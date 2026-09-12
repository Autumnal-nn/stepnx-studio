from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidgetItem,
    QVBoxLayout,
)

from stepnx.authoring.random_state import RandomPoolPolicy, probability_error
from stepnx.exporters import (
    SscExportError,
    SscRandomExportReport,
    SscSongInfo,
    compile_ssc_export,
    render_compiled_reports,
    render_compiled_simfile,
    render_simfile,
)


_SSC_FILTER = "XSanity SSC (*.ssc);;All files (*)"
_PLAYABLE_AUDIO_SUFFIXES = frozenset({".flac", ".mp2", ".mp3", ".ogg", ".wav"})
_PREFLIGHT_HELPERS = 72
_POOL_TIERS_2520 = (72, 140, 360, 2520)
_IGNORE_PREFLIGHT_DIAGNOSTICS = frozenset({"ssc.random-probability-approximation"})


@dataclass(frozen=True, slots=True)
class SscGuiExportDefaults:
    description: str
    title: str
    music: str
    target: Path


@dataclass(frozen=True, slots=True)
class SscPoolOption:
    helper_count: int
    max_error_pp: float
    estimated_bytes: int


@dataclass(frozen=True, slots=True)
class SscChartPreflight:
    document_index: int
    source_name: str
    description: str
    document: object
    sample_report: SscRandomExportReport | None
    steps_type: str
    blocked: bool
    warnings: tuple[str, ...]
    options: tuple[SscPoolOption, ...]
    default_helpers: int

    @property
    def has_random(self) -> bool:
        return bool(self.sample_report and self.sample_report.helper_count)

    @property
    def needs_attention(self) -> bool:
        return self.blocked or bool(self.warnings) or len(self.options) > 1


def _clean_field(value: str) -> str:
    """Keep guessed metadata from accidentally terminating an SSC tag."""

    return " ".join(str(value).replace(";", " ").splitlines()).strip()


def _file_menu(window) -> QMenu | None:
    return next(
        (
            menu
            for menu in window.menuBar().findChildren(QMenu)
            if menu.title().replace("&", "").strip().casefold() == "file"
        ),
        None,
    )


def _preferred_music(workspace) -> str:
    selected = getattr(workspace, "selected_audio", None)
    if selected is not None:
        selected_path = Path(selected)
        if selected_path.suffix.casefold() in _PLAYABLE_AUDIO_SUFFIXES:
            return _clean_field(selected_path.name)

    for candidate in getattr(workspace, "audio_candidates", ()):
        path = Path(candidate.path)
        if path.suffix.casefold() in _PLAYABLE_AUDIO_SUFFIXES:
            return _clean_field(path.name)
    return ""


def _export_defaults(workspace, entry=None) -> SscGuiExportDefaults:
    root = Path(workspace.root)
    description = "" if entry is None else _clean_field(Path(entry.path).stem)
    return SscGuiExportDefaults(
        description=description,
        title=_clean_field(root.name),
        music=_preferred_music(workspace),
        target=root / "STEP.SSC",
    )


def _diagnostic_lines(report: SscRandomExportReport) -> list[str]:
    lines: list[str] = []
    for item in report.diagnostics:
        where = []
        if item.split_index is not None:
            where.append(f"split {item.split_index + 1}")
        if item.block_index is not None:
            where.append(f"block {item.block_index + 1}")
        if item.row_index is not None:
            where.append(f"row {item.row_index + 1}")
        if item.lane is not None:
            where.append(f"lane {item.lane + 1}")
        suffix = f" [{', '.join(where)}]" if where else ""
        count = f" x{item.occurrences}" if item.occurrences > 1 else ""
        lines.append(f"{item.code}{count}{suffix}: {item.message}")
    return lines


def _write_text_atomic(target: Path, text: str) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.stepnx-tmp")
    try:
        temporary.write_bytes(text.encode("utf-8"))
        temporary.replace(target)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _publish_diagnostics(window, source_name: str, report: SscRandomExportReport) -> None:
    tree = getattr(window, "diagnostics", None)
    if tree is None:
        return
    for item in report.diagnostics:
        count = f" (x{item.occurrences})" if item.occurrences > 1 else ""
        QTreeWidgetItem(
            tree,
            [
                "warning",
                item.code,
                f"{source_name}:ssc",
                item.message + count,
            ],
        )
    if report.diagnostics:
        tree.resizeColumnToContents(0)
        tree.resizeColumnToContents(1)


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


def _estimate_report_sizes(
    report: SscRandomExportReport,
    song: SscSongInfo,
    helper_counts: tuple[int, ...],
) -> dict[int, int]:
    """Estimate larger pools from a cheap rendered sample.

    Helper sections dominate large random SSCs. We render the preflight pool,
    subtract an approximate one-base-chart envelope, and scale the measured
    average helper payload. This deliberately labels the result as an estimate;
    final helpers can vary slightly with branch content.
    """

    sample_text = render_compiled_simfile(report, song)
    sample_size = len(sample_text.encode("utf-8"))
    if report.helper_count <= 0:
        return {count: sample_size for count in helper_counts}

    base_size = len(render_simfile([report.charts[0].chart], song).encode("utf-8"))
    helper_bytes = max(1.0, (sample_size - base_size) / report.helper_count)
    return {
        count: max(base_size, round(base_size + helper_bytes * count))
        for count in helper_counts
    }


def _pool_counts(report: SscRandomExportReport) -> tuple[int, ...]:
    exact = report.program.pool.exact_helper_count
    if exact <= 0:
        return (0,)
    if exact <= _PREFLIGHT_HELPERS:
        return (exact,)
    if exact == 2520:
        return _POOL_TIERS_2520

    maximum_arity = max(report.program.analysis.random_arities, default=1)
    candidates = [
        count
        for count in (*_POOL_TIERS_2520[:-1], exact)
        if maximum_arity <= count <= exact
    ]
    return tuple(dict.fromkeys(candidates)) or (exact,)


def _pool_options(
    report: SscRandomExportReport,
    song: SscSongInfo,
) -> tuple[SscPoolOption, ...]:
    counts = _pool_counts(report)
    estimates = _estimate_report_sizes(report, song, counts)
    arities = report.program.analysis.random_arities
    options: list[SscPoolOption] = []
    for count in counts:
        if count == 0:
            error_pp = 0.0
        else:
            error_pp = max((probability_error(count, arity) for arity in arities), default=0.0) * 100.0
        options.append(SscPoolOption(count, error_pp, estimates[count]))
    return tuple(options)


def _default_pool(options: tuple[SscPoolOption, ...]) -> int:
    counts = {option.helper_count for option in options}
    if 360 in counts:
        return 360
    return options[0].helper_count if options else 0


def _current_document(window, index: int, entry):
    sessions = getattr(window, "sessions", {})
    session = sessions.get(index)
    return entry.document if session is None else session.current


def _preflight_folder(window, workspace, song: SscSongInfo) -> tuple[SscChartPreflight, ...]:
    rows: list[SscChartPreflight] = []
    sample_policy = RandomPoolPolicy(max_probability_error=0.0, max_helpers=_PREFLIGHT_HELPERS)

    for index, entry in enumerate(workspace.documents):
        document = _current_document(window, index, entry)
        source_name = Path(entry.path).name
        description = _clean_field(Path(entry.path).stem)
        if source_name.casefold() == "lm.nx" or getattr(document, "effective_lightmap", False):
            rows.append(
                SscChartPreflight(
                    index,
                    source_name,
                    description,
                    document,
                    None,
                    "Lightmap",
                    True,
                    ("Lightmap has no SSC chart representation and will not be exported.",),
                    (),
                    0,
                )
            )
            continue

        try:
            report = compile_ssc_export(
                document,
                description=description,
                policy=sample_policy,
            )
            options = _pool_options(report, song)
            warnings = [
                line
                for item, line in zip(report.diagnostics, _diagnostic_lines(report))
                if item.code not in _IGNORE_PREFLIGHT_DIAGNOSTICS
            ]
            if report.program.pool.exact_helper_count > _PREFLIGHT_HELPERS:
                warnings.append(
                    f"Large random pool: exact marginals need {report.program.pool.exact_helper_count} "
                    "helpers; choose the runtime size/accuracy trade-off."
                )
            rows.append(
                SscChartPreflight(
                    index,
                    source_name,
                    description,
                    document,
                    report,
                    report.charts[0].chart.steps_type,
                    False,
                    tuple(warnings),
                    options,
                    _default_pool(options),
                )
            )
        except (SscExportError, ValueError) as exc:
            rows.append(
                SscChartPreflight(
                    index,
                    source_name,
                    description,
                    document,
                    None,
                    "unsupported",
                    True,
                    (str(exc),),
                    (),
                    0,
                )
            )

    # T sees the global DIVISION pool for its StepsType. Flag every member of a
    # potential collision so the selection dialog explains why both cannot be
    # exported together yet.
    groups: dict[str, list[int]] = {}
    for row_index, row in enumerate(rows):
        if not row.blocked and row.has_random:
            groups.setdefault(row.steps_type, []).append(row_index)
    for steps_type, indices in groups.items():
        if len(indices) <= 1:
            continue
        message = (
            f"Multiple random {steps_type} charts share XSanity's DIVISION pool; "
            "select at most one until a narrower Wrap filter is proven."
        )
        for row_index in indices:
            rows[row_index] = replace(rows[row_index], warnings=rows[row_index].warnings + (message,))

    return tuple(rows)


class _FolderSscExportDialog(QDialog):
    def __init__(self, parent, rows: tuple[SscChartPreflight, ...]):
        super().__init__(parent)
        self.setWindowTitle("Select charts for XSanity SSC export")
        self.resize(1050, 480)
        self._rows = rows
        self._combos: dict[int, QComboBox] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Charts with warnings need review. Lightmaps are blocked. For large random charts, "
                "choose the helper-pool size before generation."
            )
        )
        self.table = QTableWidget(len(rows), 6, self)
        self.table.setHorizontalHeaderLabels(
            ["Export", "Chart", "StepsType", "Random pool", "Estimated size", "Warnings"]
        )
        layout.addWidget(self.table)
        self.total_label = QLabel(self)
        layout.addWidget(self.total_label)

        for row_index, row in enumerate(rows):
            check = QTableWidgetItem()
            check.setCheckState(Qt.CheckState.Unchecked if row.blocked else Qt.CheckState.Checked)
            if row.blocked:
                check.setFlags(check.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row_index, 0, check)
            self.table.setItem(row_index, 1, QTableWidgetItem(row.source_name))
            self.table.setItem(row_index, 2, QTableWidgetItem(row.steps_type))

            if row.options:
                combo = QComboBox(self.table)
                for option in row.options:
                    if option.helper_count == 0:
                        label = "none"
                    else:
                        accuracy = "exact" if option.max_error_pp < 1e-9 else f"~{option.max_error_pp:.3g} pp"
                        label = f"{option.helper_count} helpers ({accuracy}, ~{_format_size(option.estimated_bytes)})"
                    combo.addItem(label, option.helper_count)
                wanted = combo.findData(row.default_helpers)
                if wanted >= 0:
                    combo.setCurrentIndex(wanted)
                combo.currentIndexChanged.connect(self._refresh_total)
                self.table.setCellWidget(row_index, 3, combo)
                self._combos[row_index] = combo
                self.table.setItem(row_index, 4, QTableWidgetItem(""))
            else:
                self.table.setItem(row_index, 3, QTableWidgetItem("blocked" if row.blocked else "none"))
                self.table.setItem(row_index, 4, QTableWidgetItem("—"))

            self.table.setItem(
                row_index,
                5,
                QTableWidgetItem(" | ".join(row.warnings) if row.warnings else "None"),
            )

        self.table.itemChanged.connect(self._refresh_total)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_total()

    def _option(self, row_index: int) -> SscPoolOption | None:
        row = self._rows[row_index]
        combo = self._combos.get(row_index)
        if combo is None:
            return row.options[0] if row.options else None
        helper_count = int(combo.currentData())
        return next((option for option in row.options if option.helper_count == helper_count), None)

    def selected(self) -> tuple[tuple[SscChartPreflight, int], ...]:
        result: list[tuple[SscChartPreflight, int]] = []
        for row_index, row in enumerate(self._rows):
            item = self.table.item(row_index, 0)
            if row.blocked or item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            option = self._option(row_index)
            result.append((row, 0 if option is None else option.helper_count))
        return tuple(result)

    def _refresh_total(self, *_args) -> None:
        total = 0
        selected_count = 0
        for row_index, row in enumerate(self._rows):
            item = self.table.item(row_index, 0)
            if row.blocked or item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            selected_count += 1
            option = self._option(row_index)
            if option is not None:
                total += option.estimated_bytes
                size_item = self.table.item(row_index, 4)
                if size_item is not None:
                    size_item.setText("~" + _format_size(option.estimated_bytes))
        self.total_label.setText(
            f"Selected charts: {selected_count} | Estimated combined chart payload: ~{_format_size(total)}"
        )

    def _accept_selection(self) -> None:
        selected = self.selected()
        if not selected:
            QMessageBox.warning(self, "Nothing selected", "Select at least one playable chart.")
            return
        random_types: dict[str, list[str]] = {}
        for row, _helpers in selected:
            if row.has_random:
                random_types.setdefault(row.steps_type, []).append(row.source_name)
        conflicts = {key: value for key, value in random_types.items() if len(value) > 1}
        if conflicts:
            details = "\n".join(
                f"{steps_type}: {', '.join(names)}" for steps_type, names in conflicts.items()
            )
            QMessageBox.warning(
                self,
                "Random DIVISION pool conflict",
                "XSanity cannot safely distinguish these random helper pools yet. "
                "Deselect all but one random chart per StepsType.\n\n" + details,
            )
            return
        self.accept()


def _selected_without_dialog(rows: tuple[SscChartPreflight, ...]) -> tuple[tuple[SscChartPreflight, int], ...]:
    return tuple(
        (row, row.default_helpers)
        for row in rows
        if not row.blocked
    )


def _compile_selection(
    selections: tuple[tuple[SscChartPreflight, int], ...],
) -> tuple[SscRandomExportReport, ...]:
    reports: list[SscRandomExportReport] = []
    for row, helper_count in selections:
        sample = row.sample_report
        if sample is not None and helper_count == sample.helper_count:
            reports.append(sample)
            continue
        if helper_count <= 0:
            policy = RandomPoolPolicy(max_probability_error=0.0, max_helpers=1)
        else:
            policy = RandomPoolPolicy(max_probability_error=0.0, max_helpers=helper_count)
        reports.append(
            compile_ssc_export(
                row.document,
                description=row.description,
                policy=policy,
            )
        )
    return tuple(reports)


def _choose_ssc_export(window) -> None:
    workspace = getattr(window, "workspace", None)
    if workspace is None:
        QMessageBox.information(window, "Export XSanity SSC", "Open a chart folder first.")
        return

    defaults = _export_defaults(workspace)
    song = SscSongInfo(title=defaults.title, music=defaults.music)

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    window.statusBar().showMessage("Scanning folder for XSanity SSC export…")
    QApplication.processEvents()
    try:
        rows = _preflight_folder(window, workspace, song)
    finally:
        QApplication.restoreOverrideCursor()

    playable = tuple(row for row in rows if not row.blocked)
    if not playable:
        details = "\n".join(f"{row.source_name}: {' | '.join(row.warnings)}" for row in rows)
        QMessageBox.critical(
            window,
            "Cannot export XSanity SSC",
            "No playable chart can be exported from this folder.\n\n" + details,
        )
        return

    if any(row.needs_attention for row in rows):
        dialog = _FolderSscExportDialog(window, rows)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selections = dialog.selected()
    else:
        selections = _selected_without_dialog(rows)

    selected, _ = QFileDialog.getSaveFileName(
        window,
        "Export folder as XSanity SSC",
        str(defaults.target),
        _SSC_FILTER,
    )
    if not selected:
        return
    target = Path(selected)
    if target.suffix.casefold() != ".ssc":
        target = target.with_suffix(".ssc")

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    window.statusBar().showMessage(
        "Generating XSanity SSC helpers… large exact pools can take a while."
    )
    QApplication.processEvents()
    try:
        reports = _compile_selection(selections)
        text = render_compiled_reports(reports, song)
        _write_text_atomic(target, text)
    except (OSError, SscExportError, ValueError) as exc:
        QMessageBox.critical(window, "XSanity SSC export failed", str(exc))
        return
    finally:
        QApplication.restoreOverrideCursor()

    for (row, _helpers), report in zip(selections, reports):
        _publish_diagnostics(window, row.source_name, report)

    helper_total = sum(report.helper_count for report in reports)
    size = len(text.encode("utf-8"))
    window.statusBar().showMessage(
        f"Exported {len(reports)} chart(s) to {target.name}: {helper_total} helper(s), {_format_size(size)}",
        10000,
    )

    diagnostics = sum(len(report.diagnostics) for report in reports)
    if diagnostics:
        QMessageBox.warning(
            window,
            "XSanity SSC exported with diagnostics",
            f"Wrote {target}.\n\n"
            f"Exported {len(reports)} playable chart(s), {helper_total} random helper(s), "
            f"final size {_format_size(size)}. Diagnostics were appended to the Diagnostics panel.",
        )
    else:
        QMessageBox.information(
            window,
            "XSanity SSC exported",
            f"Wrote {target}.\n\n"
            f"Exported {len(reports)} playable chart(s), {helper_total} random helper(s), "
            f"final size {_format_size(size)}.",
        )


def _refresh_action(window, action: QAction) -> None:
    action.setEnabled(getattr(window, "workspace", None) is not None)


def install_phase12_ssc_export(window) -> None:
    if getattr(window, "_phase12_ssc_export_installed", False):
        return
    window._phase12_ssc_export_installed = True

    menu = _file_menu(window)
    if menu is None:
        raise RuntimeError("File menu not found while installing XSanity SSC export")

    action = QAction("Export folder as XSanity SSC…", window)
    action.setToolTip(
        "Experimental NX/NX10 folder to one XSanity SSC; Lightmap is excluded and random pools are reviewed"
    )
    action.triggered.connect(lambda *_: _choose_ssc_export(window))

    actions = menu.actions()
    nfo_index = next(
        (
            index
            for index, candidate in enumerate(actions)
            if "export nfo mirror" in candidate.text().replace("&", "").casefold()
        ),
        None,
    )
    if nfo_index is None or nfo_index + 1 >= len(actions):
        menu.addAction(action)
    else:
        menu.insertAction(actions[nfo_index + 1], action)

    menu.aboutToShow.connect(lambda: _refresh_action(window, action))
    action.setEnabled(False)
    window.phase12_ssc_export_action = action


__all__ = [
    "SscChartPreflight",
    "SscGuiExportDefaults",
    "SscPoolOption",
    "install_phase12_ssc_export",
]
