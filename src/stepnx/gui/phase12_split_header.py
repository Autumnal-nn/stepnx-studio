from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
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

        layout = QVBoxLayout(self)
        explanation = QLabel(
            "NX20 stores Split selection in one byte. The upper three bits are "
            "independent selector flags; the lower five bits are the random bank. "
            "Unusual combinations are preserved and warned about, not normalized.",
            self,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        self.random_start = QCheckBox("0x80  Random at Split start", self)
        self.random_trigger = QCheckBox("0x40  Random on selection trigger", self)
        self.force_select = QCheckBox("0x20  Force/select behavior", self)
        self.bank = QSpinBox(self)
        self.bank.setRange(0, 31)
        self.bank.setToolTip(
            "0 = independent/unbanked random event. Non-zero values share the "
            "random event with matching banks when random selection is active."
        )
        self.raw_label = QLabel(self)
        self.warning_label = QLabel(self)
        self.warning_label.setWordWrap(True)

        form.addRow("Random at start:", self.random_start)
        form.addRow("Random at trigger:", self.random_trigger)
        form.addRow("Force select:", self.force_select)
        form.addRow("Random bank (0..31):", self.bank)
        form.addRow("Encoded byte:", self.raw_label)
        layout.addLayout(form)
        layout.addWidget(self.warning_label)

        initial = SplitSelectionByte.from_raw(int(value))
        self.random_start.setChecked(initial.random_at_start)
        self.random_trigger.setChecked(initial.random_at_trigger)
        self.force_select.setChecked(initial.force_select)
        self.bank.setValue(initial.bank)

        self.random_start.toggled.connect(self._refresh)
        self.random_trigger.toggled.connect(self._refresh)
        self.force_select.toggled.connect(self._refresh)
        self.bank.valueChanged.connect(self._refresh)
        self._refresh()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selection(self) -> SplitSelectionByte:
        return SplitSelectionByte(
            random_at_start=self.random_start.isChecked(),
            random_at_trigger=self.random_trigger.isChecked(),
            force_select=self.force_select.isChecked(),
            bank=self.bank.value(),
        )

    def _refresh(self, *_args) -> None:
        selection = self.selection
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

    # phase11_workspace connects a lambda that resolves its module-global
    # _show_tree_context at click time, so wrapping that function extends the
    # existing context menu instead of creating two menus for one right-click.
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
        "Edit the complete NX20 Split selector byte: random flags, force-select flag, and bank."
    )
    action.triggered.connect(lambda *_args: _edit_split_selection(window))
    window.structure_menu.addAction(action)
    window.phase12_edit_split_selection_action = action
    window.phase12_edit_split_selection = lambda: _edit_split_selection(window)
