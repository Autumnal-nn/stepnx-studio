from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
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

from stepnx.importers.authoring_import import (
    AuthoringImportCandidate,
    load_authoring_import_candidates,
    materialize_authoring_import,
    validate_import_filename,
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
    def __init__(
        self,
        source: Path,
        root: Path,
        candidates: tuple[AuthoringImportCandidate, ...],
        parent=None,
    ) -> None:
        super().__init__(parent)
        if not candidates:
            raise ValueError("import source produced no chart candidates")
        self._root = root.resolve()
        self._candidates = candidates
        self.setWindowTitle("Import chart")
        self.resize(640, 470)

        layout = QVBoxLayout(self)
        source_label = QLabel(f"Source: {source}", self)
        source_label.setWordWrap(True)
        layout.addWidget(source_label)

        form = QFormLayout()
        self.candidate_combo = QComboBox(self)
        for index, candidate in enumerate(candidates):
            self.candidate_combo.addItem(candidate.label, index)
        form.addRow("Chart:", self.candidate_combo)

        self.target_name = QLineEdit(self)
        form.addRow("Target filename:", self.target_name)
        layout.addLayout(form)

        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        layout.addWidget(QLabel("Import diagnostics:", self))
        self.diagnostics = QPlainTextEdit(self)
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.diagnostics, 1)

        self.validation = QLabel(self)
        self.validation.setWordWrap(True)
        layout.addWidget(self.validation)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        self.buttons.accepted.connect(self._accept_if_valid)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.candidate_combo.currentIndexChanged.connect(self._candidate_changed)
        self.target_name.textChanged.connect(self._validate_target)
        self._candidate_changed(0)

    def selected_candidate(self) -> AuthoringImportCandidate:
        index = int(self.candidate_combo.currentData())
        return self._candidates[index]

    def selected_filename(self) -> str:
        return self.target_name.text().strip()

    def _candidate_changed(self, _index: int) -> None:
        candidate = self.selected_candidate()
        self.target_name.setText(candidate.default_filename)
        stats = candidate.statistics
        self.summary.setText(
            f"Format: {candidate.source_format.upper()} · "
            f"Profile: {candidate.document.profile} · "
            f"Columns: {candidate.document.columns.value} · "
            f"Splits: {stats.get('splits', 0)} · "
            f"Blocks: {stats.get('blocks', 0)} · "
            f"Rows: {stats.get('rows', 0)}"
        )
        if candidate.diagnostics:
            prefix = (
                "ATTENTION: conversion contains approximations or unsupported details.\n\n"
                if not candidate.semantically_lossless
                else ""
            )
            self.diagnostics.setPlainText(prefix + "\n".join(candidate.diagnostics))
        else:
            self.diagnostics.setPlainText("No conversion diagnostics.")
        self._validate_target()

    def _validate_target(self) -> bool:
        try:
            name = validate_import_filename(self.selected_filename())
            target = self._root / name
            if target.exists():
                raise FileExistsError(
                    f"{name} already exists. Import never overwrites an existing NX file."
                )
        except (ValueError, FileExistsError) as exc:
            self.validation.setText(str(exc))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return False
        self.validation.setText(f"Will create: {self._root / name}")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        return True

    def _accept_if_valid(self) -> None:
        if self._validate_target():
            self.accept()


def _choose_import_source(window) -> None:
    workspace = getattr(window, "workspace", None)
    if workspace is None:
        QMessageBox.information(
            window,
            "Import chart",
            "Open a chart folder before importing a legacy or user-chart source.",
        )
        return

    has_unsaved = getattr(window, "_has_unsaved_changes", None)
    if callable(has_unsaved) and has_unsaved():
        QMessageBox.warning(
            window,
            "Import chart",
            "Save or discard the current in-memory edits before importing. "
            "The workspace is reloaded after the new NX file is created.",
        )
        return

    selected, _ = QFileDialog.getOpenFileName(
        window,
        "Import chart source",
        str(workspace.root),
        _IMPORT_FILTER,
    )
    if not selected:
        return

    source = Path(selected)
    profile = _selected_profile(window)
    try:
        candidates = load_authoring_import_candidates(source, profile=profile)
    except Exception as exc:
        QMessageBox.critical(window, "Cannot import chart", str(exc))
        return
    if not candidates:
        QMessageBox.information(
            window,
            "Import chart",
            "The selected source contains no importable charts.",
        )
        return

    dialog = AuthoringImportDialog(source, workspace.root, candidates, window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    candidate = dialog.selected_candidate()
    try:
        target = materialize_authoring_import(
            candidate,
            workspace.root,
            dialog.selected_filename(),
        )
    except Exception as exc:
        QMessageBox.critical(window, "Cannot create imported NX", str(exc))
        return

    # The import source has already been materialized atomically. Reload only
    # after the safe-write succeeds; unsaved authoring state was blocked above.
    try:
        window.load_folder(workspace.root, discard_changes=True)
    except Exception as exc:
        QMessageBox.warning(
            window,
            "Imported, but reload failed",
            f"Created {target.name}, but the workspace could not be reloaded:\n{exc}",
        )
        return
    window.statusBar().showMessage(
        f"Imported {source.name} → {target.name}",
        7000,
    )


def install_phase11_import(window) -> None:
    if getattr(window, "_phase11_import_installed", False):
        return
    window._phase11_import_installed = True

    menu = _file_menu(window)
    if menu is None:
        raise RuntimeError("File menu not found while installing Phase 11 import flow")

    action = QAction("Import chart…", window)
    action.setShortcut(QKeySequence("Ctrl+I"))
    action.setToolTip(
        "Import STF/ST2, NOT/NOT5, STX, SEE, KSF, or UCS as a new native NX20 file"
    )
    action.triggered.connect(lambda *_: _choose_import_source(window))

    actions = menu.actions()
    insert_before = actions[1] if len(actions) > 1 else None
    if insert_before is None:
        menu.addAction(action)
    else:
        menu.insertAction(insert_before, action)
    window.phase11_import_action = action
