from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from stepnx.importers.authoring_import import (
    AuthoringImportCandidate,
    load_authoring_import_candidates,
    materialize_authoring_import_batch,
    prepare_authoring_import_batch,
    validate_authoring_import_batch,
)


_IMPORT_FILTER = (
    "Pump chart sources (*.stf *.st2 *.not *.not5 *.stx *.see *.ksf *.ucs);;"
    "StepEdit SEE (*.see);;"
    "StepEdit STF/ST2 (*.stf *.st2);;"
    "StepEdit NOT/NOT5 (*.not *.not5);;"
    "StepEdit STX (*.stx);;"
    "KSF (*.ksf);;"
    "UCS (*.ucs);;"
    "All files (*)"
)


def _selected_profile(window) -> str:
    selector = getattr(window, "_selected_profile", None)
    if callable(selector):
        try:
            return str(selector())
        except Exception:
            pass
    for name, action in getattr(window, "profile_actions", {}).items():
        if action.isChecked():
            return str(name)
    return "nxa-native"


def _file_menu(window) -> QMenu | None:
    return next(
        (
            menu
            for menu in window.menuBar().findChildren(QMenu)
            if menu.title().replace("&", "").strip().casefold() == "file"
        ),
        None,
    )


class AuthoringImportDialog(QDialog):
    """Read-only review of the complete set that will be imported."""

    def __init__(
        self,
        source: Path,
        root: Path,
        candidates: tuple[AuthoringImportCandidate, ...],
        parent=None,
    ) -> None:
        super().__init__(parent)
        if not candidates:
            raise ValueError("import source produced no non-empty chart candidates")
        self._root = root.resolve()
        self._candidates = candidates
        self.setWindowTitle("Import charts")
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        source_label = QLabel(f"Source: {source}", self)
        source_label.setWordWrap(True)
        layout.addWidget(source_label)
        root_label = QLabel(f"Destination: {self._root}", self)
        root_label.setWordWrap(True)
        layout.addWidget(root_label)

        self.table = QTableWidget(len(candidates), 4, self)
        self.table.setHorizontalHeaderLabels(["Chart", "Target", "Columns", "Rows"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        for row, candidate in enumerate(candidates):
            stats = candidate.statistics
            values = (
                candidate.label,
                candidate.default_filename,
                str(candidate.document.columns.value),
                str(stats.get("rows", 0)),
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        layout.addWidget(self.table, 1)

        layout.addWidget(QLabel("Import diagnostics:", self))
        self.diagnostics = QPlainTextEdit(self)
        self.diagnostics.setReadOnly(True)
        chunks = []
        for candidate in candidates:
            if candidate.diagnostics:
                chunks.append(
                    f"[{candidate.default_filename}]\n" + "\n".join(candidate.diagnostics)
                )
        self.diagnostics.setPlainText("\n\n".join(chunks) if chunks else "No conversion diagnostics.")
        layout.addWidget(self.diagnostics, 1)

        self.validation = QLabel(self)
        self.validation.setWordWrap(True)
        layout.addWidget(self.validation)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import all")
        self.buttons.accepted.connect(self._accept_if_valid)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._validate_targets()

    @property
    def candidates(self) -> tuple[AuthoringImportCandidate, ...]:
        return self._candidates

    def _validate_targets(self) -> bool:
        try:
            targets = validate_authoring_import_batch(self._candidates, self._root)
        except (ValueError, FileExistsError) as exc:
            self.validation.setText(str(exc))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return False
        self.validation.setText(f"Will create {len(targets)} NX file(s). Existing files are never overwritten.")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        return True

    def _accept_if_valid(self) -> None:
        if self._validate_targets():
            self.accept()


def _close_workspace(window) -> bool:
    if getattr(window, "workspace", None) is None:
        return True
    confirm = getattr(window, "_confirm_discard", None)
    if callable(confirm) and not confirm():
        return False

    transport = getattr(window, "audio_transport", None)
    if transport is not None:
        try:
            transport.load(None)
        except Exception:
            pass

    window.workspace = None
    for name in (
        "sessions",
        "baselines",
        "widget_documents",
        "preview_snapshots",
        "gesture_keys",
    ):
        collection = getattr(window, name, None)
        if hasattr(collection, "clear"):
            collection.clear()
    for name in ("tabs", "tree", "diagnostics", "routes"):
        widget = getattr(window, name, None)
        if hasattr(widget, "clear"):
            widget.clear()
    inspector = getattr(window, "inspector", None)
    if inspector is not None and hasattr(inspector, "setRowCount"):
        inspector.setRowCount(0)
    if hasattr(window, "waveform"):
        window.waveform = None
    if hasattr(window, "metronome_clock"):
        window.metronome_clock = None
    if hasattr(window, "note_metronome_clock"):
        window.note_metronome_clock = None

    for name in ("_refresh_edit_actions", "_refresh_structure_actions"):
        callback = getattr(window, name, None)
        if callable(callback):
            try:
                callback()
            except TypeError:
                pass
    window.statusBar().showMessage("Closed chart folder", 5000)
    return True


def _choose_import_source(window) -> None:
    has_unsaved = getattr(window, "_has_unsaved_changes", None)
    if callable(has_unsaved) and has_unsaved():
        QMessageBox.warning(
            window,
            "Import charts",
            "Save or discard the current in-memory edits before importing. "
            "The destination folder is opened after a successful import.",
        )
        return

    workspace = getattr(window, "workspace", None)
    initial = Path(workspace.root) if workspace is not None else Path.home()
    selected, _ = QFileDialog.getOpenFileName(
        window,
        "Import chart source",
        str(initial),
        _IMPORT_FILTER,
    )
    if not selected:
        return

    source = Path(selected)
    profile = _selected_profile(window)
    try:
        candidates = prepare_authoring_import_batch(
            load_authoring_import_candidates(source, profile=profile)
        )
    except Exception as exc:
        QMessageBox.critical(window, "Cannot import charts", str(exc))
        return
    if not candidates:
        QMessageBox.information(
            window,
            "Import charts",
            "The selected source contains no non-empty importable charts.",
        )
        return

    default_root = Path(workspace.root) if workspace is not None else source.parent
    chosen_root = QFileDialog.getExistingDirectory(
        window,
        "Choose import destination folder",
        str(default_root),
    )
    if not chosen_root:
        return
    root = Path(chosen_root)

    dialog = AuthoringImportDialog(source, root, candidates, window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    try:
        targets = materialize_authoring_import_batch(candidates, root)
    except Exception as exc:
        QMessageBox.critical(window, "Cannot create imported NX files", str(exc))
        return

    window.load_folder(root, discard_changes=True)
    refreshed = getattr(window, "workspace", None)
    if refreshed is None or Path(refreshed.root).resolve() != root.resolve():
        QMessageBox.warning(
            window,
            "Imported, but workspace did not open",
            f"Created {len(targets)} NX files in {root}, but the folder could not be opened.",
        )
        return

    first_chart = next((path for path in targets if path.name.casefold() != "lm.nx"), targets[0])
    imported_index = next(
        (
            index
            for index, entry in enumerate(refreshed.documents)
            if entry.path.resolve() == first_chart.resolve()
        ),
        None,
    )
    opener = getattr(window, "_open_document", None)
    if imported_index is not None and callable(opener):
        opener(imported_index)
    window.statusBar().showMessage(
        f"Imported {source.name} → {len(targets)} NX file(s)",
        7000,
    )


def install_phase11_import(window) -> None:
    if getattr(window, "_phase11_import_installed", False):
        return
    window._phase11_import_installed = True

    menu = _file_menu(window)
    if menu is None:
        raise RuntimeError("File menu not found while installing Phase 11 import flow")

    close_action = QAction("Close Folder", window)
    close_action.setToolTip("Close the current workspace without exiting StepNX Studio")
    close_action.triggered.connect(lambda *_: _close_workspace(window))

    import_action = QAction("Import charts…", window)
    import_action.setShortcut(QKeySequence("Ctrl+I"))
    import_action.setToolTip(
        "Import all non-empty STF/ST2, NOT/NOT5, STX, SEE, KSF, or UCS charts into a folder"
    )
    import_action.triggered.connect(lambda *_: _choose_import_source(window))

    actions = menu.actions()
    insert_before = actions[1] if len(actions) > 1 else None
    if insert_before is None:
        menu.addAction(close_action)
        menu.addAction(import_action)
    else:
        menu.insertAction(insert_before, close_action)
        menu.insertAction(insert_before, import_action)

    menu.aboutToShow.connect(
        lambda: close_action.setEnabled(getattr(window, "workspace", None) is not None)
    )
    window.phase11_close_folder_action = close_action
    window.phase11_import_action = import_action
