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
    QInputDialog,
    QPushButton,
    QVBoxLayout,
)

from stepnx.authoring.editor_controller import EditorContextError, EditorController, InteractionTool
from stepnx.gui.stepedit_structure_actions import plan_structure_action
from stepnx.authoring.selection import CellSelection
from stepnx.gui.stepedit_visual_style import EDITOR_ZOOM_PRESETS
from stepnx.authoring.tools import NoteTool
from stepnx.gui.stepedit_experimental_viewport import StepEditExperimentalViewport


class StepEditExperimentalDialog(QDialog):
    """Experimental mouse-editing session; closing does not save to disk."""

    def __init__(self, controller: EditorController, *, tap_raw=None, hold_raw=None, noteskin_pack=None, parent=None) -> None:
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
            ("Toggle tap / drag Hold", InteractionTool.TOGGLE),
            ("Draw Hold", InteractionTool.HOLD),
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
        for percent in EDITOR_ZOOM_PRESETS:
            self.zoom_combo.addItem(f"{percent}%", percent)
        self.zoom_combo.setCurrentIndex(EDITOR_ZOOM_PRESETS.index(100))
        toolbar.addWidget(self.zoom_combo)

        self.viewport_widget = StepEditExperimentalViewport(
            controller, tap_raw=tap_raw, hold_raw=hold_raw, noteskin_pack=noteskin_pack, parent=self,
        )
        root.addWidget(self.viewport_widget, 1)

        lower = QHBoxLayout()
        root.addLayout(lower)
        self.status = QLabel(
            "Toggle: tap / drag Hold. Draw Hold: drag to create, click Hold to erase. Lightmap stays in Studio.",
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
            lambda _: self.viewport_widget.set_zoom(int(self.zoom_combo.currentData()))
        )
        self.split_combo.currentIndexChanged.connect(self._on_split_changed)
        self.block_combo.currentIndexChanged.connect(self._on_block_changed)
        self.viewport_widget.routeChanged.connect(self._populate_splits)
        self.viewport_widget.structureRequested.connect(self._on_structure_requested)
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

    def _on_structure_requested(self, request) -> None:
        action, scope, row_index = request
        controller = self.viewport_widget.controller
        try:
            controller._validate_scope(scope)
            doc = controller.document
            requested_rows = None
            if action == "resize-split":
                from stepnx.gui.typed_inputs import ResizeSplitDialog

                block = controller.snapshot.split(scope.split_id).block(scope.block_id)
                dialog = ResizeSplitDialog(
                    block.row_count,
                    beat_split=int(block.beat_split),
                    beat_measure=int(block.beat_measure),
                    parent=self,
                )
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                requested_rows = dialog.requested_rows()
            plan = plan_structure_action(
                doc, action, scope.split_id, scope.block_id,
                row_index=row_index, requested_rows=requested_rows,
            )
            # A structural dialog runs its own Qt event loop. Validate
            # original document/Block again immediately before executing.
            if plan.confirmation:
                decision = QMessageBox.question(
                    self, plan.description, plan.confirmation,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if decision != QMessageBox.StandardButton.Yes:
                    return
            controller._validate_scope(scope)
            self.viewport_widget._cancel_interaction()
            scroll = self.viewport_widget._scroll_y()
            updated = controller.execute(plan.command)
            if updated is doc:
                return
            controller.session.selection = CellSelection()
            self.viewport_widget._rebuild_layout(scroll_y=scroll)
            self.viewport_widget.documentChanged.emit(updated)
            self.viewport_widget.routeChanged.emit()
            self.status.setText(f"{plan.description}: modified in memory; Save All in Studio.")
        except (EditorContextError, ValueError, KeyError, IndexError) as exc:
            QMessageBox.warning(self, "Cannot edit structure", str(exc))

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
    # Keep a Python reference; short-lived QMenu wrappers can outlive their
    # underlying C++ menu on some PySide6/offscreen configurations.
    menu = window.menuBar().addMenu("&Experimental")
    window.stepedit_experimental_menu = menu
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

        def hold_raw(part: NoteTool) -> bytes:
            from stepnx.gui.phase10_install import _regular_note_raw
            return _regular_note_raw(
                window, part, window.tool_value.value(),
                window._selected_function(), window._selected_visibility(),
            )

        dialog = StepEditExperimentalDialog(
            controller, tap_raw=tap_raw, hold_raw=hold_raw,
            noteskin_pack=getattr(window, "noteskin", None), parent=window,
        )
        try:
            dialog.exec()
        finally:
            # Modal interaction keeps the legacy view inactive. Once the user
            # returns, reuse the full existing workspace/save/recovery path.
            if stack.current is not original_document:
                window._apply_document(doc_index, source_view, stack.current)
            dialog.deleteLater()

    action.triggered.connect(launch)
