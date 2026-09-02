from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from stepnx.authoring.split_selection import SplitSelectionByte, SetSplitSelectionByte
from stepnx.core.errors import ModelInvariantError


class SplitSelectionDialog(QDialog):
    def __init__(self, value: int, *, block_count: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Split selection byte")
        self.block_count = int(block_count)
        self._syncing = False

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "NX20 stores Split selection in one byte. 0x80 chooses a random "
            "Block when the chart is loaded. 0x40 first looks for the encoded "
            "selection bank: with bank 1..31 it follows the latest Block index "
            "selected for that bank; with no bank (raw 0x40) the lookup has "
            "nothing to follow and falls back to a fresh random choice when the "
            "Split is reached. A bank is also meaningful on conditioned/explicit "
            "selector Splits such as 0x01, whose choice can later be reused by "
            "0x41. Runtime validation shows 0x80 takes precedence when both "
            "selector bits are present. The raw field remains authoritative and "
            "can represent every byte from 0x00 through 0xFF.",
            self,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        self.random_start = QCheckBox("0x80  Random at chart load", self)
        # Attribute name retained for compatibility with the original typed
        # projection. Its meaning depends on whether a real bank (1..31) exists.
        self.random_trigger = QCheckBox(
            "0x40  Follow bank / random at block start if unbanked", self
        )
        self.random_trigger.setToolTip(
            "With bank 1..31, reuse the most recent Block index selected for "
            "that bank. With bank 0 (no bank), the lookup cannot resolve and "
            "the runtime falls back to a fresh random selection when this Split "
            "is reached."
        )
        self.force_select = QCheckBox("0x20  Force/select behavior", self)
        self.bank = QSpinBox(self)
        self.bank.setRange(0, 31)
        self.bank.setToolTip(
            "0 means no bank. Banks 1..31 retain a selected Block index. A "
            "banked Split remains meaningful even without 0x80/0x40: conditions "
            "or an explicit active candidate can establish the state that a "
            "later follower reuses."
        )
        self.raw_edit = QLineEdit(self)
        self.raw_edit.setMaxLength(4)
        self.raw_edit.setToolTip(
            "Complete raw selector byte. Accepts 0x00..0xFF or decimal 0..255. "
            "Raw entry may deliberately encode combinations such as 0xC0."
        )
        self.raw_label = QLabel(self)
        self.warning_label = QLabel(self)
        self.warning_label.setWordWrap(True)

        form.addRow("Random at load:", self.random_start)
        form.addRow("0x40 behavior:", self.random_trigger)
        form.addRow("Force select:", self.force_select)
        form.addRow("Selection bank (0 = none):", self.bank)
        form.addRow("Raw byte:", self.raw_edit)
        form.addRow("Decoded:", self.raw_label)
        layout.addLayout(form)
        layout.addWidget(self.warning_label)

        initial = SplitSelectionByte.from_raw(int(value))
        self._set_controls(initial)

        self.random_start.toggled.connect(self._start_toggled)
        self.random_trigger.toggled.connect(self._trigger_toggled)
        self.force_select.toggled.connect(self._typed_changed)
        self.bank.valueChanged.connect(self._typed_changed)
        self.raw_edit.editingFinished.connect(self._raw_changed)
        self._refresh(update_raw=True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_controls(self, selection: SplitSelectionByte) -> None:
        self._syncing = True
        try:
            self.random_start.setChecked(selection.random_at_start)
            self.random_trigger.setChecked(selection.random_at_trigger)
            self.force_select.setChecked(selection.force_select)
            self.bank.setValue(selection.bank)
        finally:
            self._syncing = False

    @property
    def selection(self) -> SplitSelectionByte:
        return SplitSelectionByte(
            random_at_start=self.random_start.isChecked(),
            random_at_trigger=self.random_trigger.isChecked(),
            force_select=self.force_select.isChecked(),
            bank=self.bank.value(),
        )

    def _start_toggled(self, checked: bool) -> None:
        if self._syncing:
            return
        if checked and self.random_trigger.isChecked():
            self._syncing = True
            try:
                self.random_trigger.setChecked(False)
            finally:
                self._syncing = False
        self._refresh(update_raw=True)

    def _trigger_toggled(self, checked: bool) -> None:
        if self._syncing:
            return
        if checked and self.random_start.isChecked():
            self._syncing = True
            try:
                self.random_start.setChecked(False)
            finally:
                self._syncing = False
        self._refresh(update_raw=True)

    def _typed_changed(self, *_args) -> None:
        if not self._syncing:
            self._refresh(update_raw=True)

    def _raw_changed(self) -> None:
        text = self.raw_edit.text().strip()
        try:
            value = int(text, 0) if text.lower().startswith("0x") else int(text, 10)
            selection = SplitSelectionByte.from_raw(value)
        except (ValueError, TypeError):
            QMessageBox.warning(
                self,
                "Invalid raw selector byte",
                "Enter 0x00..0xFF or decimal 0..255.",
            )
            self._refresh(update_raw=True)
            return
        self._set_controls(selection)
        self._refresh(update_raw=True)

    def _refresh(self, *, update_raw: bool = False) -> None:
        selection = self.selection
        if update_raw:
            self.raw_edit.setText(f"0x{selection.raw:02X}")
        self.raw_label.setText(f"0x{selection.raw:02X}  ({selection.mode_label})")
        warnings = selection.warnings(block_count=self.block_count)
        self.warning_label.setText("\n".join(f"Warning: {item}" for item in warnings))


def _selected_split(window):
    item = window.tree.currentItem()
    if item is None:
        return None
    payload = item.data(0, Qt.ItemDataRole.UserRole)
    if not payload or len(payload) < 4:
        return None
    kind, document_index, split_id, _block_id = payload
    if kind not in ("split", "block") or int(document_index) < 0 or split_id is None:
        return None
    document = window.sessions[int(document_index)].current
    split = next(
        (candidate for candidate in document.splits if candidate.stable_id == split_id),
        None,
    )
    if split is None:
        return None
    return int(document_index), split


def _edit_split_selection(window, document_index=None, split_id=None) -> None:
    if document_index is None or split_id is None:
        selected = _selected_split(window)
        if selected is None:
            QMessageBox.information(window, "No Split selected", "Select a Split or Block first.")
            return
        document_index, split = selected
    else:
        document = window.sessions[int(document_index)].current
        split = next(
            (candidate for candidate in document.splits if candidate.stable_id == split_id),
            None,
        )
        if split is None:
            return

    dialog = SplitSelectionDialog(
        int(split.raw_select.value), block_count=len(split.blocks), parent=window
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    value = dialog.selection.raw
    if value == int(split.raw_select.value):
        return
    widget = window.tabs.currentWidget()
    if widget is None or not hasattr(widget, "snapshot"):
        return
    try:
        updated = window.sessions[int(document_index)].execute(
            SetSplitSelectionByte(split.stable_id, value)
        )
    except (ValueError, ModelInvariantError) as exc:
        QMessageBox.critical(window, "Cannot edit Split selection", str(exc))
        return

    window._apply_document(
        int(document_index),
        widget,
        updated,
        tree_selection=("split", int(document_index), split.stable_id, None),
    )
    window.statusBar().showMessage(
        f"Split selector: 0x{value:02X} ({dialog.selection.mode_label})", 5000
    )


def _decorate_tree(window) -> None:
    if window.workspace is None:
        return

    def visit(item) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload and len(payload) >= 4 and payload[0] == "split":
            document_index = int(payload[1])
            split_id = payload[2]
            if 0 <= document_index < len(window.sessions):
                document = window.sessions[document_index].current
                split = next(
                    (candidate for candidate in document.splits if candidate.stable_id == split_id),
                    None,
                )
                if split is not None:
                    selection = SplitSelectionByte.from_raw(int(split.raw_select.value))
                    item.setText(
                        1,
                        f"{selection.mode_label} · {len(split.blocks)} block(s)",
                    )
        for index in range(item.childCount()):
            visit(item.child(index))

    for index in range(window.tree.topLevelItemCount()):
        visit(window.tree.topLevelItem(index))


def install_phase12_split_header(window) -> None:
    if getattr(window, "_phase12_split_header_installed", False):
        return
    window._phase12_split_header_installed = True

    import stepnx.gui.phase11_workspace as workspace_module

    previous_show = workspace_module._show_tree_context

    def show_tree_context_with_split(target_window, point) -> None:
        item = target_window.tree.itemAt(point)
        payload = None if item is None else item.data(0, Qt.ItemDataRole.UserRole)
        if payload and len(payload) >= 4 and payload[0] == "split":
            target_window.tree.setCurrentItem(item)
            menu = QMenu(target_window.tree)
            menu.addAction(
                "Edit Split selection…",
                lambda: _edit_split_selection(target_window, int(payload[1]), payload[2]),
            )
            menu.exec(target_window.tree.viewport().mapToGlobal(point))
            return
        previous_show(target_window, point)

    workspace_module._show_tree_context = show_tree_context_with_split

    original_populate = window._populate_tree

    def populate_with_selector_summary(selected=None) -> None:
        original_populate(selected)
        _decorate_tree(window)

    window._populate_tree = populate_with_selector_summary
    _decorate_tree(window)

    action = QAction("Edit Split selection…", window)
    action.setToolTip(
        "Edit the complete NX20 Split selector byte: load-time random, 0x40 follower/fallback behavior, force-select flag, and bank."
    )
    action.triggered.connect(lambda *_args: _edit_split_selection(window))
    window.structure_menu.addAction(action)
    window.phase12_edit_split_selection_action = action
    window.phase12_edit_split_selection = lambda: _edit_split_selection(window)
