from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from types import MethodType

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QMessageBox

from stepnx.authoring.lightmap import LightmapEdit, SetLightmapCells
from stepnx.authoring.selection import CellSelection, CellTarget
from stepnx.authoring.tools import NoteTool
from stepnx.core.commands import NoteEdit, SetNotesAt
from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import EmptyRow, LightmapRow, NoteRow, PackedNoteRow
from stepnx.gui.phase11_fast_notes import _row_index


_HOLD_TYPES = frozenset({0x7, 0xB, 0xF})
_ZERO_NOTE = b"\x00\x00\x00\x00"


@dataclass(frozen=True, slots=True)
class GridClipboard:
    """Clipboard geometry over the active Timeline row sequence.

    ``kind`` keeps Lightmap one-byte channel values separate from four-byte note
    cells. Row offsets deliberately count encoded rows, not musical ticks or
    elapsed time, so a selection can cross Blocks with different Beat Splits.
    """

    kind: str
    width: int
    height: int
    cells: tuple[tuple[int, int, bytes], ...]

    def __post_init__(self) -> None:
        if self.kind not in {"notes", "lightmap"}:
            raise ValueError(f"unknown grid clipboard kind {self.kind!r}")
        if self.width <= 0 or self.height <= 0 or not self.cells:
            raise ValueError("grid clipboard cannot be empty")
        expected = 4 if self.kind == "notes" else 1
        if any(len(raw) != expected for _row, _lane, raw in self.cells):
            raise ValueError(
                f"{self.kind} clipboard cells require {expected}-byte payloads"
            )


@dataclass(frozen=True, slots=True)
class _VisibleEntry:
    start: int
    segment_index: int
    segment: object
    row_count: int


class VisibleRowOrder:
    """Flat encoded-row order for the Blocks currently visible in Timeline."""

    def __init__(self, widget) -> None:
        entries = []
        starts = []
        total = 0
        for segment_index, segment in enumerate(widget._layout.segments):
            count = int(segment.block.row_count)
            if count <= 0:
                continue
            starts.append(total)
            entries.append(_VisibleEntry(total, segment_index, segment, count))
            total += count
        self.entries = tuple(entries)
        self.starts = tuple(starts)
        self.total = total

    def locate(self, row_id: int) -> tuple[_VisibleEntry, int, int]:
        wanted = int(row_id)
        for entry in self.entries:
            index = _row_index(entry.segment.block.rows, wanted)
            if index is not None:
                return entry, int(index), entry.start + int(index)
        raise ModelInvariantError(
            f"row stable ID {wanted} is not on the active Timeline route"
        )

    def at(self, ordinal: int) -> tuple[_VisibleEntry, int, int]:
        ordinal = int(ordinal)
        if not 0 <= ordinal < self.total:
            raise IndexError(ordinal)
        entry_index = bisect_right(self.starts, ordinal) - 1
        entry = self.entries[entry_index]
        local = ordinal - entry.start
        return entry, local, _row_id_at(entry.segment.block.rows, local)

    def row_ids(self, first: int, last: int) -> tuple[int, ...]:
        first = int(first)
        last = int(last)
        if first > last:
            first, last = last, first
        if not 0 <= first <= last < self.total:
            raise IndexError((first, last))
        result = []
        for entry in self.entries:
            entry_end = entry.start + entry.row_count - 1
            if entry_end < first:
                continue
            if entry.start > last:
                break
            local_first = max(0, first - entry.start)
            local_last = min(entry.row_count - 1, last - entry.start)
            result.extend(
                _row_id_at(entry.segment.block.rows, index)
                for index in range(local_first, local_last + 1)
            )
        return tuple(result)


def _row_id_at(rows, index: int) -> int:
    base = getattr(rows, "base", None)
    if base is not None and hasattr(base, "_row_ids"):
        replacement = next(
            (row for replacement_index, row in rows.replacements if replacement_index == index),
            None,
        )
        return int(replacement.stable_id) if replacement is not None else int(base._row_ids[index])
    if hasattr(rows, "_row_ids"):
        return int(rows._row_ids[index])
    return int(rows[index].stable_id)


def _selection_between(widget, target: CellTarget) -> CellSelection:
    """Extend from the original anchor through active Blocks/Splits by row count."""

    selection = widget.selection
    anchor = selection.anchor or target
    order = VisibleRowOrder(widget)
    try:
        _anchor_entry, _anchor_local, anchor_ordinal = order.locate(anchor.row_id)
        _target_entry, _target_local, target_ordinal = order.locate(target.row_id)
    except ModelInvariantError:
        return selection.replace(target)

    row_ids = order.row_ids(anchor_ordinal, target_ordinal)
    lane_start, lane_end = sorted((int(anchor.lane), int(target.lane)))
    targets = frozenset(
        CellTarget(row_id, lane)
        for row_id in row_ids
        for lane in range(lane_start, lane_end + 1)
    )
    return CellSelection(targets, anchor)


def _cell_payload(row, lane: int, *, lightmap: bool) -> bytes:
    lane = int(lane)
    if lightmap:
        if not 0 <= lane < 3:
            raise ModelInvariantError(f"Lightmap lane {lane} is outside the three-light field")
        if isinstance(row, EmptyRow):
            return b"\x00"
        if not isinstance(row, LightmapRow):
            raise ModelInvariantError("Lightmap selection contains a non-Lightmap row")
        return bytes((row.raw_channels[lane],))

    if isinstance(row, LightmapRow):
        raise ModelInvariantError("note selection contains a Lightmap row")
    if isinstance(row, EmptyRow):
        return _ZERO_NOTE
    if isinstance(row, PackedNoteRow):
        return row.cell(lane).raw
    if isinstance(row, NoteRow):
        return row.cells[lane].raw
    raise ModelInvariantError("unsupported Timeline row variant")


def _selection_positions(widget, selection: CellSelection):
    if not selection.targets:
        raise ValueError("selection is empty")
    order = VisibleRowOrder(widget)
    positions = {}
    for row_id in {target.row_id for target in selection.targets}:
        entry, local, ordinal = order.locate(row_id)
        positions[row_id] = (entry, local, ordinal)
    return order, positions


def copy_visible_selection(widget, selection: CellSelection | None = None) -> GridClipboard:
    selection = widget.selection if selection is None else selection
    order, positions = _selection_positions(widget, selection)
    del order
    first_row = min(positions[target.row_id][2] for target in selection.targets)
    first_lane = min(int(target.lane) for target in selection.targets)
    lightmap = bool(widget.snapshot.effective_lightmap)
    cells = []
    for target in sorted(
        selection.targets,
        key=lambda item: (positions[item.row_id][2], int(item.lane)),
    ):
        entry, local, ordinal = positions[target.row_id]
        row = entry.segment.block.rows[local]
        cells.append(
            (
                ordinal - first_row,
                int(target.lane) - first_lane,
                _cell_payload(row, target.lane, lightmap=lightmap),
            )
        )
    return GridClipboard(
        "lightmap" if lightmap else "notes",
        max(int(target.lane) for target in selection.targets) - first_lane + 1,
        max(positions[target.row_id][2] for target in selection.targets) - first_row + 1,
        tuple(cells),
    )


def erase_visible_selection(widget):
    selection = widget.selection
    if not selection.targets:
        raise ValueError("erase requires a non-empty selection")
    if widget.snapshot.effective_lightmap:
        return SetLightmapCells(
            tuple(
                LightmapEdit(target.row_id, target.lane, 0)
                for target in sorted(selection.targets)
            )
        )
    return SetNotesAt(
        tuple(
            NoteEdit(target.row_id, target.lane, _ZERO_NOTE)
            for target in sorted(selection.targets)
        )
    )


def paste_visible_clipboard(widget, clipboard: GridClipboard, anchor: CellTarget):
    lightmap = bool(widget.snapshot.effective_lightmap)
    expected_kind = "lightmap" if lightmap else "notes"
    if clipboard.kind != expected_kind:
        raise ValueError(
            "Lightmap and playable-chart clipboards are intentionally not interchangeable"
        )

    order = VisibleRowOrder(widget)
    _entry, _local, anchor_ordinal = order.locate(anchor.row_id)
    columns = 3 if lightmap else int(widget.snapshot.columns)
    if int(anchor.lane) + clipboard.width > columns:
        raise ValueError("paste would cross the document's lane boundary")
    if anchor_ordinal + clipboard.height > order.total:
        raise ValueError("paste would cross the end of the active Timeline route")

    targets = set()
    if lightmap:
        edits = []
        for row_offset, lane_offset, raw in clipboard.cells:
            _entry, _local, row_id = order.at(anchor_ordinal + row_offset)
            target = CellTarget(row_id, int(anchor.lane) + lane_offset)
            edits.append(LightmapEdit(target.row_id, target.lane, raw[0]))
            targets.add(target)
        command = SetLightmapCells(tuple(edits))
    else:
        note_edits = []
        for row_offset, lane_offset, raw in clipboard.cells:
            _entry, _local, row_id = order.at(anchor_ordinal + row_offset)
            target = CellTarget(row_id, int(anchor.lane) + lane_offset)
            note_edits.append(NoteEdit(target.row_id, target.lane, raw))
            targets.add(target)
        command = SetNotesAt(tuple(note_edits))

    return command, CellSelection(frozenset(targets), CellTarget(anchor.row_id, anchor.lane))


def _selection_rectangle(widget):
    selection = widget.selection
    order, positions = _selection_positions(widget, selection)
    ordinals = sorted({positions[target.row_id][2] for target in selection.targets})
    if ordinals != list(range(ordinals[0], ordinals[-1] + 1)):
        raise ValueError("a transform requires contiguous rows")
    lanes = tuple(sorted({int(target.lane) for target in selection.targets}))
    if lanes != tuple(range(lanes[0], lanes[-1] + 1)):
        raise ValueError("a transform requires contiguous columns")
    row_ids = order.row_ids(ordinals[0], ordinals[-1])
    expected = frozenset(
        CellTarget(row_id, lane) for row_id in row_ids for lane in lanes
    )
    if selection.targets != expected:
        raise ValueError("a transform requires a rectangular selection")
    return order, positions, row_ids, lanes


def transform_visible_selection(widget, mode: str):
    if widget.snapshot.effective_lightmap:
        raise ValueError("Lightmap Select supports Cut, Copy, Paste and Delete; note transforms do not apply")

    _order, positions, row_ids, lanes = _selection_rectangle(widget)
    row_count = len(row_ids)
    lane_count = len(lanes)
    if mode == "mirror":
        columns = int(widget.snapshot.columns)
        if lane_count == 5 and (
            (columns == 5 and lanes == tuple(range(5)))
            or (columns == 10 and lanes in (tuple(range(5)), tuple(range(5, 10))))
        ):
            permutation = (3, 4, 2, 0, 1)
        elif lane_count == 6 and (
            (columns == 6 and lanes == tuple(range(6)))
            or (columns == 10 and lanes == tuple(range(2, 8)))
        ):
            permutation = (5, 3, 4, 1, 2, 0)
        elif columns == 10 and lanes == tuple(range(10)):
            permutation = (8, 9, 7, 5, 6, 3, 4, 2, 0, 1)
        else:
            raise ValueError(
                "Mirror requires all 5 Single columns, either 5-column pad or all "
                "10 Double columns, or the 6 central Half Double columns"
            )
    elif mode not in {"horizontal", "vertical"}:
        raise ValueError(f"unknown selection transform {mode!r}")

    transformed = {}
    target_map = {}
    row_position_by_id = {row_id: index for index, row_id in enumerate(row_ids)}
    lane_position = {lane: index for index, lane in enumerate(lanes)}
    for source in widget.selection.targets:
        entry, local, _ordinal = positions[source.row_id]
        raw = _cell_payload(entry.segment.block.rows[local], source.lane, lightmap=False)
        row_pos = row_position_by_id[source.row_id]
        lane_pos = lane_position[int(source.lane)]
        if mode == "horizontal":
            destination_row = row_pos
            destination_lane = lane_count - 1 - lane_pos
        elif mode == "vertical":
            destination_row = row_count - 1 - row_pos
            destination_lane = lane_pos
        else:
            destination_row = row_pos
            destination_lane = permutation[lane_pos]
        target = CellTarget(row_ids[destination_row], lanes[destination_lane])
        transformed[target] = raw
        target_map[source] = target

    if len(transformed) != len(widget.selection.targets):
        raise ModelInvariantError("selection transform is not a bijection")
    command = SetNotesAt(
        tuple(
            NoteEdit(target.row_id, target.lane, raw)
            for target, raw in sorted(transformed.items())
        )
    )
    anchor = (
        target_map.get(widget.selection.anchor)
        if widget.selection.anchor is not None
        else None
    )
    return command, CellSelection(widget.selection.targets, anchor)


def _normal_toggle_command(window, widget):
    import stepnx.gui.phase10_install as phase10

    selection = widget.selection
    if not selection.targets:
        raise ValueError("Toggle requires a non-empty selection")
    order, positions = _selection_positions(widget, selection)
    del order
    _tool, value, functionality, visibility = phase10._tool_state(window)
    tap_raw = phase10._regular_note_raw(
        window, NoteTool.TAP, value, functionality, visibility
    )
    edits: dict[tuple[int, int], bytes] = {}

    for target in sorted(
        selection.targets,
        key=lambda item: (positions[item.row_id][2], int(item.lane)),
    ):
        entry, local, _ordinal = positions[target.row_id]
        rows = entry.segment.block.rows
        current = _cell_payload(rows[local], target.lane, lightmap=False)
        note_type = current[0] & 0x0F
        if note_type in _HOLD_TYPES:
            span = phase10._hold_span(entry.segment.block, target.lane, local)
            indexes = (local,) if span is None else range(span[0], span[1] + 1)
            for index in indexes:
                edits[(_row_id_at(rows, index), int(target.lane))] = _ZERO_NOTE
        elif current == _ZERO_NOTE:
            edits[(int(target.row_id), int(target.lane))] = tap_raw
        else:
            edits[(int(target.row_id), int(target.lane))] = _ZERO_NOTE

    return SetNotesAt(
        tuple(NoteEdit(row_id, lane, raw) for (row_id, lane), raw in sorted(edits.items()))
    )


def _lightmap_toggle_command(widget):
    selection = widget.selection
    if not selection.targets:
        raise ValueError("Toggle requires a non-empty selection")
    _order, positions = _selection_positions(widget, selection)
    edits = []
    for target in sorted(
        selection.targets,
        key=lambda item: (positions[item.row_id][2], int(item.lane)),
    ):
        entry, local, _ordinal = positions[target.row_id]
        current = _cell_payload(entry.segment.block.rows[local], target.lane, lightmap=True)[0]
        edits.append(LightmapEdit(target.row_id, target.lane, 0 if current else 1))
    return SetLightmapCells(tuple(edits))


def _lightmap_blocked(window) -> None:
    QMessageBox.information(
        window,
        "Lightmap editing",
        "LM.NX is not a playable chart. Lightmap authoring supports only Toggle and Select.",
    )


def _replace_action_handler(action, callback) -> None:
    if action is None:
        return
    try:
        action.triggered.disconnect()
    except (RuntimeError, TypeError):
        pass
    action.triggered.connect(lambda _checked=False: callback())


def _draw_three_channel_lightmap_row(widget, painter, channels: bytes, y: float, row_height: float) -> None:
    """Draw the three authorable bytes exactly on the three logical lanes."""

    colors = (QColor("#d67373"), QColor("#99dd99"), QColor("#7b7bd8"))
    lane_width = float(widget._geometry.lane_width)
    for lane, value in enumerate(channels[:3]):
        if not value:
            continue
        rect = QRectF(
            float(widget._geometry.ruler_width) + lane * lane_width + 2,
            float(y) + 2,
            max(1.0, lane_width - 4),
            max(1.0, float(row_height) - 4),
        )
        color = QColor(colors[lane])
        color.setAlpha(max(40, min(255, int(value))))
        painter.fillRect(rect, color)


def _install_cross_segment_mouse_selection() -> None:
    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_stepnx_cross_segment_selection", False):
        return
    timeline_class._stepnx_cross_segment_selection = True

    original_select_hit = timeline_class._select_hit
    original_mouse_move = timeline_class.mouseMoveEvent

    def select_hit(self, segment, row_index: int, lane: int, modifiers) -> None:
        target = CellTarget(_row_id_at(segment.block.rows, row_index), lane)
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.set_selection(_selection_between(self, target))
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            self.set_selection(self.selection.toggle(target))
            return
        original_select_hit(self, segment, row_index, lane, modifiers)

    def mouse_move(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and (
            self._selection_mode
            or event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            content_x = event.position().x() + self.horizontalScrollBar().value()
            content_y = event.position().y() + self.verticalScrollBar().value()
            hit = self._snapped_hit(self._layout.cell_at(content_x, content_y))
            if hit is not None:
                segment, row_index, lane = hit
                target = CellTarget(_row_id_at(segment.block.rows, row_index), lane)
                selection = _selection_between(self, target)
                if selection != self.selection:
                    self.set_selection(selection)
                event.accept()
                return
        original_mouse_move(self, event)

    timeline_class._select_hit = select_hit
    timeline_class.mouseMoveEvent = mouse_move
    timeline_class._stepnx_original_select_hit = original_select_hit
    timeline_class._stepnx_original_mouse_move = original_mouse_move


def _install_lightmap_renderer() -> None:
    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_stepnx_three_lane_lightmap_renderer", False):
        return
    timeline_class._stepnx_original_draw_lightmap_row = timeline_class._draw_lightmap_row
    timeline_class._draw_lightmap_row = _draw_three_channel_lightmap_row
    timeline_class._stepnx_three_lane_lightmap_renderer = True


def install_selection_lightmap_workflow(window) -> None:
    if getattr(window, "_stepnx_selection_lightmap_workflow", False):
        return
    window._stepnx_selection_lightmap_workflow = True

    import stepnx.gui.phase10_install as phase10

    _install_cross_segment_mouse_selection()
    _install_lightmap_renderer()

    original_click = window._phase10_click
    original_hold = window._phase10_hold
    original_drag_preview = window._phase10_drag_preview_allowed
    original_apply_tool = window._apply_tool_to_selection

    def execute_command(self, command, *, selection=None) -> bool:
        self._execute_bulk(command, selection=selection)
        return True

    def toggle_selection(self, widget=None) -> bool:
        widget = self.tabs.currentWidget() if widget is None else widget
        if widget is None or not hasattr(widget, "selection") or not widget.selection.targets:
            return False
        try:
            command = (
                _lightmap_toggle_command(widget)
                if widget.snapshot.effective_lightmap
                else _normal_toggle_command(self, widget)
            )
        except (ValueError, ModelInvariantError) as exc:
            QMessageBox.critical(self, "Cannot toggle selection", str(exc))
            return False
        return execute_command(self, command)

    window._stepnx_toggle_selection = MethodType(toggle_selection, window)

    def click(widget, hit):
        document_index = phase10._active_document_index(window, widget)
        if document_index is None:
            return
        document = window.sessions[document_index].current
        if not document.effective_lightmap:
            return original_click(widget, hit)
        mode = phase10._tool_mode(window)
        tool = NoteTool(window.tool_combo.currentData())
        if tool is NoteTool.SELECT:
            return
        if mode != "toggle":
            _lightmap_blocked(window)
            return
        segment, row_index, lane = hit
        row_id = _row_id_at(segment.block.rows, row_index)
        widget.set_selection(widget.selection.replace(CellTarget(row_id, lane)))
        return window._stepnx_toggle_selection(widget)

    def hold(widget, start, end):
        document_index = phase10._active_document_index(window, widget)
        if document_index is None:
            return
        document = window.sessions[document_index].current
        if not document.effective_lightmap:
            return original_hold(widget, start, end)
        # Lightmap Toggle is deliberately a cell operation, never a note Hold.
        # A dragged Toggle therefore commits the pressed cell only; multi-cell
        # Lightmap edits use Select plus the ordinary bulk operations.
        return click(widget, start)

    def drag_preview(widget, start, end):
        document_index = phase10._active_document_index(window, widget)
        if document_index is not None and window.sessions[document_index].current.effective_lightmap:
            return False
        return original_drag_preview(widget, start, end)

    window._phase10_click = click
    window._phase10_hold = hold
    window._phase10_drag_preview_allowed = drag_preview

    def apply_tool_to_selection(self) -> None:
        widget = self.tabs.currentWidget()
        if widget is None or not hasattr(widget, "selection") or not widget.selection.targets:
            return
        mode = phase10._tool_mode(self)
        tool = NoteTool(self.tool_combo.currentData())
        if widget.snapshot.effective_lightmap:
            if tool is NoteTool.SELECT:
                return
            if mode == "toggle":
                self._stepnx_toggle_selection(widget)
            else:
                _lightmap_blocked(self)
            return
        if mode == "toggle":
            self._stepnx_toggle_selection(widget)
            return
        original_apply_tool()

    window._apply_tool_to_selection = MethodType(apply_tool_to_selection, window)
    _replace_action_handler(
        getattr(window, "apply_selection_action", None),
        window._apply_tool_to_selection,
    )

    def copy_selected() -> None:
        widget = window.tabs.currentWidget()
        if widget is None or not hasattr(widget, "selection") or not widget.selection.targets:
            return
        try:
            clipboard = copy_visible_selection(widget)
        except (ValueError, ModelInvariantError) as exc:
            QMessageBox.critical(window, "Cannot copy selection", str(exc))
            return
        window.note_clipboard = clipboard
        noun = "light cell" if clipboard.kind == "lightmap" else "note cell"
        window.statusBar().showMessage(
            f"Copied {len(clipboard.cells)} {noun}(s)", 5000
        )
        window._refresh_edit_actions()

    def erase_selected() -> None:
        widget = window.tabs.currentWidget()
        if widget is None or not hasattr(widget, "selection") or not widget.selection.targets:
            return
        try:
            command = erase_visible_selection(widget)
        except (ValueError, ModelInvariantError) as exc:
            QMessageBox.critical(window, "Cannot erase selection", str(exc))
            return
        window._execute_bulk(command)

    def cut_selected() -> None:
        widget = window.tabs.currentWidget()
        if widget is None or not hasattr(widget, "selection") or not widget.selection.targets:
            return
        try:
            clipboard = copy_visible_selection(widget)
            command = erase_visible_selection(widget)
        except (ValueError, ModelInvariantError) as exc:
            QMessageBox.critical(window, "Cannot cut selection", str(exc))
            return
        window.note_clipboard = clipboard
        window._execute_bulk(command)
        window.statusBar().showMessage(
            f"Cut {len(clipboard.cells)} {'light cell' if clipboard.kind == 'lightmap' else 'note cell'}(s)",
            5000,
        )

    def paste_selected() -> None:
        widget = window.tabs.currentWidget()
        clipboard = window.note_clipboard
        if (
            widget is None
            or not hasattr(widget, "selection")
            or clipboard is None
            or widget.selection.anchor is None
        ):
            return
        if not isinstance(clipboard, GridClipboard):
            QMessageBox.critical(
                window,
                "Cannot paste selection",
                "The clipboard predates the cross-Block authoring workflow; copy the cells again.",
            )
            return
        try:
            command, selection = paste_visible_clipboard(
                widget, clipboard, widget.selection.anchor
            )
        except (ValueError, ModelInvariantError) as exc:
            QMessageBox.critical(window, "Cannot paste selection", str(exc))
            return
        window._execute_bulk(command, selection=selection)

    def transform_selected(mode: str, title: str) -> None:
        widget = window.tabs.currentWidget()
        if widget is None or not hasattr(widget, "selection") or not widget.selection.targets:
            return
        try:
            command, selection = transform_visible_selection(widget, mode)
        except (ValueError, ModelInvariantError) as exc:
            QMessageBox.critical(window, f"Cannot {title.lower()}", str(exc))
            return
        window._execute_bulk(command, selection=selection)

    _replace_action_handler(getattr(window, "copy_selection_action", None), copy_selected)
    _replace_action_handler(getattr(window, "cut_selection_action", None), cut_selected)
    _replace_action_handler(getattr(window, "paste_selection_action", None), paste_selected)
    _replace_action_handler(getattr(window, "clear_selection_notes_action", None), erase_selected)
    _replace_action_handler(
        getattr(window, "flip_horizontal_selection_action", None),
        lambda: transform_selected("horizontal", "Flip selection horizontally"),
    )
    _replace_action_handler(
        getattr(window, "flip_vertical_selection_action", None),
        lambda: transform_selected("vertical", "Flip selection vertically"),
    )
    _replace_action_handler(
        getattr(window, "mirror_selection_action", None),
        lambda: transform_selected("mirror", "Mirror selection"),
    )

    window._stepnx_copy_selected = copy_selected
    window._stepnx_cut_selected = cut_selected
    window._stepnx_paste_selected = paste_selected
    window._stepnx_erase_selected = erase_selected
