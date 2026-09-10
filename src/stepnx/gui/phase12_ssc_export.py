from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QTreeWidgetItem

from stepnx.exporters import (
    SscExportError,
    SscRandomExportReport,
    SscSongInfo,
    compile_ssc_export,
    render_compiled_simfile,
)


_SSC_FILTER = "XSanity SSC (*.ssc);;All files (*)"
_PLAYABLE_AUDIO_SUFFIXES = frozenset({".flac", ".mp2", ".mp3", ".ogg", ".wav"})


@dataclass(frozen=True, slots=True)
class SscGuiExportDefaults:
    description: str
    title: str
    music: str
    target: Path


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


def _current_document_index(window) -> int | None:
    getter = getattr(window, "_current_document_index", None)
    if callable(getter):
        try:
            index = getter()
        except Exception:
            index = None
        if index is not None:
            return int(index)

    tree = getattr(window, "tree", None)
    item = None if tree is None else tree.currentItem()
    if item is None:
        return None
    payload = item.data(0, Qt.ItemDataRole.UserRole)
    if not payload or len(payload) < 2:
        return None
    try:
        index = int(payload[1])
    except (TypeError, ValueError):
        return None
    return index if index >= 0 else None


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


def _export_defaults(workspace, entry) -> SscGuiExportDefaults:
    source_path = Path(entry.path)
    root = Path(workspace.root)
    return SscGuiExportDefaults(
        description=_clean_field(source_path.stem),
        title=_clean_field(root.name),
        music=_preferred_music(workspace),
        target=source_path.with_suffix(".ssc"),
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


def _preflight_text(report: SscRandomExportReport, defaults: SscGuiExportDefaults) -> tuple[str, str]:
    pool = report.program.pool
    probability = "exact"
    if not report.exact_probabilities:
        probability = (
            f"approximate, max error {report.max_probability_error * 100:.3f} pp "
            f"({report.helper_count}/{pool.exact_helper_count} helper states)"
        )

    summary = [
        f"Chart: {defaults.description}",
        f"Random helpers: {report.helper_count}",
        f"Random probabilities: {probability}",
        f"Music: {defaults.music or '(not detected)'}",
    ]
    details = _diagnostic_lines(report)
    if not details:
        details = ["No conversion diagnostics."]
    return "\n".join(summary), "\n".join(details)


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


def _choose_ssc_export(window) -> None:
    workspace = getattr(window, "workspace", None)
    if workspace is None:
        QMessageBox.information(window, "Export XSanity SSC", "Open a chart folder first.")
        return

    document_index = _current_document_index(window)
    if document_index is None or not (0 <= document_index < len(workspace.documents)):
        QMessageBox.information(
            window,
            "Export XSanity SSC",
            "Open or select the NX chart you want to export first.",
        )
        return

    entry = workspace.documents[document_index]
    sessions = getattr(window, "sessions", {})
    session = sessions.get(document_index)
    document = entry.document if session is None else session.current
    defaults = _export_defaults(workspace, entry)

    try:
        report = compile_ssc_export(document, description=defaults.description)
    except (SscExportError, ValueError) as exc:
        QMessageBox.critical(window, "Cannot export XSanity SSC", str(exc))
        return

    summary, details = _preflight_text(report, defaults)
    box = QMessageBox(window)
    box.setIcon(QMessageBox.Icon.Warning if report.diagnostics else QMessageBox.Icon.Information)
    box.setWindowTitle("Experimental XSanity SSC export")
    box.setText("Review the generated SSC plan before writing it.")
    box.setInformativeText(summary)
    box.setDetailedText(details)
    box.setStandardButtons(
        QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel
    )
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    if box.exec() != QMessageBox.StandardButton.Save:
        return

    selected, _ = QFileDialog.getSaveFileName(
        window,
        "Export current chart as XSanity SSC",
        str(defaults.target),
        _SSC_FILTER,
    )
    if not selected:
        return
    target = Path(selected)
    if target.suffix.casefold() != ".ssc":
        target = target.with_suffix(".ssc")

    song = SscSongInfo(
        title=defaults.title,
        music=defaults.music,
    )
    try:
        text = render_compiled_simfile(report, song)
        _write_text_atomic(target, text)
    except (OSError, SscExportError, ValueError) as exc:
        QMessageBox.critical(window, "XSanity SSC export failed", str(exc))
        return

    _publish_diagnostics(window, entry.path.name, report)
    window.statusBar().showMessage(
        f"Exported {entry.path.name} to {target.name} with {report.helper_count} random helper(s)",
        8000,
    )

    if report.diagnostics:
        QMessageBox.warning(
            window,
            "XSanity SSC exported with diagnostics",
            f"Wrote {target}.\n\n"
            f"The export completed with {len(report.diagnostics)} diagnostic type(s). "
            "They were also appended to the Diagnostics panel.",
        )
    else:
        QMessageBox.information(
            window,
            "XSanity SSC exported",
            f"Wrote {target}.\n\n"
            "This path is still experimental until the generated T/DIVISION/O flow "
            "is validated in XSanity runtime.",
        )


def _refresh_action(window, action: QAction) -> None:
    workspace = getattr(window, "workspace", None)
    action.setEnabled(workspace is not None and _current_document_index(window) is not None)


def install_phase12_ssc_export(window) -> None:
    if getattr(window, "_phase12_ssc_export_installed", False):
        return
    window._phase12_ssc_export_installed = True

    menu = _file_menu(window)
    if menu is None:
        raise RuntimeError("File menu not found while installing XSanity SSC export")

    action = QAction("Export current chart as XSanity SSC…", window)
    action.setToolTip(
        "Experimental NX20 to XSanity SSC export, including random branch helper charts"
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
    "SscGuiExportDefaults",
    "install_phase12_ssc_export",
]
