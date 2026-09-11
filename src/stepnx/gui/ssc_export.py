"""File-menu action that exports the open folder as an XSanity SSC simfile."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from stepnx.exporters.ssc import (
    SSC_DIFFICULTIES,
    UNKNOWN_NOTE_EMPTY,
    UNKNOWN_NOTE_ERROR,
    SscExportError,
    SscSongInfo,
    difficulty_for_name,
    export_chart,
    render_extension,
    render_simfile,
)


def _write_atomic(target: Path, text: str) -> None:
    """Write ``text`` so a failed write cannot leave a half-written file behind."""

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".stepnx-tmp")
    try:
        temporary.write_bytes(text.encode("utf-8"))
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _file_menu(window) -> QMenu | None:
    return next(
        (
            menu
            for menu in window.menuBar().findChildren(QMenu)
            if menu.title().replace("&", "").strip().casefold() == "file"
        ),
        None,
    )


class SscExportDialog(QDialog):
    """Collects the song header fields that an NX20 document does not carry."""

    def __init__(self, parent, default_title: str, chart_names: list[str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export to SSC (XSanity)")
        layout = QVBoxLayout(self)

        listed = "\n".join(f"- {name}" for name in chart_names[:12])
        if len(chart_names) > 12:
            listed += f"\n- and {len(chart_names) - 12} more"
        summary = QLabel(
            f"{len(chart_names)} chart(s) will be written into one simfile:\n{listed}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        form = QFormLayout()
        self.title = QLineEdit(default_title)
        self.artist = QLineEdit()
        self.music = QLineEdit()
        self.difficulty = QComboBox()
        self.difficulty.addItem("From chart filename")
        self.difficulty.addItems(SSC_DIFFICULTIES)
        self.extension = QCheckBox("Write .ssc.ext companions instead of one .ssc")
        self.keep_unknown = QCheckBox(
            "Write unsupported notes as empty lanes instead of stopping"
        )
        self.song_tag = QLineEdit()
        self.song_tag.setPlaceholderText("Group/Song folder pair for #SONG")
        form.addRow("Title", self.title)
        form.addRow("Artist", self.artist)
        form.addRow("Music file", self.music)
        form.addRow("Difficulty", self.difficulty)
        form.addRow("", self.extension)
        form.addRow("", self.keep_unknown)
        form.addRow("Song tag", self.song_tag)
        layout.addLayout(form)

        self.song_tag.setEnabled(False)
        self.extension.toggled.connect(self.song_tag.setEnabled)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def song_info(self) -> SscSongInfo:
        return SscSongInfo(
            title=self.title.text().strip(),
            artist=self.artist.text().strip(),
            music=self.music.text().strip(),
        )

    def selected_difficulty(self) -> str | None:
        if self.difficulty.currentIndex() == 0:
            return None
        return self.difficulty.currentText()


def _confirm_report(window, route: str, diagnostics: list[tuple[str, str]]) -> bool:
    """Show what the export will lose and let the user stop before anything is written."""

    dialog = QDialog(window)
    dialog.setWindowTitle("SSC export report")
    layout = QVBoxLayout(dialog)
    heading = (
        f"Route to export: {route}\n\n"
        "The projection is one-way. These details have no SSC representation "
        "and will not be written:"
        if diagnostics
        else f"Route to export: {route}\n\nNothing was reported as unrepresented."
    )
    label = QLabel(heading)
    label.setWordWrap(True)
    layout.addWidget(label)
    body = "\n".join(f"{name}: {message}" for name, message in diagnostics)
    if body:
        text = QPlainTextEdit(body)
        text.setReadOnly(True)
        layout.addWidget(text)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(680, 360)
    return dialog.exec() == QDialog.DialogCode.Accepted


def _snapshot_for(window, document_index: int):
    """Return the snapshot the editor is showing, so the exported route matches it."""

    from stepnx.gui.timeline_widget import TimelineWidget

    tabs = getattr(window, "tabs", None)
    documents = getattr(window, "widget_documents", {})
    if tabs is None:
        return None
    for index in range(tabs.count()):
        widget = tabs.widget(index)
        if (
            isinstance(widget, TimelineWidget)
            and documents.get(widget) == document_index
        ):
            return getattr(widget, "snapshot", None)
    return None


def _confirm_overwrite(window, targets: list[Path]) -> bool:
    listed = "\n".join(f"- {target.name}" for target in targets[:12])
    if len(targets) > 12:
        listed += f"\n- and {len(targets) - 12} more"
    answer = QMessageBox.question(
        window,
        "Replace existing companions",
        f"{len(targets)} file(s) already exist and will be replaced:\n{listed}",
        QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    return answer == QMessageBox.StandardButton.Save


def export_workspace_to_ssc(window) -> None:
    """Project every non-Lightmap chart of the open folder onto one SSC simfile."""

    workspace = getattr(window, "workspace", None)
    if workspace is None:
        QMessageBox.information(window, "Export to SSC", "Open a chart folder first.")
        return

    charts = []
    for index, entry in enumerate(workspace.documents):
        document = window.sessions[index].current
        if document.effective_lightmap:
            continue
        charts.append((entry.path, document, _snapshot_for(window, index)))
    if not charts:
        QMessageBox.information(
            window, "Export to SSC", "The folder holds no exportable chart."
        )
        return

    dialog = SscExportDialog(
        window, workspace.root.name, [path.name for path, _, _ in charts]
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    chosen = dialog.selected_difficulty()
    rendered = []
    diagnostics: list[tuple[str, str]] = []
    routes: list[str] = []
    for path, document, snapshot in charts:
        try:
            report = export_chart(
                document,
                description=path.name,
                difficulty=chosen or difficulty_for_name(path.name),
                snapshot=snapshot,
                unknown_notes=UNKNOWN_NOTE_EMPTY
                if dialog.keep_unknown.isChecked()
                else UNKNOWN_NOTE_ERROR,
            )
        except SscExportError as exc:
            QMessageBox.critical(window, "Export to SSC failed", f"{path.name}: {exc}")
            return
        rendered.append((path, report.chart))
        routes.append(f"{path.name}: {report.route_summary}")
        diagnostics.extend(
            (
                path.name,
                f"{item.code}: {item.message}"
                + (f" (x{item.occurrences})" if item.occurrences > 1 else ""),
            )
            for item in report.diagnostics
        )

    if not _confirm_report(window, "; ".join(routes), diagnostics):
        return

    if dialog.extension.isChecked():
        tag = dialog.song_tag.text().strip()
        if not tag:
            QMessageBox.warning(
                window, "Export to SSC", "A .ssc.ext companion needs a song tag."
            )
            return
        targets = [
            (path.with_name(path.stem + ".ssc.ext"), chart) for path, chart in rendered
        ]
        existing = [target for target, _ in targets if target.exists()]
        if existing and not _confirm_overwrite(window, existing):
            return
        try:
            for target, chart in targets:
                _write_atomic(target, render_extension(chart, tag))
        except OSError as exc:
            QMessageBox.critical(window, "Export to SSC failed", str(exc))
            return
        written = f"{len(rendered)} .ssc.ext companion(s) in {workspace.root}"
    else:
        default = workspace.root / f"{workspace.root.name}.ssc"
        selected, _ = QFileDialog.getSaveFileName(
            window, "Export to SSC (XSanity)", str(default), "SSC simfile (*.ssc)"
        )
        if not selected:
            return
        target = Path(selected)
        text = render_simfile([chart for _, chart in rendered], dialog.song_info())
        try:
            _write_atomic(target, text)
        except OSError as exc:
            QMessageBox.critical(window, "Export to SSC failed", str(exc))
            return
        written = str(target)

    window.statusBar().showMessage(f"Exported to {written}", 8000)


def install_ssc_export(window) -> None:
    """Add the SSC export action next to the existing mirror export."""

    if getattr(window, "_ssc_export_installed", False):
        return
    window._ssc_export_installed = True

    menu = _file_menu(window)
    if menu is None:
        raise RuntimeError("File menu not found while installing the SSC export")

    action = QAction("Export to SSC (XSanity)...", window)
    action.setToolTip(
        "Write every non-Lightmap chart of this folder as an XSanity SSC simfile"
    )
    action.triggered.connect(lambda *_: export_workspace_to_ssc(window))

    existing = menu.actions()
    anchor = next(
        (item for item in existing if "mirror" in item.text().casefold()), None
    )
    if anchor is None:
        menu.addAction(action)
    else:
        index = existing.index(anchor)
        following = existing[index + 1 :]
        if following:
            menu.insertAction(following[0], action)
        else:
            menu.addAction(action)

    menu.aboutToShow.connect(
        lambda: action.setEnabled(getattr(window, "workspace", None) is not None)
    )
    window.ssc_export_action = action
