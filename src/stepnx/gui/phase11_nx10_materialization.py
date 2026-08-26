from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


def _pending_nx10_imports(window):
    workspace = getattr(window, "workspace", None)
    if workspace is None:
        return ()
    return tuple(entry for entry in workspace.documents if entry.needs_native_target)


def _confirm_in_place_materialization(window, entries) -> bool:
    names = [entry.path.name for entry in entries]
    preview = "\n".join(f"• {name}" for name in names[:20])
    if len(names) > 20:
        preview += f"\n• …and {len(names) - 20} more"

    message = QMessageBox(window)
    message.setIcon(QMessageBox.Icon.Warning)
    message.setWindowTitle("Materialize NX10 imports")
    message.setText(
        f"{len(entries)} imported NX10 file(s) need an explicit NX20 target before Save All."
    )
    message.setInformativeText(
        preview
        + "\n\nMaterializing in place replaces these legacy NX10 files with their current "
        "NX20 projections. This is intentionally never done without explicit consent."
    )
    materialize = message.addButton(
        "Materialize in place as NX20",
        QMessageBox.ButtonRole.AcceptRole,
    )
    cancel = message.addButton(QMessageBox.StandardButton.Cancel)
    message.setDefaultButton(cancel)
    message.exec()
    return message.clickedButton() is materialize


def _assign_in_place_targets(window, entries) -> None:
    workspace = window.workspace
    for entry in entries:
        workspace = workspace.replace_document(entry.with_output_path(entry.path))
    window.workspace = workspace


def install_phase11_nx10_materialization(window) -> None:
    """Turn the core NX10 publication guard into an explicit Save All workflow.

    NX10 documents are import provenance only. The core refuses to publish them
    until an NX20 target is explicit. For folder authoring, the useful default
    is an explicit one-time consent to replace the legacy .NX files in place;
    cancelling leaves every source byte untouched.
    """

    if getattr(window, "_phase11_nx10_materialization_installed", False):
        return
    window._phase11_nx10_materialization_installed = True

    action = getattr(window, "save_action", None)
    original_save_all = getattr(window, "_save_all", None)
    if action is None or not callable(original_save_all):
        return

    def save_all_with_materialization(*_args) -> None:
        pending = _pending_nx10_imports(window)
        if pending:
            if not _confirm_in_place_materialization(window, pending):
                return
            _assign_in_place_targets(window, pending)
            window.statusBar().showMessage(
                f"NX20 materialization approved for {len(pending)} imported file(s)",
                5000,
            )
        original_save_all()

    try:
        action.triggered.disconnect()
    except (RuntimeError, TypeError):
        pass
    action.triggered.connect(save_all_with_materialization)

    # Keep a direct hook for smoke tests and future non-menu callers.
    window.phase11_save_all = save_all_with_materialization
