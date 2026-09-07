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
    SscExportError,
    SscSongInfo,
    difficulty_for_name,
    export_chart,
    render_extension,
    render_simfile,
)


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
        self.song_tag = QLineEdit()
        self.song_tag.setPlaceholderText("Group/Song folder pair for #SONG")
        form.addRow("Title", self.title)
        form.addRow("Artist", self.artist)
        form.addRow("Music file", self.music)
        form.addRow("Difficulty", self.difficulty)
        form.addRow("", self.extension)
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


def _report_diagnostics(window, diagnostics: list[tuple[str, str]]) -> None:
    if not diagnostics:
        return
    dialog = QDialog(window)
    dialog.setWindowTitle("SSC export diagnostics")
    layout = QVBoxLayout(dialog)
    layout.addWidget(
        QLabel("The simfile was written. These details have no SSC representation:")
    )
    body = "\n".join(f"{name}: {message}" for name, message in diagnostics)
    text = QPlainTextEdit(body)
    text.setReadOnly(True)
    layout.addWidget(text)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    dialog.resize(640, 320)
    dialog.exec()


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
        charts.append((entry.path, document))
    if not charts:
        QMessageBox.information(
            window, "Export to SSC", "The folder holds no exportable chart."
        )
        return

    dialog = SscExportDialog(
        window, workspace.root.name, [path.name for path, _ in charts]
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    chosen = dialog.selected_difficulty()
    rendered = []
    diagnostics: list[tuple[str, str]] = []
    for path, document in charts:
        try:
            report = export_chart(
                document,
                description=path.name,
                difficulty=chosen or difficulty_for_name(path.name),
            )
        except SscExportError as exc:
            QMessageBox.critical(window, "Export to SSC failed", f"{path.name}: {exc}")
            return
        rendered.append((path, report.chart))
        diagnostics.extend(
            (path.name, f"{item.code}: {item.message}") for item in report.diagnostics
        )

    if dialog.extension.isChecked():
        tag = dialog.song_tag.text().strip()
        if not tag:
            QMessageBox.warning(
                window, "Export to SSC", "A .ssc.ext companion needs a song tag."
            )
            return
        try:
            for path, chart in rendered:
                target = path.with_name(path.stem + ".ssc.ext")
                target.write_bytes(render_extension(chart, tag).encode("utf-8"))
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
            target.write_bytes(text.encode("utf-8"))
        except OSError as exc:
            QMessageBox.critical(window, "Export to SSC failed", str(exc))
            return
        written = str(target)

    window.statusBar().showMessage(f"Exported to {written}", 8000)
    _report_diagnostics(window, diagnostics)


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
