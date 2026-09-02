from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut

from stepnx.authoring.selection import CellSelection, CellTarget
from stepnx.core.model import CompactRows, OverlayRows
from stepnx.gui.phase11_fast_notes import _row_index


_TOOL_KEY_LABELS = {
    Qt.Key.Key_1: "Toggle",
    Qt.Key.Key_2: "Select",
    Qt.Key.Key_3: "Roll",
    Qt.Key.Key_4: "Tap",
    Qt.Key.Key_5: "Hold head",
    Qt.Key.Key_6: "Hold body",
    Qt.Key.Key_7: "Hold tail",
    Qt.Key.Key_8: "Item",
    Qt.Key.Key_9: "Division",
    Qt.Key.Key_0: "Erase",
}


@dataclass(frozen=True, slots=True)
class KeyboardCursor:
    segment_index: int
    row_index: int
    lane: int


def _row_id_at(rows, index: int) -> int:
    if isinstance(rows, OverlayRows):
        for replacement_index, row in rows.replacements:
            if replacement_index == index:
                return int(row.stable_id)
            if replacement_index > index:
                break
        return int(rows.base._row_ids[index])
    if isinstance(rows, CompactRows):
        return int(rows._row_ids[index])
    return int(rows[index].stable_id)


def _cursor_for_anchor(widget) -> KeyboardCursor | None:
    anchor = widget.selection.anchor
    if anchor is None:
        return None
    for segment_index, segment in enumerate(widget._layout.segments):
        row_index = _row_index(segment.block.rows, int(anchor.row_id))
        if row_index is not None:
            return KeyboardCursor(
                segment_index,
                int(row_index),
                max(0, min(int(anchor.lane), int(widget.snapshot.columns) - 1)),
            )
    return None


def _default_cursor(widget) -> KeyboardCursor | None:
    segments = widget._layout.segments
    if not segments or int(widget.snapshot.columns) <= 0:
        return None
    content_y = widget.verticalScrollBar().value() + widget.viewport().height() * 0.07
    hit = widget._layout.row_at_y(content_y)
    if hit is not None:
        segment, row_index = hit
        try:
            segment_index = segments.index(segment)
        except ValueError:
            segment_index = 0
        if segment.block.row_count:
            return KeyboardCursor(segment_index, int(row_index), 0)
    for segment_index, segment in enumerate(segments):
        if segment.block.row_count:
            return KeyboardCursor(segment_index, 0, 0)
    return None


def _cursor(widget) -> KeyboardCursor | None:
    return _cursor_for_anchor(widget) or _default_cursor(widget)


def _step_vertical(widget, cursor: KeyboardCursor, delta: int) -> KeyboardCursor:
    segments = widget._layout.segments
    segment_index = cursor.segment_index
    row_index = cursor.row_index + delta
    if delta < 0:
        while row_index < 0 and segment_index > 0:
            segment_index -= 1
            row_index = int(segments[segment_index].block.row_count) - 1
        row_index = max(0, row_index)
    else:
        while (
            segment_index < len(segments)
            and row_index >= int(segments[segment_index].block.row_count)
        ):
            if segment_index + 1 >= len(segments):
                row_index = max(0, int(segments[segment_index].block.row_count) - 1)
                break
            segment_index += 1
            row_index = 0
    return KeyboardCursor(segment_index, row_index, cursor.lane)


def _jump_segment(widget, cursor: KeyboardCursor, delta: int) -> KeyboardCursor:
    segments = widget._layout.segments
    wanted = max(0, min(cursor.segment_index + delta, len(segments) - 1))
    while wanted != cursor.segment_index and not segments[wanted].block.row_count:
        wanted += 1 if delta > 0 else -1
        if not 0 <= wanted < len(segments):
            return cursor
    row_count = int(segments[wanted].block.row_count)
    if row_count <= 0:
        return cursor
    row_index = 0 if delta > 0 else row_count - 1
    return KeyboardCursor(wanted, row_index, cursor.lane)


def _move_cursor(widget, cursor: KeyboardCursor, key: int, modifiers) -> KeyboardCursor:
    columns = int(widget.snapshot.columns)
    control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
    if key == Qt.Key.Key_Left:
        return KeyboardCursor(cursor.segment_index, cursor.row_index, max(0, cursor.lane - 1))
    if key == Qt.Key.Key_Right:
        return KeyboardCursor(
            cursor.segment_index,
            cursor.row_index,
            min(columns - 1, cursor.lane + 1),
        )
    if key == Qt.Key.Key_Up:
        return _jump_segment(widget, cursor, -1) if control else _step_vertical(widget, cursor, -1)
    if key == Qt.Key.Key_Down:
        return _jump_segment(widget, cursor, 1) if control else _step_vertical(widget, cursor, 1)
    if key == Qt.Key.Key_Home:
        if control:
            return KeyboardCursor(cursor.segment_index, 0, cursor.lane)
        return KeyboardCursor(cursor.segment_index, cursor.row_index, 0)
    if key == Qt.Key.Key_End:
        if control:
            row_count = int(widget._layout.segments[cursor.segment_index].block.row_count)
            return KeyboardCursor(cursor.segment_index, max(0, row_count - 1), cursor.lane)
        return KeyboardCursor(cursor.segment_index, cursor.row_index, max(0, columns - 1))
    return cursor


def _selection_to_cursor(widget, cursor: KeyboardCursor, *, extend: bool) -> CellSelection:
    segment = widget._layout.segments[cursor.segment_index]
    row_id = _row_id_at(segment.block.rows, cursor.row_index)
    target = CellTarget(row_id, cursor.lane)
    selection = widget.selection
    if not extend or selection.anchor is None:
        return selection.replace(target)

    anchor = selection.anchor
    anchor_index = _row_index(segment.block.rows, int(anchor.row_id))
    if anchor_index is None:
        return selection.replace(target)

    row_start, row_end = sorted((int(anchor_index), cursor.row_index))
    lane_start, lane_end = sorted((int(anchor.lane), cursor.lane))
    targets = frozenset(
        CellTarget(_row_id_at(segment.block.rows, row_index), lane)
        for row_index in range(row_start, row_end + 1)
        for lane in range(lane_start, lane_end + 1)
    )
    return CellSelection(targets, anchor)


def _ensure_cursor_visible(widget, cursor: KeyboardCursor) -> None:
    segment = widget._layout.segments[cursor.segment_index]
    row_y = float(segment.y_for_row(cursor.row_index))
    vertical = widget.verticalScrollBar()
    top = float(vertical.value())
    height = float(widget.viewport().height())
    margin = max(float(widget._geometry.lane_width) * 0.6, 12.0)
    if row_y < top + margin:
        vertical.setValue(round(max(0.0, row_y - margin)))
    elif row_y > top + height - margin:
        vertical.setValue(round(row_y - height + margin))

    horizontal = widget.horizontalScrollBar()
    lane_left = float(widget._geometry.ruler_width + cursor.lane * widget._geometry.lane_width)
    lane_right = lane_left + float(widget._geometry.lane_width)
    left = float(horizontal.value())
    width = float(widget.viewport().width())
    if lane_left < left:
        horizontal.setValue(round(lane_left))
    elif lane_right > left + width:
        horizontal.setValue(round(lane_right - width))


def _trigger(action) -> bool:
    if action is None or not action.isEnabled():
        return False
    action.trigger()
    return True


def _select_tool(window, key: int) -> bool:
    label = _TOOL_KEY_LABELS.get(key)
    if label is None:
        return False
    combo = getattr(window, "tool_combo", None)
    if combo is None:
        return False
    index = combo.findText(label)
    if index < 0:
        return False
    combo.setCurrentIndex(index)
    window.statusBar().showMessage(f"Tool: {label}", 1800)
    return True


def _focus_editor_control(window, key: int) -> bool:
    target = None
    if key == Qt.Key.Key_T:
        target = getattr(window, "tool_combo", None)
    elif key == Qt.Key.Key_B:
        target = getattr(window, "tool_value", None)
    elif key == Qt.Key.Key_F:
        target = getattr(window, "function_combo", None)
    elif key == Qt.Key.Key_V:
        target = getattr(window, "visibility_combo", None)
    if target is None:
        return False
    target.setFocus(Qt.FocusReason.ShortcutFocusReason)
    select_all = getattr(target, "selectAll", None)
    if callable(select_all):
        select_all()
    return True


def _activate_current_tool(window, widget) -> bool:
    if not widget.selection.targets:
        cursor = _cursor(widget)
        if cursor is None:
            return False
        widget.set_selection(_selection_to_cursor(widget, cursor, extend=False))
    if len(widget.selection.targets) == 1:
        combo = getattr(window, "tool_combo", None)
        if combo is not None and combo.currentText().strip().casefold() == "toggle":
            cursor = _cursor(widget)
            click = getattr(window, "_phase10_click", None)
            if cursor is not None and callable(click):
                segment = widget._layout.segments[cursor.segment_index]
                click(widget, (segment, cursor.row_index, cursor.lane))
                return True
    apply_tool = getattr(window, "_apply_tool_to_selection", None)
    if callable(apply_tool):
        apply_tool()
        return True
    return False


def _handle_timeline_key(widget, event) -> bool:
    window = widget.window()
    key = event.key()
    modifiers = event.modifiers()
    exact_control = modifiers == Qt.KeyboardModifier.ControlModifier
    no_modifiers = modifiers == Qt.KeyboardModifier.NoModifier

    if no_modifiers and _select_tool(window, key):
        return True
    if no_modifiers and _focus_editor_control(window, key):
        return True

    if key in (
        Qt.Key.Key_Left,
        Qt.Key.Key_Right,
        Qt.Key.Key_Up,
        Qt.Key.Key_Down,
        Qt.Key.Key_Home,
        Qt.Key.Key_End,
    ) and not (modifiers & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)):
        cursor = _cursor(widget)
        if cursor is None:
            return False
        moved = _move_cursor(widget, cursor, key, modifiers)
        widget.set_selection(
            _selection_to_cursor(
                widget,
                moved,
                extend=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
            )
        )
        _ensure_cursor_visible(widget, moved)
        return True

    if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and modifiers in (
        Qt.KeyboardModifier.NoModifier,
        Qt.KeyboardModifier.ControlModifier,
    ):
        return _activate_current_tool(window, widget)

    if no_modifiers and key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
        return _trigger(getattr(window, "clear_selection_notes_action", None))
    if no_modifiers and key == Qt.Key.Key_Escape:
        return _trigger(getattr(window, "clear_selection_action", None))
    if exact_control and key == Qt.Key.Key_C:
        return _trigger(getattr(window, "copy_selection_action", None))
    if exact_control and key == Qt.Key.Key_X:
        return _trigger(getattr(window, "cut_selection_action", None))
    if exact_control and key == Qt.Key.Key_V:
        return _trigger(getattr(window, "paste_selection_action", None))
    if no_modifiers and key == Qt.Key.Key_X:
        return _trigger(getattr(window, "flip_horizontal_selection_action", None))
    if no_modifiers and key == Qt.Key.Key_Y:
        return _trigger(getattr(window, "flip_vertical_selection_action", None))
    if no_modifiers and key == Qt.Key.Key_M:
        return _trigger(getattr(window, "mirror_selection_action", None))
    return False


def _install_timeline_keyboard() -> None:
    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_keyboard_workflow_installed", False):
        return
    original_key_press = timeline_class.keyPressEvent

    def key_press_event(self, event) -> None:
        if _handle_timeline_key(self, event):
            event.accept()
            return
        original_key_press(self, event)

    timeline_class.keyPressEvent = key_press_event
    timeline_class._keyboard_workflow_installed = True


class _TreeKeyboardFilter(QObject):
    def __init__(self, window, *, routes: bool = False) -> None:
        super().__init__(window)
        self.window = window
        self.routes = routes

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.KeyPress:
            return False
        key = event.key()
        modifiers = event.modifiers()
        item = obj.currentItem()
        if item is None:
            return False

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and modifiers == Qt.KeyboardModifier.NoModifier:
            callback = self.window._route_activated if self.routes else self.window._tree_activated
            callback(item, obj.currentColumn())
            return True
        if self.routes:
            return False

        payload = item.data(0, Qt.ItemDataRole.UserRole)
        kind = payload[0] if payload and len(payload) >= 4 else None

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and modifiers == Qt.KeyboardModifier.AltModifier:
            if kind == "block":
                return _trigger(getattr(self.window, "edit_timing_action", None))
            if kind == "split":
                return _trigger(getattr(self.window, "phase12_edit_split_selection_action", None))
            if kind == "header":
                return _trigger(getattr(self.window, "edit_metadata_action", None))
            return False
        if key == Qt.Key.Key_Insert:
            if modifiers == Qt.KeyboardModifier.NoModifier:
                return _trigger(getattr(self.window, "insert_block_action", None))
            if modifiers == Qt.KeyboardModifier.ShiftModifier:
                return _trigger(getattr(self.window, "insert_split_action", None))
        if key == Qt.Key.Key_Delete:
            if modifiers == Qt.KeyboardModifier.ControlModifier:
                return _trigger(getattr(self.window, "remove_block_action", None))
            if modifiers == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                return _trigger(getattr(self.window, "remove_split_action", None))
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and modifiers in (
            Qt.KeyboardModifier.ControlModifier,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        ):
            direction = -1 if key == Qt.Key.Key_Up else 1
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                action = (
                    getattr(self.window, "move_split_up_action", None)
                    if direction < 0
                    else getattr(self.window, "move_split_down_action", None)
                )
            else:
                action = (
                    getattr(self.window, "move_block_up_action", None)
                    if direction < 0
                    else getattr(self.window, "move_block_down_action", None)
                )
            return _trigger(action)
        return False


def _focus_timeline(window) -> None:
    widget = window.tabs.currentWidget()
    if widget is not None:
        widget.setFocus(Qt.FocusReason.ShortcutFocusReason)


def _focus_side_tab(window, index: int, widget) -> None:
    window.side_tabs.setCurrentIndex(index)
    widget.setFocus(Qt.FocusReason.ShortcutFocusReason)


def _install_pane_shortcuts(window) -> None:
    shortcuts = []

    def add(sequence: str, callback) -> None:
        shortcut = QShortcut(QKeySequence(sequence), window)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut.activated.connect(callback)
        shortcuts.append(shortcut)

    add("Alt+1", lambda: window.tree.setFocus(Qt.FocusReason.ShortcutFocusReason))
    add("Alt+2", lambda: _focus_timeline(window))
    add("Alt+3", lambda: _focus_side_tab(window, 1, window.inspector))
    add("Alt+4", lambda: _focus_side_tab(window, 0, window.diagnostics))
    add("Alt+5", lambda: _focus_side_tab(window, 2, window.routes))
    window.keyboard_pane_shortcuts = tuple(shortcuts)


def _scope_selection_shortcuts(window) -> None:
    for name in (
        "apply_selection_action",
        "clear_selection_notes_action",
        "clear_selection_action",
        "copy_selection_action",
        "cut_selection_action",
        "paste_selection_action",
        "flip_horizontal_selection_action",
        "flip_vertical_selection_action",
        "mirror_selection_action",
    ):
        action = getattr(window, name, None)
        if action is not None:
            action.setShortcut(QKeySequence())


def _install_save_shortcuts(window) -> None:
    action = getattr(window, "save_action", None)
    if action is not None:
        action.setShortcuts((QKeySequence("Ctrl+S"), QKeySequence("Ctrl+Shift+S")))


def install_keyboard_workflow(window) -> None:
    if getattr(window, "_keyboard_workflow_installed", False):
        return
    window._keyboard_workflow_installed = True

    _install_timeline_keyboard()
    _scope_selection_shortcuts(window)
    _install_save_shortcuts(window)
    _install_pane_shortcuts(window)

    space = getattr(window, "phase10_space_shortcut", None)
    if space is not None:
        space.setContext(Qt.ShortcutContext.WindowShortcut)

    tree_filter = _TreeKeyboardFilter(window)
    window.tree.installEventFilter(tree_filter)
    routes_filter = _TreeKeyboardFilter(window, routes=True)
    window.routes.installEventFilter(routes_filter)
    window.keyboard_tree_filter = tree_filter
    window.keyboard_routes_filter = routes_filter
