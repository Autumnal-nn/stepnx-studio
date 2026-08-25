from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox

from stepnx.authoring.trailer import SetTrailerString, project_trailer_strings
from stepnx.core.errors import ModelInvariantError


def _edit_trailer_string(window) -> None:
    document_index = window._current_document_index()
    if document_index is None:
        return

    document = window.sessions[document_index].current
    projection = project_trailer_strings(document)
    strings = tuple(item for item in projection.strings if item.authorable)
    if not strings:
        QMessageBox.information(
            window,
            "No safe trailer strings",
            "No known trailer offset currently resolves to an editable UTF-8 string.",
        )
        return

    labels = [
        f"0x{item.metadata_id:08X} / variant {item.variant_index} / +{item.offset}: {item.text}"
        for item in strings
    ]
    selected, accepted = QInputDialog.getItem(
        window,
        "Edit trailer string",
        "Referenced field:",
        labels,
        0,
        False,
    )
    if not accepted:
        return

    target = strings[labels.index(selected)]
    text, accepted = QInputDialog.getText(
        window,
        "Edit trailer string",
        (
            f"UTF-8 text (currently {len(target.raw)} bytes; safe relocation is "
            "attempted automatically when the encoded size changes):"
        ),
        text=target.text,
    )
    if not accepted:
        return

    widget = window.tabs.currentWidget()
    if widget is None or not hasattr(widget, "snapshot"):
        return

    try:
        new_size = len(text.encode("utf-8"))
        updated = window.sessions[document_index].execute(
            SetTrailerString(target.metadata_stable_id, text)
        )
    except (UnicodeEncodeError, ModelInvariantError) as exc:
        QMessageBox.critical(window, "Cannot edit trailer string", str(exc))
        return

    window._apply_document(document_index, widget, updated)
    if new_size == len(target.raw):
        message = f"Updated trailer string in place ({new_size} UTF-8 bytes)"
    else:
        message = (
            f"Relocated trailer string safely: {len(target.raw)} → {new_size} UTF-8 bytes"
        )
    window.statusBar().showMessage(message, 6000)


def install_phase11_trailer_edit(window) -> None:
    if getattr(window, "_phase11_trailer_edit_installed", False):
        return
    window._phase11_trailer_edit_installed = True

    action = getattr(window, "edit_trailer_action", None)
    if action is None:
        return

    action.setText("Edit trailer string…")
    action.setToolTip(
        "Edit a proven UTF-8 trailer string. Length-changing edits relocate only "
        "when every affected known offset can be updated safely; ambiguous unknown "
        "pointers block the operation."
    )
    try:
        action.triggered.disconnect()
    except (RuntimeError, TypeError):
        pass
    action.triggered.connect(lambda *_args: _edit_trailer_string(window))
