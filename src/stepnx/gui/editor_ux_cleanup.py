from __future__ import annotations

from types import MethodType

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu

from stepnx.gui.selection_lightmap_workflow import GridClipboard, VisibleRowOrder


def _active_timeline(window):
    widget = window.tabs.currentWidget() if hasattr(window, "tabs") else None
    if widget is None or not hasattr(widget, "snapshot") or not hasattr(widget, "selection"):
        return None
    return widget


def _clipboard_compatible(widget, clipboard) -> bool:
    if widget is None or clipboard is None:
        return False
    if not isinstance(clipboard, GridClipboard):
        return False
    expected = "lightmap" if widget.snapshot.effective_lightmap else "notes"
    return clipboard.kind == expected


def selection_summary(widget) -> str:
    """Compact status text that distinguishes rectangles from sparse selections."""

    selection = getattr(widget, "selection", None)
    if selection is None or not selection.targets:
        return "Ready"
    count = len(selection.targets)
    if count == 1:
        return "1 light cell selected" if widget.snapshot.effective_lightmap else "1 cell selected"

    rows = {int(target.row_id) for target in selection.targets}
    lanes = {int(target.lane) for target in selection.targets}
    rectangular = count == len(rows) * len(lanes)
    noun = "light cells" if widget.snapshot.effective_lightmap else "cells"
    row_label = f"{len(rows)} {'row' if len(rows) == 1 else 'rows'}"
    lane_label = f"{len(lanes)} {'lane' if len(lanes) == 1 else 'lanes'}"
    if rectangular:
        detail = f"{row_label} × {lane_label}"
    else:
        detail = f"{row_label} · {lane_label}"

    block_ids = set()
    try:
        order = VisibleRowOrder(widget)
        for row_id in rows:
            entry, _local, _ordinal = order.locate(row_id)
            block_ids.add(int(entry.segment.block.stable_id))
    except Exception:
        block_ids.clear()
    crossing = f" · across {len(block_ids)} Blocks" if len(block_ids) > 1 else ""
    return f"{count} {noun} selected · {detail}{crossing}"


def selection_transform_state(widget) -> tuple[bool, bool]:
    """Return (rectangular-transform, mirror) applicability without reading cells."""

    if widget is None or widget.snapshot.effective_lightmap or not widget.selection.targets:
        return False, False
    try:
        order = VisibleRowOrder(widget)
        positions = {
            int(row_id): order.locate(int(row_id))[2]
            for row_id in {target.row_id for target in widget.selection.targets}
        }
    except Exception:
        return False, False

    ordinals = sorted(set(positions.values()))
    lanes = sorted({int(target.lane) for target in widget.selection.targets})
    rectangle = (
        bool(ordinals)
        and bool(lanes)
        and ordinals == list(range(ordinals[0], ordinals[-1] + 1))
        and lanes == list(range(lanes[0], lanes[-1] + 1))
        and len(widget.selection.targets) == len(ordinals) * len(lanes)
    )
    if not rectangle:
        return False, False

    columns = int(widget.snapshot.columns)
    lane_tuple = tuple(lanes)
    mirror = (
        (len(lanes) == 5 and (
            (columns == 5 and lane_tuple == tuple(range(5)))
            or (columns == 10 and lane_tuple in (tuple(range(5)), tuple(range(5, 10))))
        ))
        or (len(lanes) == 6 and (
            (columns == 6 and lane_tuple == tuple(range(6)))
            or (columns == 10 and lane_tuple == tuple(range(2, 8)))
        ))
        or (columns == 10 and lane_tuple == tuple(range(10)))
    )
    return True, mirror


def _selected_document(window):
    if window.workspace is None:
        return None
    item = window.tree.currentItem() if hasattr(window, "tree") else None
    if item is not None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload and len(payload) >= 2 and int(payload[1]) >= 0:
            index = int(payload[1])
            if 0 <= index < len(window.workspace.documents):
                return window.workspace.documents[index].document
    current = getattr(window, "_current_document_index", None)
    index = current() if callable(current) else None
    if index is None or not 0 <= int(index) < len(window.workspace.documents):
        return None
    return window.workspace.documents[int(index)].document


def inspector_context_exists(document, context) -> bool:
    """Whether an Inspector scope still exists after a structural edit."""

    if context is None:
        return False
    kind, _document_index, split_id, block_id = context
    if kind in {"document", "header"}:
        return True
    split = next((item for item in document.splits if item.stable_id == split_id), None)
    if split is None:
        return False
    if kind == "split":
        return True
    if kind == "block":
        return any(item.stable_id == block_id for item in split.blocks)
    return False


def _metadata_signature(entries) -> tuple[tuple[int, str], ...]:
    return tuple((int(item.meta_id.value), item.value.hex) for item in entries)


def inspector_context_signature(document, context):
    """Cheap signature of exactly the model data rendered by Inspector."""

    if context is None:
        return None
    kind, _document_index, split_id, block_id = context
    if kind in {"document", "header"}:
        return (kind, _metadata_signature(document.header_metadata), bytes(document.envelope.raw))
    split = next((item for item in document.splits if item.stable_id == split_id), None)
    if split is None:
        return None
    if kind == "split":
        return (kind, split.raw_select.hex, split.raw_brain.hex, _metadata_signature(split.metadata))
    if kind == "block":
        block = next((item for item in split.blocks if item.stable_id == block_id), None)
        if block is None:
            return None
        return (
            kind,
            block.start_time.hex,
            block.bpm.hex,
            block.scroll.hex,
            block.offset_or_delay.hex,
            block.speed_or_freeze.hex,
            block.beat_split.hex,
            block.beat_measure.hex,
            block.smooth_speed.hex,
            block.raw_flag.hex,
            _metadata_signature(block.divisions),
        )
    return None


def _add_action_group(menu: QMenu, actions) -> None:
    available = [action for action in actions if action is not None]
    if not available:
        return
    if menu.actions():
        menu.addSeparator()
    for action in available:
        menu.addAction(action)


def _structure_actions(window, kind: str):
    if kind == "split":
        return (
            (
                getattr(window, "insert_split_action", None),
                getattr(window, "remove_split_action", None),
                getattr(window, "move_split_up_action", None),
                getattr(window, "move_split_down_action", None),
            ),
            (getattr(window, "phase12_edit_split_selection_action", None),),
        )
    if kind == "block":
        return (
            (
                getattr(window, "insert_block_action", None),
                getattr(window, "remove_block_action", None),
                getattr(window, "move_block_up_action", None),
                getattr(window, "move_block_down_action", None),
            ),
            (
                getattr(window, "edit_timing_action", None),
                getattr(window, "phase12_edit_split_selection_action", None),
                getattr(window, "phase11_division_metadata_action", None),
            ),
        )
    if kind == "header":
        return ((getattr(window, "edit_metadata_action", None),),)
    return ()


def _install_tree_context_cleanup(window) -> None:
    import stepnx.gui.phase11_workspace as workspace_module

    previous = workspace_module._show_tree_context

    def show_tree_context(target_window, point) -> None:
        item = target_window.tree.itemAt(point)
        payload = None if item is None else item.data(0, Qt.ItemDataRole.UserRole)
        kind = None if not payload else str(payload[0])
        groups = _structure_actions(target_window, kind)
        if not groups:
            previous(target_window, point)
            return
        target_window.tree.setCurrentItem(item)
        refresh = getattr(target_window, "_refresh_edit_actions", None)
        if callable(refresh):
            refresh()
        structure_refresh = getattr(target_window, "_refresh_structure_actions", None)
        if callable(structure_refresh):
            structure_refresh()
        menu = QMenu(target_window.tree)
        for group in groups:
            _add_action_group(menu, group)
        if menu.actions():
            menu.exec(target_window.tree.viewport().mapToGlobal(point))

    workspace_module._show_tree_context = show_tree_context
    window._stepnx_tree_context_handler = show_tree_context


def _install_edit_action_state(window) -> None:
    original = window._refresh_edit_actions

    def refresh_edit_actions(self, *args) -> None:
        original(*args)
        widget = _active_timeline(self)
        lightmap = bool(widget is not None and widget.snapshot.effective_lightmap)
        has_selection = bool(widget is not None and widget.selection.targets)
        tool_text = self.tool_combo.currentText().strip().casefold() if hasattr(self, "tool_combo") else ""

        apply_action = getattr(self, "apply_selection_action", None)
        if apply_action is not None:
            apply_action.setEnabled(
                has_selection and (not lightmap or tool_text == "toggle") and tool_text != "select"
            )

        rectangle, mirror = selection_transform_state(widget)
        horizontal = getattr(self, "flip_horizontal_selection_action", None)
        vertical = getattr(self, "flip_vertical_selection_action", None)
        mirror_action = getattr(self, "mirror_selection_action", None)
        if horizontal is not None:
            horizontal.setEnabled(rectangle)
        if vertical is not None:
            vertical.setEnabled(rectangle)
        if mirror_action is not None:
            mirror_action.setEnabled(mirror)

        replace_action = getattr(self, "replace_selection_action", None)
        if replace_action is not None and lightmap:
            replace_action.setEnabled(False)
        apply_flags = getattr(self, "apply_flags", None)
        if apply_flags is not None and lightmap:
            apply_flags.setEnabled(False)

        paste = getattr(self, "paste_selection_action", None)
        if paste is not None:
            paste.setEnabled(
                has_selection
                and widget is not None
                and widget.selection.anchor is not None
                and _clipboard_compatible(widget, getattr(self, "note_clipboard", None))
            )

        for name in (
            "tool_value",
            "function_combo",
            "visibility_combo",
            "phase10_brain_code",
            "phase10_special_button",
            "phase10_advanced_raw_button",
        ):
            control = getattr(self, name, None)
            if control is not None:
                control.setEnabled(not lightmap)

        split_selection = getattr(self, "phase12_edit_split_selection_action", None)
        if split_selection is not None:
            split_selection.setEnabled(self._structure_selection() is not None)

        edit_field = getattr(self, "phase11_edit_field_action", None)
        if edit_field is not None:
            selected_document = _selected_document(self)
            edit_field.setEnabled(
                selected_document is not None and not selected_document.effective_lightmap
            )

    window._refresh_edit_actions = MethodType(refresh_edit_actions, window)
    window._refresh_edit_actions()


def _install_selection_feedback(window) -> None:
    previous = getattr(window, "_phase10_update_selection_status", None)

    def update_selection_status(widget) -> None:
        selection = getattr(widget, "selection", None)
        if selection is None or not selection.targets:
            if callable(previous):
                previous(widget)
            return
        if len(selection.targets) == 1 and not widget.snapshot.effective_lightmap:
            if callable(previous):
                previous(widget)
            return
        label = getattr(window, "phase10_selection_status", None)
        if label is not None:
            label.setText(selection_summary(widget))

    window._phase10_update_selection_status = update_selection_status
    widget = _active_timeline(window)
    if widget is not None:
        update_selection_status(widget)


def _install_inspector_state(window) -> None:
    original_inspect = window._inspect
    original_apply = window._apply_document
    window._stepnx_inspector_context = None

    def inspect(self, kind, document_index, split_id, block_id) -> None:
        self._stepnx_inspector_context = (str(kind), int(document_index), split_id, block_id)
        original_inspect(kind, document_index, split_id, block_id)

    def apply_document(self, document_index, widget, document, *, tree_selection=None) -> None:
        context = getattr(self, "_stepnx_inspector_context", None)
        before = None
        if context is not None and int(context[1]) == int(document_index) and self.workspace is not None:
            old_document = self.workspace.documents[int(document_index)].document
            before = inspector_context_signature(old_document, context)
        original_apply(document_index, widget, document, tree_selection=tree_selection)
        if context is None or int(context[1]) != int(document_index):
            return
        current = self.sessions[int(document_index)].current
        if not inspector_context_exists(current, context):
            self._stepnx_inspector_context = None
            self.inspector.clearContents()
            self.inspector.setRowCount(0)
            return
        after = inspector_context_signature(current, context)
        if before == after:
            return
        selected_side = self.side_tabs.currentWidget()
        kind, doc_index, split_id, block_id = context
        original_inspect(kind, doc_index, split_id, block_id)
        if selected_side is not self.inspector:
            self.side_tabs.setCurrentWidget(selected_side)

    window._inspect = MethodType(inspect, window)
    window._apply_document = MethodType(apply_document, window)


def install_editor_ux_cleanup(window) -> None:
    if getattr(window, "_stepnx_editor_ux_cleanup_installed", False):
        return
    window._stepnx_editor_ux_cleanup_installed = True
    _install_tree_context_cleanup(window)
    _install_edit_action_state(window)
    _install_selection_feedback(window)
    _install_inspector_state(window)
