from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
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

from stepnx.authoring.field import (
    FIELD_PRESETS,
    FieldGeometry,
    SetChartField,
    count_dropped_nonempty_cells,
    current_field,
)
from stepnx.core.errors import ModelInvariantError
from stepnx.workspace import (
    WorkspaceError,
    delete_nx_chart,
    execute_save_plan,
    plan_create_nx_chart,
    plan_duplicate_nx_chart,
)


class _FieldControls:
    def __init__(self, parent, initial: FieldGeometry) -> None:
        self.scope = QComboBox(parent)
        for label, geometry in FIELD_PRESETS:
            self.scope.addItem(label, geometry)
        self.scope.addItem("Custom", None)

        self.start = QSpinBox(parent)
        self.start.setRange(0, 63)
        self.columns = QSpinBox(parent)
        self.columns.setRange(1, 64)
        self.start.setValue(int(initial.start_column))
        self.columns.setValue(int(initial.columns))

        preset_index = self.scope.count() - 1
        for index in range(self.scope.count() - 1):
            if self.scope.itemData(index) == initial:
                preset_index = index
                break
        self.scope.setCurrentIndex(preset_index)
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self._sync_enabled()

    def _scope_changed(self, *_args) -> None:
        geometry = self.scope.currentData()
        if isinstance(geometry, FieldGeometry):
            self.start.setValue(int(geometry.start_column))
            self.columns.setValue(int(geometry.columns))
        self._sync_enabled()

    def _sync_enabled(self) -> None:
        custom = self.scope.currentData() is None
        self.start.setEnabled(custom)
        self.columns.setEnabled(custom)

    def geometry(self) -> FieldGeometry:
        geometry = self.scope.currentData()
        if isinstance(geometry, FieldGeometry):
            return geometry
        return FieldGeometry(self.start.value(), self.columns.value())

    def add_to_form(self, form: QFormLayout) -> None:
        form.addRow("Scope:", self.scope)
        form.addRow("Start Column:", self.start)
        form.addRow("Columns:", self.columns)


class FieldGeometryDialog(QDialog):
    def __init__(self, initial: FieldGeometry, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit chart scope / field")
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "The NX20 field is a window over physical panel columns. Notes are "
            "remapped by absolute panel position when Start Column or Columns changes.",
            self,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        self.controls = _FieldControls(self, initial)
        self.controls.add_to_form(form)
        layout.addLayout(form)
        self.validation = QLabel(self)
        self.validation.setWordWrap(True)
        layout.addWidget(self.validation)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_if_valid(self) -> None:
        try:
            geometry = self.controls.geometry()
            if int(geometry.columns) == 3:
                raise ValueError("Columns = 3 is reserved for NX20 Lightmap geometry")
        except ValueError as exc:
            self.validation.setText(str(exc))
            return
        self.accept()

    @property
    def geometry(self) -> FieldGeometry:
        return self.controls.geometry()


class NewNXChartDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create NX chart")
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Creates an empty NX20 chart from LM.NX header/timing context. "
            "LM.NX itself is never replaced.",
            self,
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        form = QFormLayout()
        self.filename = QLineEdit(self)
        self.filename.setPlaceholderText("CR.NX")
        form.addRow("Filename:", self.filename)
        self.controls = _FieldControls(self, FieldGeometry.single())
        self.controls.add_to_form(form)
        layout.addLayout(form)
        self.validation = QLabel(self)
        self.validation.setWordWrap(True)
        layout.addWidget(self.validation)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_if_valid(self) -> None:
        if not self.filename.text().strip():
            self.validation.setText("Enter an NX filename.")
            return
        try:
            geometry = self.controls.geometry()
            if int(geometry.columns) == 3:
                raise ValueError("Columns = 3 is reserved for NX20 Lightmap geometry")
        except ValueError as exc:
            self.validation.setText(str(exc))
            return
        self.accept()

    @property
    def geometry(self) -> FieldGeometry:
        return self.controls.geometry()


def _selected_document_index(window) -> int | None:
    item = window.tree.currentItem()
    if item is not None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload and len(payload) >= 2 and int(payload[1]) >= 0:
            return int(payload[1])
    current = getattr(window, "_current_document_index", None)
    if callable(current):
        return current()
    return None


def _block_file_membership_change(window, title: str) -> bool:
    has_unsaved = getattr(window, "_has_unsaved_changes", None)
    if callable(has_unsaved) and has_unsaved():
        QMessageBox.warning(
            window,
            title,
            "Save or discard the current in-memory chart edits first. "
            "Creating, duplicating, or deleting NX files reloads the folder.",
        )
        return True
    return False


def _reload_and_open(window, path: Path | None) -> None:
    if window.workspace is None:
        return
    root = Path(window.workspace.root)
    window.load_folder(root, discard_changes=True)
    if path is None or window.workspace is None:
        return
    wanted = path.resolve()
    index = next(
        (
            index
            for index, entry in enumerate(window.workspace.documents)
            if entry.path.resolve() == wanted
        ),
        None,
    )
    if index is not None:
        window._open_document(index)
        window._populate_tree(("document", index, None, None))


def _create_chart(window) -> None:
    if window.workspace is None or _block_file_membership_change(window, "Create NX chart"):
        return
    dialog = NewNXChartDialog(window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    try:
        plan = plan_create_nx_chart(
            window.workspace,
            dialog.filename.text(),
            dialog.geometry,
        )
        if not plan.is_ready:
            details = "\n".join(f"{item.code}: {item.message}" for item in plan.issues)
            raise WorkspaceError(details or "chart creation preflight failed")
        targets = execute_save_plan(plan)
    except (FileExistsError, OSError, ValueError, WorkspaceError) as exc:
        QMessageBox.critical(window, "Cannot create NX chart", str(exc))
        return
    _reload_and_open(window, targets[0])
    window.statusBar().showMessage(f"Created {targets[0].name}", 5000)


def _duplicate_chart(window, document_index: int) -> None:
    if window.workspace is None or _block_file_membership_change(window, "Duplicate NX chart"):
        return
    if not 0 <= document_index < len(window.workspace.documents):
        return
    entry = window.workspace.documents[document_index]
    if entry.path.name.casefold() == "lm.nx":
        QMessageBox.information(window, "LM.NX is protected", "LM.NX cannot be duplicated.")
        return

    dialog = QDialog(window)
    dialog.setWindowTitle("Duplicate NX chart")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(f"Source: {entry.path.name}", dialog))
    form = QFormLayout()
    filename = QLineEdit(dialog)
    filename.setText(f"{entry.path.stem}_COPY.NX")
    form.addRow("New filename:", filename)
    layout.addLayout(form)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        dialog,
    )
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Duplicate")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    try:
        plan = plan_duplicate_nx_chart(window.workspace, entry.path, filename.text())
        targets = execute_save_plan(plan)
    except (FileExistsError, OSError, ValueError, WorkspaceError) as exc:
        QMessageBox.critical(window, "Cannot duplicate NX chart", str(exc))
        return
    _reload_and_open(window, targets[0])
    window.statusBar().showMessage(
        f"Duplicated {entry.path.name} → {targets[0].name}", 5000
    )


def _delete_chart(window, document_index: int) -> None:
    if window.workspace is None or _block_file_membership_change(window, "Delete NX chart"):
        return
    if not 0 <= document_index < len(window.workspace.documents):
        return
    entry = window.workspace.documents[document_index]
    if entry.path.name.casefold() == "lm.nx":
        QMessageBox.information(window, "LM.NX is protected", "LM.NX cannot be deleted.")
        return
    answer = QMessageBox.warning(
        window,
        "Delete NX chart",
        f"Permanently delete {entry.path.name} from this folder?\n\n"
        "This filesystem operation is not part of the chart Undo stack.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return
    try:
        deleted = delete_nx_chart(window.workspace, entry.path)
    except (OSError, WorkspaceError) as exc:
        QMessageBox.critical(window, "Cannot delete NX chart", str(exc))
        return
    _reload_and_open(window, None)
    window.statusBar().showMessage(f"Deleted {deleted.name}", 5000)


def _edit_field(window, document_index: int | None = None) -> None:
    if window.workspace is None:
        return
    if document_index is None:
        document_index = _selected_document_index(window)
    if document_index is None or not 0 <= document_index < len(window.workspace.documents):
        return

    entry = window.workspace.documents[document_index]
    if entry.path.name.casefold() == "lm.nx" or entry.document.effective_lightmap:
        QMessageBox.information(
            window,
            "Lightmap field is fixed",
            "LM.NX uses the dedicated 3-channel Lightmap row layout and is not converted by the chart field tool.",
        )
        return

    # A tree context action may target a document that has not yet been opened,
    # so create/select its CommandStack before reading the editable snapshot.
    window._open_document(document_index)
    document = window.sessions[document_index].current

    dialog = FieldGeometryDialog(current_field(document), window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    geometry = dialog.geometry
    if geometry == current_field(document):
        return

    try:
        dropped = count_dropped_nonempty_cells(document, geometry)
    except (ModelInvariantError, ValueError) as exc:
        QMessageBox.critical(window, "Cannot change chart field", str(exc))
        return
    allow_note_loss = False
    if dropped:
        answer = QMessageBox.warning(
            window,
            "Field change discards notes",
            f"The new field excludes {dropped} non-empty note cell(s).\n\n"
            "Discard those cells and continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        allow_note_loss = True

    widget = window.tabs.currentWidget()
    try:
        updated = window.sessions[document_index].execute(
            SetChartField(geometry, allow_note_loss=allow_note_loss)
        )
    except (ModelInvariantError, ValueError) as exc:
        QMessageBox.critical(window, "Cannot change chart field", str(exc))
        return
    window._apply_document(
        document_index,
        widget,
        updated,
        tree_selection=("document", document_index, None, None),
    )
    window.statusBar().showMessage(
        f"Field: Start Column {geometry.start_column}, Columns {geometry.columns}",
        5000,
    )


def _show_tree_context(window, point) -> None:
    item = window.tree.itemAt(point)
    if item is not None:
        window.tree.setCurrentItem(item)
    payload = None if item is None else item.data(0, Qt.ItemDataRole.UserRole)
    kind = payload[0] if payload else None
    document_index = int(payload[1]) if payload and len(payload) >= 2 else -1

    menu = QMenu(window.tree)
    if kind == "root":
        menu.addAction("Create NX…", lambda: _create_chart(window))
    elif kind == "document" and document_index >= 0:
        entry = window.workspace.documents[document_index] if window.workspace else None
        menu.addAction("Open", lambda: window._open_document(document_index))
        menu.addAction("Edit scope / field…", lambda: _edit_field(window, document_index))
        menu.addSeparator()
        duplicate = menu.addAction(
            "Duplicate NX…", lambda: _duplicate_chart(window, document_index)
        )
        delete = menu.addAction(
            "Delete NX…", lambda: _delete_chart(window, document_index)
        )
        protected = bool(entry and entry.path.name.casefold() == "lm.nx")
        duplicate.setEnabled(not protected)
        delete.setEnabled(not protected)
    elif item is None and window.workspace is not None:
        # Empty tree space is a folder-level target, equivalent to the root.
        menu.addAction("Create NX…", lambda: _create_chart(window))
    if menu.actions():
        menu.exec(window.tree.viewport().mapToGlobal(point))


def install_phase11_workspace_tools(window) -> None:
    if getattr(window, "_phase11_workspace_tools_installed", False):
        return
    window._phase11_workspace_tools_installed = True

    window.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    window.tree.customContextMenuRequested.connect(
        lambda point: _show_tree_context(window, point)
    )

    edit_field_action = QAction("Edit chart scope / field…", window)
    edit_field_action.setToolTip(
        "Edit NX20 Start Column and Columns while remapping notes by physical panel"
    )
    edit_field_action.triggered.connect(lambda *_: _edit_field(window))
    window.structure_menu.addSeparator()
    window.structure_menu.addAction(edit_field_action)
    window.phase11_edit_field_action = edit_field_action

    # These hooks keep the file actions directly testable without reconstructing
    # a context-menu mouse interaction.
    window.phase11_create_nx = lambda: _create_chart(window)
    window.phase11_duplicate_nx = lambda index: _duplicate_chart(window, index)
    window.phase11_delete_nx = lambda index: _delete_chart(window, index)
