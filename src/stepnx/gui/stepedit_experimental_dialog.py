"""Opt-in modal integration with the live StepNX workspace.

The legacy Timeline remains open and authoritative for file publication.
A modal editor prevents concurrent frontend edits; changes are synchronized
once through the existing MainWindow._apply_document route on close.
"""
from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from stepnx.authoring.editor_controller import EditorController, InteractionTool
from stepnx.authoring.stepedit_layout import STEPEDIT_VERTICAL_ZOOMS
from stepnx.authoring.tools import NoteTool
from stepnx.gui.stepedit_experimental_viewport import StepEditExperimentalViewport


class StepEditExperimentalDialog(QDialog):
    """Experimental mouse-editing session; closing does not save to disk."""

    def __init__(self, controller: EditorController, *, tap_raw=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("STEPEdit-inspired viewport (experimental)")
        self.setModal(True)
        self.resize(970, 700)
        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        root.addLayout(toolbar)

        toolbar.addWidget(QLabel("Tool"))
        self.tool_combo = QComboBox(self)
        for label, tool in (
            ("Toggle tap", InteractionTool.TOGGLE),
            ("Paint taps", InteractionTool.ADD),
            ("Erase cells", InteractionTool.ERASE),
            ("Select", InteractionTool.SELECT),
        ):
            self.tool_combo.addItem(label, tool)
        toolbar.addWidget(self.tool_combo)

        toolbar.addWidget(QLabel("Split"))
        self.split_combo = QComboBox(self)
        toolbar.addWidget(self.split_combo)
        toolbar.addWidget(QLabel("Block"))
        self.block_combo = QComboBox(self)
        toolbar.addWidget(self.block_combo)

        toolbar.addWidget(QLabel("Zoom"))
        self.zoom_combo = QComboBox(self)
        for zoom in STEPEDIT_VERTICAL_ZOOMS:
            self.zoom_combo.addItem(f"{zoom}×", zoom)
        self.zoom_combo.setCurrentIndex(STEPEDIT_VERTICAL_ZOOMS.index(4))
        toolbar.addWidget(self.zoom_combo)

        self.viewport_widget = StepEditExperimentalViewport(controller, tap_raw=tap_raw, parent=self)
        root.addWidget(self.viewport_widget, 1)

        lower = QHBoxLayout()
        root.addLayout(lower)
        self.status = QLabel(
            "Experimental. Tap/paint/select only; Hold and Lightmap edits remain in Studio.",
            self,
        )
        lower.addWidget(self.status, 1)
        close = QPushButton("Return to Studio", self)
        close.clicked.connect(self.accept)
        lower.addWidget(close)

        self.tool_combo.currentIndexChanged.connect(
            lambda _: self.viewport_widget.set_tool(self.tool_combo.currentData())
        )
        self.zoom_combo.currentIndexChanged.connect(
            lambda _: self.viewport_widget.set_zoom(float(self.zoom_combo.currentData()))
        )
        self.split_combo.currentIndexChanged.connect(self._on_split_changed)
        self.block_combo.currentIndexChanged.connect(self._on_block_changed)
        self.viewport_widget.routeChanged.connect(self._populate_splits)
        self.viewport_widget.statusMessage.connect(self.status.setText)
        self.viewport_widget.selectionChanged.connect(
            lambda selection: self.status.setText(f"{len(selection.targets)} cells selected")
        )
        self.viewport_widget.documentChanged.connect(
            lambda _: self.status.setText(
                "Document edited in memory. Return to Studio to save using Save All."
            )
        )
        for shortcut, callback in (
            ("Ctrl+Z", self.viewport_widget.undo),
            ("Ctrl+Y", self.viewport_widget.redo),
        ):
            binding = QShortcut(QKeySequence(shortcut), self)
            binding.activated.connect(callback)
        self._populate_splits()

    def _populate_splits(self) -> None:
        previously = self.split_combo.currentData()
        self.split_combo.blockSignals(True)
        try:
            self.split_combo.clear()
            for split in self.viewport_widget.controller.snapshot.splits:
                if split.blocks:
                    self.split_combo.addItem(f"{split.index + 1}", split.stable_id)
            choice = self.split_combo.findData(previously)
            if choice >= 0:
                self.split_combo.setCurrentIndex(choice)
        finally:
            self.split_combo.blockSignals(False)
        self._on_split_changed()

    def _on_split_changed(self, *_args) -> None:
        split_id = self.split_combo.currentData()
        self.block_combo.blockSignals(True)
        try:
            self.block_combo.clear()
            if split_id is None:
                return
            snap = self.viewport_widget.controller.snapshot
            selected = snap.active_block_id(split_id)
            for block in snap.split(split_id).blocks:
                self.block_combo.addItem(str(block.index + 1), block.stable_id)
            idx = self.block_combo.findData(selected)
            if idx >= 0:
                self.block_combo.setCurrentIndex(idx)
        finally:
            self.block_combo.blockSignals(False)

    def _on_block_changed(self, *_args) -> None:
        split_id, block_id = self.split_combo.currentData(), self.block_combo.currentData()
        if split_id is not None and block_id is not None:
            self.viewport_widget.select_block(split_id, block_id)

    def reject(self) -> None:
        self.viewport_widget._cancel_interaction()
        super().reject()

    def accept(self) -> None:
        self.viewport_widget._cancel_interaction()
        super().accept()


def install_stepedit_experimental(window) -> None:
    """Install one explicitly-labelled menu action after legacy wrappers."""

    if getattr(window, "_stepedit_experimental_installed", False):
        return
    window._stepedit_experimental_installed = True
    preview = next(
        (
            action.menu()
            for action in window.menuBar().actions()
            if action.menu() is not None
            and action.text().replace("&", "").strip().lower() == "preview"
        ),
        None,
    )
    menu = preview or window.menuBar().addMenu("Experimental")
    menu.addSeparator()
    action = menu.addAction("STEPEdit-inspired editor (experimental)…")
    window.stepedit_experimental_action = action

    def launch() -> None:
        doc_index = window._current_document_index()
        source_view = window.tabs.currentWidget()
        if doc_index is None or source_view is None or not hasattr(source_view, "snapshot"):
            QMessageBox.information(window, "Experimental editor", "Open a chart first.")
            return
        stack = window.sessions[doc_index]
        original_document = stack.current
        controller = EditorController(stack)
        for split_id, block_id in source_view.snapshot.active_blocks:
            try:
                controller.select_block(split_id, block_id)
            except KeyError:
                pass

        # Compose exactly the same Tap preset selected in the existing Studio.
        # The legacy adapter accounts for Source Slot and Brain Shower options.
        def tap_raw() -> bytes:
            from stepnx.gui.phase10_install import _regular_note_raw
            return _regular_note_raw(
                window, NoteTool.TAP, window.tool_value.value(),
                window._selected_function(), window._selected_visibility(),
            )

        dialog = StepEditExperimentalDialog(controller, tap_raw=tap_raw, parent=window)
        try:
            dialog.exec()
        finally:
            # Modal interaction keeps the legacy view inactive. Once the user
            # returns, reuse the full existing workspace/save/recovery path.
            if stack.current is not original_document:
                window._apply_document(doc_index, source_view, stack.current)
            dialog.deleteLater()

    action.triggered.connect(launch)
