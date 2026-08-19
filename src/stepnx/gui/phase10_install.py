from __future__ import annotations

import os
import re
import tempfile
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import MethodType

from PySide6.QtCore import QElapsedTimer, QRect, Qt, Signal, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from stepnx.authoring import (
    NoteFunction,
    NoteTool,
    NoteVisibility,
    ShiftBlockStartTimes,
    note_tool_raw,
    set_selection_raw,
)
from stepnx.core.commands import InsertBlock, InsertSplit, SetBlockField, SetNoteAt
from stepnx.core.model import (
    EmptyRow,
    LightmapRow,
    NoteCell,
    NoteRow,
    PackedNoteRow,
)
from stepnx.core.scalars import RawF32, RawU32


_ALLOWED_CHART_AUDIO = frozenset({".mp3", ".aud", ".a"})
_HOLD_TYPES = frozenset({0x7, 0xB, 0xF})
_MBR_RE = re.compile(r"^\s*(\d+)\|(\d+)\|(\d+)\s*$")

_NORMAL_ITEM_TYPES = (
    (0, "Action"),
    (1, "Shield"),
    (2, "Charge"),
    (3, "Acceleration"),
    (4, "Flash"),
    (5, "Mine X"),
    (6, "Mine"),
    (7, "Attack"),
    (8, "Drain"),
    (9, "Heart"),
    (10, "2x"),
    (11, "Random Item"),
    (12, "3x"),
    (13, "4x"),
    (14, "8x"),
    (15, "1x"),
    (16, "Potion"),
    (17, "Rotate 0°"),
    (18, "Rotate 90°"),
    (19, "Rotate 180°"),
    (20, "Rotate 270°"),
    (21, "Random Velocity"),
    (22, "Death / Nuclear"),
    (23, "Hyper Potion"),
)

_DIVISION_TYPES = (
    (0, "Step G"),
    (1, "Step W"),
    (2, "Step A"),
    (3, "Step B"),
    (4, "Step C"),
)

_EXTENDED_ITEM_PROFILES = frozenset({
    "fiesta2",
    "prime2",
    "nxa-step5-patched",
})

_BASIC_BRAIN_CODES = (0, 1, 6, 7)
_BRAIN_CODE_LABELS = {
    0: "None / normal",
    1: "Renderer / context",
    6: "Incorrect / X",
    7: "Correct / O",
}


def _active_document_index(window, widget):
    return window.widget_documents.get(widget)


def _find_row(document, row_id: int):
    for split in document.splits:
        for block in split.blocks:
            for index, row in enumerate(block.rows):
                if row.stable_id == row_id:
                    return split, block, index, row
    return None


def _cell_raw(row, lane: int) -> bytes:
    if isinstance(row, EmptyRow):
        return b"\0\0\0\0"
    if isinstance(row, LightmapRow):
        raise ValueError("Lightmap cells are not note lanes")
    if isinstance(row, PackedNoteRow):
        return row.cell(lane).raw
    if isinstance(row, NoteRow):
        return row.cells[lane].raw
    raise ValueError("unsupported row variant")


def _tool_state(window):
    return (
        NoteTool(window.tool_combo.currentData()),
        window.tool_value.value(),
        NoteFunction(window.function_combo.currentData()),
        NoteVisibility(window.visibility_combo.currentData()),
    )


def _tool_mode(window) -> str:
    # Toggle deliberately shares Tap's data value so the untouched base editor
    # continues to understand the combo box.  The label distinguishes the new
    # StepEdit-style default from the old overwrite Tap tool.
    if window.tool_combo.currentText().strip().casefold() == "toggle":
        return "toggle"
    return str(NoteTool(window.tool_combo.currentData()).value)


def _compose_context_byte(player_slot: int = 0, brain_code: int = 0) -> int:
    if not 0 <= int(player_slot) <= 3:
        raise ValueError("Source Slot must be between 0 and 3")
    if not 0 <= int(brain_code) <= 63:
        raise ValueError("Brain Code must be between 0 and 63")
    return (int(player_slot) << 6) | int(brain_code)


def _selected_player_slot(window) -> int:
    # Source Slot stays out of the basic toolbar. It remains authorable
    # through the Advanced raw-fields dialog and preserved losslessly.
    if hasattr(window, "phase10_source_slot_value"):
        return int(window.phase10_source_slot_value)
    editor = getattr(window, "phase10_player_slot", None)
    return 0 if editor is None else int(editor.value())


def _selected_brain_code(window) -> int:
    if hasattr(window, "phase10_brain_code_value"):
        return int(window.phase10_brain_code_value)
    editor = getattr(window, "phase10_brain_code", None)
    if editor is None:
        return 0
    value = editor.currentData()
    return 0 if value is None else int(value)


def _special_item_raw(cell: int, slot: int = 0) -> bytes:
    if not 0 <= int(cell) <= 96:
        raise ValueError("SPECIAL.PNG cell must be between 0 and 96")
    return bytes((0x01, 0x03, 64 + int(cell), _compose_context_byte(slot, 0)))


def _number_block_raw(number: int, slot: int = 0) -> bytes:
    if not 0 <= int(number) <= 99:
        raise ValueError("Number Block must be between 00 and 99")
    return bytes((0x02, 0x03, 100 + int(number), _compose_context_byte(slot, 1)))


def _regular_note_raw(window, tool, value, functionality, visibility) -> bytes:
    raw = bytearray(note_tool_raw(tool, value, functionality, visibility))
    # ERASE must remain the canonical all-zero cell. Carrying Source Slot or
    # Brain Code into an empty type would leave a nonzero raw cell that the
    # NX20 model cannot collapse back to an EmptyRow.
    if raw == bytearray(b"\0\0\0\0"):
        return bytes(raw)
    raw[3] = _compose_context_byte(
        _selected_player_slot(window),
        _selected_brain_code(window),
    )
    return bytes(raw)


def _placement_raw(window, tool, value, functionality, visibility) -> bytes:
    override = getattr(window, "phase10_raw_override", None)
    slot = _selected_player_slot(window)
    if override is not None:
        kind, selected = override[:2]
        if kind == "special":
            return _special_item_raw(selected, slot)
        if kind == "number":
            return _number_block_raw(selected, slot)

    # In the patched profile the numeric Bank/ID field is also a typed path.
    # This keeps direct numeric entry equivalent to the Special picker:
    #   Item 64..160     -> SPECIAL.PNG cells 0..96
    #   Division 100..199 -> Number Block 00..99
    if _patched_profile(window):
        if tool is NoteTool.ITEM and 64 <= int(value) <= 160:
            return _special_item_raw(int(value) - 64, slot)
        if tool is NoteTool.DIVISION and 100 <= int(value) <= 199:
            return _number_block_raw(int(value) - 100, slot)

    return _regular_note_raw(window, tool, value, functionality, visibility)


def _clear_raw_override(window) -> None:
    window.phase10_raw_override = None


_VIS_STATUS = {
    0: "Hidden",
    1: "Appear",
    2: "Vanish",
    3: "Visible",
    6: "VanishLow",
    7: "AppearLow",
}


def _selection_status_text(window, widget) -> str:
    selection = getattr(widget, "selection", None)
    if selection is None or not selection.targets:
        return "Ready"
    if len(selection.targets) != 1:
        return f"{len(selection.targets)} cells selected"

    target = next(iter(selection.targets))
    document_index = _active_document_index(window, widget)
    if document_index is None:
        return "Ready"
    document = window.sessions[document_index].current
    found = _find_row(document, target.row_id)
    if found is None:
        return "Ready"
    _split, _block, row_index, row = found
    try:
        raw = _cell_raw(row, target.lane)
    except (ValueError, IndexError):
        return "Ready"

    if raw == b"\0\0\0\0":
        return f"Empty | Row {row_index} | Lane {target.lane + 1}"

    note_type = raw[0] & 0x0F
    subtype = raw[2]
    low6 = raw[3] & 0x3F
    slot = (raw[3] >> 6) & 0x03
    profile = getattr(document, "profile", "")

    if (
        profile == "nxa-step5-patched"
        and note_type == 0x1
        and raw[1] == 0x03
        and 64 <= subtype <= 160
        and low6 == 0
    ):
        type_text = f"SPECIAL cell {subtype - 64}"
    elif (
        profile == "nxa-step5-patched"
        and note_type == 0x2
        and raw[1] == 0x03
        and 100 <= subtype <= 199
        and low6 == 1
    ):
        type_text = f"Number Block {subtype - 100:02d}"
    elif note_type == 0x3:
        type_text = f"Tap (Bank {subtype})"
    elif note_type == 0x7:
        type_text = f"Hold Head (Bank {subtype})"
    elif note_type == 0xB:
        type_text = f"Hold Body (Bank {subtype})"
    elif note_type == 0xF:
        type_text = f"Hold Tail (Bank {subtype})"
    elif note_type == 0x1:
        type_text = f"Item ({dict(_NORMAL_ITEM_TYPES).get(subtype, subtype)})"
    elif note_type == 0x2:
        type_text = f"Division ({dict(_DIVISION_TYPES).get(subtype, subtype)})"
    else:
        type_text = f"Type 0x{note_type:X} / ID {subtype}"

    flags = []
    if raw[0] & 0x40:
        flags.append("REGISTER")
    if raw[0] & 0x20:
        flags.append("TRIGGER" if note_type == 0x2 else "NO_COMBO_BREAK")
    if raw[0] & 0x10:
        flags.append("HOLD")
    function_bits = raw[0] & 0x60
    if note_type != 0x2:
        flags.append({0x40: "Normal", 0x60: "Bonus", 0x20: "Ghost"}.get(
            function_bits, "RawFunction?"
        ))

    visibility = _VIS_STATUS.get(raw[1] & 0x07, f"VisRaw{raw[1] & 0x07}")
    if raw[1] & 0x10:
        visibility += "+Snake"
    flag_text = ",".join(flags) if flags else "no flags"
    raw_text = " ".join(f"{byte:02X}" for byte in raw)
    return (
        f"{type_text} | {flag_text} | {visibility} | "
        f"SourceSlot:{slot} | BS:{low6} | Raw:{raw_text}"
    )


def _update_selection_status(window, widget) -> None:
    label = getattr(window, "phase10_selection_status", None)
    if label is not None:
        label.setText(_selection_status_text(window, widget))


def _apply(window, document_index, widget, command, *, coalesce=False):
    key = window.gesture_keys.get(widget) if coalesce else None
    updated = window.sessions[document_index].execute(command, coalesce_key=key)
    window._apply_document(document_index, widget, updated)
    updater = getattr(window, "_phase10_update_selection_status", None)
    if callable(updater):
        updater(widget)
    return updated


class _SequenceCommand:
    def __init__(self, commands):
        self.commands = tuple(commands)

    def apply(self, document):
        result = document
        for command in self.commands:
            result = command.apply(result)
        return result


def _hold_span(block, lane: int, row_index: int) -> tuple[int, int] | None:
    rows = block.rows
    if not 0 <= row_index < len(rows):
        return None
    note_type = _cell_raw(rows[row_index], lane)[0] & 0x0F
    if note_type not in _HOLD_TYPES:
        return None

    lo = row_index
    hi = row_index
    if note_type != 0x7:
        while lo > 0:
            previous = _cell_raw(rows[lo - 1], lane)[0] & 0x0F
            if previous == 0x7:
                lo -= 1
                break
            if previous != 0xB:
                break
            lo -= 1
    if note_type != 0xF:
        while hi + 1 < len(rows):
            following = _cell_raw(rows[hi + 1], lane)[0] & 0x0F
            if following == 0xF:
                hi += 1
                break
            if following != 0xB:
                break
            hi += 1
    return lo, hi


def _erase_commands_for_cell(block, lane: int, row_index: int):
    span = _hold_span(block, lane, row_index)
    if span is None:
        indexes = (row_index,)
    else:
        indexes = range(span[0], span[1] + 1)
    return [
        SetNoteAt(block.rows[index].stable_id, lane, b"\0\0\0\0")
        for index in indexes
    ]


def _phase10_click(self, widget, hit) -> None:
    document_index = _active_document_index(self, widget)
    if document_index is None:
        return
    segment, row_index, lane = hit
    document = self.sessions[document_index].current
    found = _find_row(document, segment.block.rows[row_index].stable_id)
    if found is None:
        return
    _split, block, actual_index, row = found
    try:
        existing_type = _cell_raw(row, lane)[0] & 0x0F
        tool, value, functionality, visibility = _tool_state(self)
        mode = _tool_mode(self)
        if tool is NoteTool.SELECT:
            return

        if mode == "toggle":
            if existing_type != 0:
                commands = _erase_commands_for_cell(block, lane, actual_index)
                _apply(self, document_index, widget, _SequenceCommand(commands))
                return
            raw = _regular_note_raw(
                self, NoteTool.TAP, value, functionality, visibility
            )
            _apply(
                self,
                document_index,
                widget,
                SetNoteAt(row.stable_id, lane, raw),
            )
            return

        if mode == NoteTool.TAP.value:
            # Old Tap remains an overwrite tool.  If the target belongs to a
            # hold, remove the complete hold first so the overwrite cannot leave
            # a structurally broken long note behind.
            commands = []
            if existing_type in _HOLD_TYPES:
                commands.extend(_erase_commands_for_cell(block, lane, actual_index))
            raw = _regular_note_raw(
                self, NoteTool.TAP, value, functionality, visibility
            )
            commands.append(SetNoteAt(row.stable_id, lane, raw))
            _apply(self, document_index, widget, _SequenceCommand(commands))
            return

        raw = _placement_raw(self, tool, value, functionality, visibility)
        _apply(
            self,
            document_index,
            widget,
            SetNoteAt(row.stable_id, lane, raw),
        )
    except (ValueError, IndexError) as exc:
        QMessageBox.critical(self, "Cannot edit note", str(exc))


def _drag_rows_empty(document, start, end) -> bool:
    start_segment, start_row, lane = start
    end_segment, end_row, end_lane = end
    if (
        start_segment.block.stable_id != end_segment.block.stable_id
        or lane != end_lane
    ):
        return False
    split = next(
        (item for item in document.splits if item.stable_id == start_segment.split_id),
        None,
    )
    if split is None:
        return False
    block = next(
        (item for item in split.blocks if item.stable_id == start_segment.block.stable_id),
        None,
    )
    if block is None:
        return False
    lo, hi = sorted((start_row, end_row))
    return all((_cell_raw(block.rows[index], lane)[0] & 0x0F) == 0 for index in range(lo, hi + 1))


def _phase10_apply_tool_to_selection(self) -> None:
    widget = self.tabs.currentWidget()
    if widget is None or not hasattr(widget, "selection") or not widget.selection.targets:
        return
    tool, value, functionality, visibility = _tool_state(self)
    if tool is NoteTool.SELECT:
        return
    try:
        raw = _placement_raw(self, tool, value, functionality, visibility)
        command = set_selection_raw(widget.selection, raw)
    except ValueError as exc:
        QMessageBox.critical(self, "Cannot edit selection", str(exc))
        return
    self._execute_bulk(command)


def _phase10_drag_preview_allowed(self, widget, start, end) -> bool:
    if _tool_mode(self) != "toggle":
        return False
    document_index = _active_document_index(self, widget)
    if document_index is None:
        return False
    return _drag_rows_empty(self.sessions[document_index].current, start, end)


def _phase10_hold(self, widget, start, end) -> None:
    document_index = _active_document_index(self, widget)
    if document_index is None:
        return
    mode = _tool_mode(self)
    if mode != "toggle":
        # The legacy Tap tool is still a direct overwrite tool, not a hold
        # gesture.  A drag therefore commits the original clicked cell.
        self._phase10_click(widget, start)
        return

    start_segment, start_row, lane = start
    end_segment, end_row, end_lane = end
    if (
        start_segment.block.stable_id != end_segment.block.stable_id
        or lane != end_lane
    ):
        return
    document = self.sessions[document_index].current
    found = _find_row(document, start_segment.block.rows[start_row].stable_id)
    if found is None:
        return
    _split, block, actual_start, start_model_row = found
    try:
        start_type = _cell_raw(start_model_row, lane)[0] & 0x0F
        if start_type != 0:
            # Toggle over any existing note means erase, even if the pointer was
            # moved before release.
            commands = _erase_commands_for_cell(block, lane, actual_start)
            _apply(self, document_index, widget, _SequenceCommand(commands))
            return
        if not _drag_rows_empty(document, start, end):
            self.statusBar().showMessage(
                "Toggle hold requires an empty span; gesture was not applied",
                4000,
            )
            return

        _tool, value, functionality, visibility = _tool_state(self)
        lo, hi = sorted((start_row, end_row))
        rows = start_segment.block.rows
        commands = []
        for index in range(lo, hi + 1):
            part = (
                NoteTool.HOLD_HEAD
                if index == lo
                else NoteTool.HOLD_TAIL
                if index == hi
                else NoteTool.HOLD_BODY
            )
            raw = _regular_note_raw(
                self, part, value, functionality, visibility
            )
            commands.append(SetNoteAt(rows[index].stable_id, lane, raw))
        _apply(self, document_index, widget, _SequenceCommand(commands))
    except (ValueError, IndexError) as exc:
        QMessageBox.critical(self, "Cannot create hold", str(exc))


def _split_and_block(document, split_id: int, block_id: int):
    split = next((item for item in document.splits if item.stable_id == split_id), None)
    if split is None:
        raise ValueError("Split no longer exists")
    block = next((item for item in split.blocks if item.stable_id == block_id), None)
    if block is None:
        raise ValueError("Block no longer exists")
    return split, block


def _format_mbr(row_count: int, beat_split: int, beat_measure: int) -> str:
    if beat_split <= 0 or beat_measure <= 0:
        raise ValueError("Beat Split and Beat Measure must be positive")
    beats, row = divmod(int(row_count), int(beat_split))
    measures, beat = divmod(beats, int(beat_measure))
    return f"{measures}|{beat}|{row}"


def _parse_mbr(text: str, beat_split: int, beat_measure: int) -> int:
    match = _MBR_RE.match(text)
    if match is None:
        raise ValueError("use Measure|Beat|Row, for example 110|0|0")
    measure, beat, row = (int(value) for value in match.groups())
    if beat >= beat_measure:
        raise ValueError(f"Beat must be between 0 and {beat_measure - 1}")
    if row >= beat_split:
        raise ValueError(f"Row must be between 0 and {beat_split - 1}")
    count = (measure * beat_measure + beat) * beat_split + row
    if count <= 0:
        raise ValueError("Split size must be greater than zero")
    return count


def _clone_row_with_ids(row, next_id: int):
    if isinstance(row, EmptyRow):
        return EmptyRow(next_id, row.raw, None), next_id + 1
    if isinstance(row, LightmapRow):
        return LightmapRow(next_id, row.raw_channels, None), next_id + 1
    if isinstance(row, PackedNoteRow):
        first_cell_id = next_id
        next_id += row.cell_count
        cloned = PackedNoteRow(next_id, first_cell_id, row.raw_cells, None)
        return cloned, next_id + 1
    cells = []
    for cell in row.cells:
        cells.append(NoteCell(next_id, cell.raw, None))
        next_id += 1
    return NoteRow(next_id, tuple(cells), None), next_id + 1


def _clone_rows_with_ids(rows, next_id: int):
    result = []
    for row in rows:
        cloned, next_id = _clone_row_with_ids(row, next_id)
        result.append(cloned)
    return tuple(result), next_id


def _resize_split_to_reference_rows(document, split_id: int, reference_block_id: int, reference_rows: int):
    split, reference = _split_and_block(document, split_id, reference_block_id)
    reference_split = int(reference.beat_split.value)
    if reference_split <= 0:
        raise ValueError("reference Block has invalid Beat Split")
    musical_beats = Fraction(reference_rows, reference_split)
    next_id = document.next_stable_id
    blocks = []
    for block in split.blocks:
        block_split = int(block.beat_split.value)
        wanted = musical_beats * block_split
        if wanted.denominator != 1:
            raise ValueError(
                f"requested Split length cannot be represented exactly by Block {block.stable_id} "
                f"with Beat Split {block_split}"
            )
        count = int(wanted)
        current_rows = tuple(block.rows)
        if count < len(current_rows):
            rows = current_rows[:count]
        else:
            rows = list(current_rows)
            while len(rows) < count:
                rows.append(EmptyRow(next_id, b"\x80\0\0\0", None))
                next_id += 1
            rows = tuple(rows)
        blocks.append(
            replace(
                block,
                rows=rows,
                row_count=RawU32.from_value(count),
                span=None,
            )
        )
    new_split = replace(split, blocks=tuple(blocks), span=None)
    splits = tuple(new_split if item.stable_id == split_id else item for item in document.splits)
    return replace(document, splits=splits, next_stable_id=next_id)


class _ReplaceDocument:
    def __init__(self, result):
        self.result = result

    def apply(self, document):
        return self.result


class _SplitHereCommand:
    def __init__(self, split_id: int, reference_block_id: int, reference_row: int):
        self.split_id = split_id
        self.reference_block_id = reference_block_id
        self.reference_row = reference_row

    def apply(self, document):
        split, reference = _split_and_block(
            document, self.split_id, self.reference_block_id
        )
        if not 0 < self.reference_row < len(reference.rows):
            raise ValueError("Split here requires a row inside the current Split")
        ref_split = int(reference.beat_split.value)
        if ref_split <= 0:
            raise ValueError("reference Block has invalid Beat Split")
        beat_position = Fraction(self.reference_row, ref_split)
        first_blocks = []
        second_blocks = []
        for block in split.blocks:
            beat_split = int(block.beat_split.value)
            boundary = beat_position * beat_split
            if boundary.denominator != 1:
                raise ValueError(
                    f"split point cannot be represented exactly by Block {block.stable_id} "
                    f"with Beat Split {beat_split}"
                )
            cut = int(boundary)
            if not 0 < cut < len(block.rows):
                raise ValueError("split point falls outside one of the Split's Blocks")
            first_rows = tuple(block.rows[:cut])
            second_rows = tuple(block.rows[cut:])
            first_blocks.append(
                replace(
                    block,
                    rows=first_rows,
                    row_count=RawU32.from_value(len(first_rows)),
                    span=None,
                )
            )
            bpm = float(block.bpm.value)
            if bpm <= 0 or beat_split <= 0:
                raise ValueError("Block has invalid BPM or Beat Split")
            second_start = float(block.start_time.value) + cut * 60_000.0 / (
                bpm * beat_split
            )
            second_blocks.append(
                replace(
                    block,
                    start_time=RawF32.from_value(second_start),
                    rows=second_rows,
                    row_count=RawU32.from_value(len(second_rows)),
                    span=None,
                )
            )

        first_split = replace(split, blocks=tuple(first_blocks), span=None)
        second_prototype = replace(split, blocks=tuple(second_blocks), span=None)
        split_index = next(
            i for i, item in enumerate(document.splits) if item.stable_id == self.split_id
        )
        before_id = (
            document.splits[split_index + 1].stable_id
            if split_index + 1 < len(document.splits)
            else None
        )
        updated = replace(
            document,
            splits=tuple(
                first_split if item.stable_id == self.split_id else item
                for item in document.splits
            ),
        )
        return InsertSplit(second_prototype, before_split_id=before_id).apply(updated)


class _MergeSplitsCommand:
    def __init__(self, split_id: int):
        self.split_id = split_id

    def apply(self, document):
        index = next(
            (i for i, item in enumerate(document.splits) if item.stable_id == self.split_id),
            -1,
        )
        if index < 0 or index + 1 >= len(document.splits):
            raise ValueError("there is no Split below this one to merge")
        upper = document.splits[index]
        lower = document.splits[index + 1]
        if not upper.blocks or not lower.blocks:
            raise ValueError("both Splits need at least one Block")

        next_id = document.next_stable_id
        merged_blocks = []
        for branch_index, upper_block in enumerate(upper.blocks):
            source = (
                lower.blocks[branch_index]
                if branch_index < len(lower.blocks)
                else lower.blocks[0]
            )
            lower_rows = tuple(source.rows)
            if branch_index >= len(lower.blocks):
                lower_rows, next_id = _clone_rows_with_ids(lower_rows, next_id)
            rows = tuple(upper_block.rows) + lower_rows
            merged_blocks.append(
                replace(
                    upper_block,
                    rows=rows,
                    row_count=RawU32.from_value(len(rows)),
                    span=None,
                )
            )
        merged = replace(upper, blocks=tuple(merged_blocks), span=None)
        splits = (
            *document.splits[:index],
            merged,
            *document.splits[index + 2 :],
        )
        return replace(document, splits=splits, next_stable_id=next_id)


def _empty_block_same_length(block):
    rows = tuple(
        EmptyRow(0, b"\x80\0\0\0", None) for _ in range(len(block.rows))
    )
    return replace(
        block,
        rows=rows,
        row_count=RawU32.from_value(len(rows)),
        span=None,
    )


def _phase10_context_action(
    self,
    widget,
    action: str,
    split_id: int,
    block_id: int,
    row_index: int | None = None,
) -> None:
    document_index = _active_document_index(self, widget)
    if document_index is None:
        return
    document = self.sessions[document_index].current
    try:
        split, block = _split_and_block(document, split_id, block_id)
        from stepnx.authoring.structure import StructureTarget, remove_block

        target = StructureTarget(split_id, block_id)
        if action == "split-here":
            if row_index is None:
                return
            command = _SplitHereCommand(split_id, block_id, row_index)
        elif action == "merge-splits":
            split_index = next(
                i for i, item in enumerate(document.splits) if item.stable_id == split_id
            )
            if split_index + 1 >= len(document.splits):
                return
            lower = document.splits[split_index + 1]
            answer = QMessageBox.warning(
                self,
                "Merge Splits",
                "Merge this Split with the Split immediately below?\n\n"
                f"Upper Split: {len(split.blocks)} Block(s)\n"
                f"Lower Split: {len(lower.blocks)} Block(s)\n\n"
                "The merged Split keeps the UPPER Split's Block count, timing, "
                "metadata, and Block settings. Lower rows are appended by branch "
                "index; extra lower branches are discarded, and if the lower Split "
                "has fewer branches its first branch is cloned for the remaining "
                "upper branches. This can discard lower-Split timing information.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            command = _MergeSplitsCommand(split_id)
        elif action == "resize-split":
            beat_split = int(block.beat_split.value)
            beat_measure = int(block.beat_measure.value)
            current_text = _format_mbr(len(block.rows), beat_split, beat_measure)
            text, accepted = QInputDialog.getText(
                self,
                "Resize Split",
                f"Measure|Beat|Row  (Beat Split {beat_split}, Measure {beat_measure}):",
                text=current_text,
            )
            if not accepted:
                return
            reference_rows = _parse_mbr(text, beat_split, beat_measure)
            if reference_rows == len(block.rows):
                return
            if reference_rows < len(block.rows):
                answer = QMessageBox.warning(
                    self,
                    "Resize Split",
                    "Shrinking truncates rows from every Block in this Split. Continue?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            result = _resize_split_to_reference_rows(
                document, split_id, block_id, reference_rows
            )
            command = _ReplaceDocument(result)
        elif action == "insert-block":
            index = next(i for i, item in enumerate(split.blocks) if item.stable_id == block_id)
            before = (
                split.blocks[index + 1].stable_id
                if index + 1 < len(split.blocks)
                else None
            )
            command = InsertBlock(
                split_id,
                _empty_block_same_length(block),
                before_block_id=before,
            )
        elif action == "duplicate-block":
            index = next(i for i, item in enumerate(split.blocks) if item.stable_id == block_id)
            before = (
                split.blocks[index + 1].stable_id
                if index + 1 < len(split.blocks)
                else None
            )
            command = InsertBlock(split_id, block, before_block_id=before)
        elif action == "delete-block":
            if QMessageBox.question(
                self,
                "Delete Block",
                "Delete this Block?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return
            command = remove_block(document, target)
        else:
            return

        updated = self.sessions[document_index].execute(command)
        tree_selection = ("split", document_index, split_id, None)
        self._apply_document(
            document_index, widget, updated, tree_selection=tree_selection
        )
    except Exception as exc:
        QMessageBox.critical(self, "Cannot edit structure", str(exc))


def _phase10_timing_context(self):
    selection = self._structure_selection()
    if selection is None:
        return None
    _kind, document_index, target = selection
    if target.block_id is None:
        return None
    document = self.sessions[document_index].current
    split_index = next(
        (i for i, item in enumerate(document.splits) if item.stable_id == target.split_id),
        -1,
    )
    if split_index < 0:
        return None
    split = document.splits[split_index]
    block_index = next(
        (i for i, item in enumerate(split.blocks) if item.stable_id == target.block_id),
        -1,
    )
    if block_index < 0:
        return None
    return {
        "document_index": document_index,
        "split_id": target.split_id,
        "block_id": target.block_id,
        "is_first": split_index == 0 and block_index == 0,
    }


class _SheetLabel(QLabel):
    chosen = Signal(int)

    def __init__(self, pixmap: QPixmap, columns: int, rows: int, mapper, parent=None):
        super().__init__(parent)
        self._columns = columns
        self._rows = rows
        self._mapper = mapper
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.width() and self.height():
            column = min(
                self._columns - 1,
                max(0, int(event.position().x() * self._columns / self.width())),
            )
            row = min(
                self._rows - 1,
                max(0, int(event.position().y() * self._rows / self.height())),
            )
            value = self._mapper(column, row)
            if value is not None:
                self.chosen.emit(int(value))
                event.accept()
                return
        super().mousePressEvent(event)


class _TwoDigitSpinBox(QSpinBox):
    def textFromValue(self, value: int) -> str:
        return f"{value:02d}"


def _sheet_page(dialog, pixmap: QPixmap, columns: int, rows: int, mapper, explanation: str):
    page = QWidget(dialog)
    layout = QVBoxLayout(page)
    layout.addWidget(QLabel(explanation, page))
    scroll = QScrollArea(page)
    scroll.setWidgetResizable(False)
    label = _SheetLabel(pixmap, columns, rows, mapper, scroll)
    scroll.setWidget(label)
    layout.addWidget(scroll)
    return page, label


def _active_profile_name(window) -> str:
    for name, action in getattr(window, "profile_actions", {}).items():
        if action.isChecked():
            return str(name)
    return "nxa-native"


def _patched_profile(window) -> bool:
    return _active_profile_name(window) == "nxa-step5-patched"


def _item_types_for_profile(profile_name: str):
    maximum = 23 if profile_name in _EXTENDED_ITEM_PROFILES else 20
    return tuple(item for item in _NORMAL_ITEM_TYPES if item[0] <= maximum)


def _type_picker(window):
    tool = NoteTool(window.tool_combo.currentData())
    if tool is NoteTool.ITEM:
        table = _item_types_for_profile(_active_profile_name(window))
    elif tool is NoteTool.DIVISION:
        table = _DIVISION_TYPES
    else:
        table = ()
    if not table:
        return
    labels = [f"{value:02d} — {name}" for value, name in table]
    current_value = int(window.tool_value.value())
    current_index = next((i for i, (value, _name) in enumerate(table) if value == current_value), 0)
    selected, accepted = QInputDialog.getItem(
        window,
        "Item type" if tool is NoteTool.ITEM else "Division type",
        "Type:",
        labels,
        current_index,
        False,
    )
    if not accepted:
        return
    index = labels.index(selected)
    _clear_raw_override(window)
    window.tool_value.setValue(table[index][0])


def _set_tool_combo(window, tool: NoteTool) -> None:
    index = window.tool_combo.findData(tool.value)
    if index >= 0:
        window.tool_combo.setCurrentIndex(index)


def _select_special_visual(window, dialog, cell: int) -> None:
    slot = _selected_player_slot(window)
    raw = _special_item_raw(cell, slot)
    _set_tool_combo(window, NoteTool.ITEM)
    window.tool_value.setValue(raw[2])
    window.phase10_raw_override = ("special", int(cell))
    window.statusBar().showMessage(
        f"SPECIAL.PNG cell {cell} selected — raw {raw.hex(' ').upper()}", 5000
    )
    dialog.accept()


def _select_number_block(window, dialog, number: int) -> None:
    slot = _selected_player_slot(window)
    raw = _number_block_raw(number, slot)
    _set_tool_combo(window, NoteTool.DIVISION)
    window.tool_value.setValue(raw[2])
    window.phase10_raw_override = ("number", int(number))
    window.statusBar().showMessage(
        f"Number Block {number:02d} selected — raw {raw.hex(' ').upper()}", 5000
    )
    dialog.accept()


def _special_picker(window):
    if not _patched_profile(window):
        return
    pack = window.noteskin
    if pack is None or pack.special_items is None:
        QMessageBox.information(
            window,
            "Special",
            "The loaded noteskin has no ITEM/SPECIAL.PNG atlas.",
        )
        return

    special = pack.special_items
    source = QPixmap(str(special.path))
    if source.isNull():
        QMessageBox.information(
            window,
            "Special",
            "ITEM/SPECIAL.PNG could not be loaded as an image.",
        )
        return

    dialog = QDialog(window)
    dialog.setWindowTitle("NXA-Patched Special — ITEM/SPECIAL.PNG")
    layout = QVBoxLayout(dialog)
    existing_cells = special.columns * special.rows

    def mapper(column, row):
        cell = row * special.columns + column
        return cell if 0 <= cell < existing_cells and cell <= 96 else None

    page, label = _sheet_page(
        dialog,
        source,
        special.columns,
        special.rows,
        mapper,
        "Click a SPECIAL.PNG cell for the inert Item encoding "
        "01 03 (64+cell) (SourceSlot<<6). Direct Bank/ID 64..160 uses the same path.",
    )
    label.chosen.connect(lambda cell: _select_special_visual(window, dialog, cell))
    layout.addWidget(page)

    number_row = QHBoxLayout()
    number_row.addWidget(QLabel("Number Block:", dialog))
    number = _TwoDigitSpinBox(dialog)
    number.setRange(0, 99)
    current_value = int(window.tool_value.value())
    number.setValue(current_value - 100 if 100 <= current_value <= 199 else 0)
    number_row.addWidget(number)
    use_number = QPushButton("Use Number Block", dialog)
    use_number.setToolTip(
        "00–99 uses 02 03 (100+n) ((SourceSlot<<6)|1). "
        "Direct Division ID 100..199 uses the same path."
    )
    use_number.clicked.connect(
        lambda: _select_number_block(window, dialog, number.value())
    )
    number_row.addWidget(use_number)
    number_row.addStretch(1)
    layout.addLayout(number_row)

    note = QLabel(
        "The raw encoder accepts SPECIAL cell 0..96. "
        f"This loaded atlas exposes {existing_cells} physical tile(s).",
        dialog,
    )
    layout.addWidget(note)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, dialog)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(min(1100, source.width() + 40), min(620, source.height() + 150))
    dialog.exec()


def _first_block(window, widget):
    document_index = _active_document_index(window, widget)
    if document_index is None:
        return None
    document = window.sessions[document_index].current
    if not document.splits or not document.splits[0].blocks:
        return None
    return document_index, document.splits[0].blocks[0]


def _refresh_start_time(window):
    editor = getattr(window, "phase10_start_time", None)
    if editor is None:
        return
    widget = window.tabs.currentWidget()
    found = _first_block(window, widget)
    editor.blockSignals(True)
    try:
        editor.setEnabled(found is not None)
        if found is not None:
            _index, block = found
            editor.setValue(float(block.start_time.value))
    finally:
        editor.blockSignals(False)


class _ShiftChartAnchor:
    def __init__(self, first_block_id: int, new_start: float):
        self.first_block_id = first_block_id
        self.new_start = float(new_start)

    def apply(self, document):
        first = None
        for split in document.splits:
            for block in split.blocks:
                if block.stable_id == self.first_block_id:
                    first = block
                    break
            if first is not None:
                break
        if first is None:
            raise ValueError("first Block no longer exists")
        old_start = float(first.start_time.value)
        delta = self.new_start - old_start
        if delta == 0.0:
            return document
        result = ShiftBlockStartTimes(delta).apply(document)
        new_offset = float(first.offset_or_delay.value) + delta
        return SetBlockField(
            self.first_block_id,
            "offset_or_delay",
            RawF32.from_value(new_offset),
        ).apply(result)


def _set_first_start_time(window, value: float):
    widget = window.tabs.currentWidget()
    found = _first_block(window, widget)
    if found is None:
        return
    document_index, block = found
    try:
        updated = window.sessions[document_index].execute(
            _ShiftChartAnchor(block.stable_id, float(value))
        )
        window._apply_document(document_index, widget, updated)
        _refresh_start_time(window)
    except Exception as exc:
        QMessageBox.critical(window, "Cannot set chart Start Time", str(exc))


def _open_external_gameplay_preview(window) -> None:
    """Build the external preview directly.

    An earlier adapter depended on calling the base QAction callback and harvesting
    the tab it created.  That is unsafe because the original QAction connection
    may still fire before our replacement callback.  If that happens, the base
    handler changes the current tab to GameplayPreviewWidget; a second call then
    sees no active authoring TimelineWidget and creates no tab.

    This function reproduces the base route-building path directly and never
    creates a temporary preview tab.
    """
    import secrets

    from stepnx.authoring import create_authoring_snapshot
    from stepnx.core.validation import Severity
    from stepnx.gui.phase10_preview import Phase10GameplayPreviewWidget
    from stepnx.gui.preview_dialog import (
        GameplayInitializationDialog,
        PreviewChartChoice,
    )
    from stepnx.preview import (
        RoutePolicy,
        build_event_stream,
        create_preview_snapshot,
        parse_gameplay_command,
        resolve_route,
    )

    current_document_index = window._current_document_index()
    if current_document_index is None or window.workspace is None:
        QMessageBox.information(
            window,
            "Gameplay preview",
            "Select an authoring timeline before opening a gameplay preview.",
        )
        return

    charts = tuple(
        PreviewChartChoice(document_index, entry.path.name)
        for document_index, entry in enumerate(window.workspace.documents)
        if not window.sessions[document_index].current.effective_lightmap
    )
    if not charts:
        QMessageBox.information(
            window,
            "Gameplay preview",
            "The workspace has no playable NX chart.",
        )
        return

    dialog = GameplayInitializationDialog(
        charts,
        current_document_index=current_document_index,
        parent=window,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    options = dialog.options()
    document_index = options.document_index
    command = parse_gameplay_command(options.command).with_speed(options.speed)
    if command.unknown:
        QMessageBox.warning(
            window,
            "Unknown COMMAND",
            "Unsupported character(s): " + ", ".join(command.unknown),
        )
        return

    snapshot = create_preview_snapshot(window.sessions[document_index].current)
    random_route = any(
        split.random_at_start or split.random_at_trigger
        for split in snapshot.splits
    )
    policy = RoutePolicy.SEEDED if random_route else RoutePolicy.MANUAL
    seed = secrets.randbits(64) if random_route else None

    errors = [
        diagnostic
        for diagnostic in snapshot.diagnostics
        if diagnostic.severity is Severity.ERROR
    ]
    if errors:
        QMessageBox.warning(
            window,
            "Gameplay preview unavailable",
            "\n".join(f"{item.code}: {item.message}" for item in errors[:12]),
        )
        return

    # widget_documents contains authoring TimelineWidgets only, so this lookup
    # does not depend on importing the patched TimelineWidget class here.
    selected_view = next(
        (
            window.tabs.widget(index)
            for index in range(window.tabs.count())
            if window.widget_documents.get(window.tabs.widget(index))
            == document_index
        ),
        None,
    )
    manual = (
        dict(selected_view.snapshot.active_blocks)
        if selected_view is not None
        else {
            split.stable_id: split.blocks[0].stable_id
            for split in snapshot.splits
            if split.blocks
        }
    )

    route = resolve_route(snapshot, policy, seed=seed, manual=manual)
    if not route.is_executable:
        QMessageBox.warning(
            window,
            "Route cannot be previewed",
            "\n".join(
                f"{'Split ' + str(item.split_id) if item.split_id else 'Document'}: "
                f"{item.message}"
                for item in route.diagnostics
            ),
        )
        return

    stream = build_event_stream(snapshot, route)
    preview = Phase10GameplayPreviewWidget(
        stream,
        columns=snapshot.columns,
        start_column=snapshot.start_column,
        command=command,
    )
    preview.set_noteskin_pack(window.noteskin)
    preview.seekRequested.connect(
        lambda chart_time: window.audio_transport.seek(
            round(window.audio_alignment.chart_to_audio(chart_time))
        )
    )
    preview.statusChanged.connect(
        lambda message: window.statusBar().showMessage(message, 4000)
    )
    preview.set_playback_time(
        window.audio_alignment.audio_to_chart(float(window.audio_position.value()))
    )

    # Resolve the metronome route exactly as the base tab-preview path does.
    metronome_snapshot = create_authoring_snapshot(
        window.sessions[document_index].current
    )
    for decision in route.decisions:
        metronome_snapshot = metronome_snapshot.with_active_block(
            decision.split_id, decision.block_id
        )

    preview.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.WindowTitleHint
        | Qt.WindowType.WindowCloseButtonHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.MSWindowsFixedSizeDialogHint
    )
    entry = window.workspace.documents[document_index]
    preview.setWindowTitle(f"StepNX Preview — {entry.path.name}")
    preview.setFixedSize(640, 480)
    preview.setWindowState(Qt.WindowState.WindowNoState)

    window.phase10_preview_windows.append(preview)
    if not hasattr(window, "phase10_preview_snapshots"):
        window.phase10_preview_snapshots = {}
    window.phase10_preview_snapshots[preview] = metronome_snapshot

    def preview_destroyed(*_args):
        if preview in window.phase10_preview_windows:
            window.phase10_preview_windows.remove(preview)
        window.phase10_preview_snapshots.pop(preview, None)
        # Restore metronome context to whichever authoring tab is active.
        try:
            window._active_tab_changed()
        except Exception:
            pass

    preview.destroyed.connect(preview_destroyed)
    window.destroyed.connect(preview.close)
    preview.exitRequested.connect(preview.close)

    # While the external preview is open, use the resolved route for the
    # metronome rather than the authoring tab's possibly different manual route.
    window._set_metronome_snapshot(metronome_snapshot)

    preview.showNormal()
    preview.setFixedSize(640, 480)
    preview.raise_()
    preview.activateWindow()
    preview.setFocus()

    warning = " · ".join(stream.warnings)
    command_status = []
    if command.approximate_effects:
        command_status.append(
            "approximate COMMAND curves: "
            + ",".join(command.approximate_effects)
        )
    if command.pending_effects:
        command_status.append(
            "COMMAND flags pending projection: "
            + ",".join(command.pending_effects)
        )
    if command_status:
        warning = " · ".join(filter(None, (warning, *command_status)))
    window.statusBar().showMessage(
        f"Opened external gameplay preview ({len(stream.events)} events)"
        + (f" · {warning}" if warning else ""),
        8000,
    )

def _sync_external_previews(window, audio_ms: int):
    chart_ms = window.audio_alignment.audio_to_chart(float(audio_ms))
    for preview in tuple(getattr(window, "phase10_preview_windows", ())):
        if preview is not None and hasattr(preview, "set_playback_time"):
            preview.set_playback_time(chart_ms)



def _choose_chart_audio(window):
    initial = str(window.workspace.root) if window.workspace is not None else ""
    selected, _ = QFileDialog.getOpenFileName(
        window,
        "Select chart audio",
        initial,
        "Pump chart audio (*.mp3 *.aud *.a)",
    )
    if selected:
        window._load_audio(Path(selected))


def _install_chart_audio_policy(window):
    # Restrict workspace discovery for this editor session without changing the
    # generic core module on disk. WAV remains valid only for the metronome path.
    try:
        import stepnx.workspace.folder as folder_module

        folder_module.AUDIO_SUFFIXES = frozenset({".A", ".AUD", ".MP3"})
    except Exception:
        pass

    original_transport_load = window.audio_transport.load

    def transport_load(self_transport, path):
        _stop_silent_transport(window)
        if path is None:
            return original_transport_load(None)
        source = Path(path)
        if source.suffix.casefold() != ".a":
            return original_transport_load(source)
        # Existing AudioTransport knows how to decode ENC2 .AUD.  Stage the .A
        # bytes under that extension so the same validated decoder path is used.
        fd, alias_name = tempfile.mkstemp(prefix="stepnx-audio-a-", suffix=".aud")
        os.close(fd)
        alias = Path(alias_name)
        try:
            alias.write_bytes(source.read_bytes())
            return original_transport_load(alias)
        finally:
            try:
                alias.unlink()
            except OSError:
                pass

    window.audio_transport.load = MethodType(transport_load, window.audio_transport)

    original_load_audio = window._load_audio

    def load_audio_wrapped(self, path):
        source = Path(path)
        if source.suffix.casefold() not in _ALLOWED_CHART_AUDIO:
            QMessageBox.information(
                self,
                "Unsupported chart audio",
                "StepNX chart audio accepts MP3 and the game's encrypted MP3 "
                "containers (.AUD/.A). PCM/WAV is reserved for the metronome.",
            )
            return
        return original_load_audio(source)

    window._load_audio = MethodType(load_audio_wrapped, window)

    audio_menu = next(
        (
            menu
            for menu in window.menuBar().findChildren(type(window.structure_menu))
            if menu.title().replace("&", "") == "Audio"
        ),
        None,
    )
    if audio_menu is not None:
        for action in audio_menu.actions():
            if action.text().replace("&", "").startswith("Select audio"):
                try:
                    action.triggered.disconnect()
                except Exception:
                    pass
                action.triggered.connect(lambda: _choose_chart_audio(window))
                break


def _set_brain_combo_value(window, value: int) -> None:
    combo = getattr(window, "phase10_brain_code", None)
    if combo is None:
        return
    value = int(value)
    combo.blockSignals(True)
    try:
        # Remove a previous temporary advanced-value entry.
        for index in range(combo.count() - 1, -1, -1):
            data = combo.itemData(index)
            if data is not None and int(data) not in _BASIC_BRAIN_CODES:
                combo.removeItem(index)
        index = combo.findData(value)
        if index < 0:
            combo.addItem(f"{value:02d} — Raw (advanced)", value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)
    finally:
        combo.blockSignals(False)


def _advanced_note_raw_fields(window) -> None:
    dialog = QDialog(window)
    dialog.setWindowTitle("Advanced note raw fields")
    layout = QVBoxLayout(dialog)

    explanation = QLabel(
        "Source Slot is raw[3] bits 7..6. NXA overwrites it for REGISTER "
        "Tap/Hold notes (group 0, or payload14 % 3 with Multibank) and "
        "forces REGISTER Item/Division to group 3. Row-null markers can "
        "consume the source value.\n\n"
        "Brain Code is raw[3] bits 0..5. Basic authoring exposes only "
        "0, 1, 6 and 7; use this dialog for every other raw value.",
        dialog,
    )
    explanation.setWordWrap(True)
    layout.addWidget(explanation)

    grid = QGridLayout()
    grid.addWidget(QLabel("Source Slot:", dialog), 0, 0)
    slot = QSpinBox(dialog)
    slot.setRange(0, 3)
    slot.setValue(_selected_player_slot(window))
    grid.addWidget(slot, 0, 1)

    grid.addWidget(QLabel("Brain Code (raw 0..63):", dialog), 1, 0)
    brain = QSpinBox(dialog)
    brain.setRange(0, 63)
    brain.setValue(_selected_brain_code(window))
    grid.addWidget(brain, 1, 1)
    layout.addLayout(grid)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        dialog,
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    window.phase10_source_slot_value = int(slot.value())
    window.phase10_brain_code_value = int(brain.value())
    _set_brain_combo_value(window, window.phase10_brain_code_value)
    window.statusBar().showMessage(
        f"Advanced raw fields: Source Slot {window.phase10_source_slot_value}, "
        f"Brain Code {window.phase10_brain_code_value:02d}",
        5000,
    )


def _silent_transport_position(window) -> int:
    position = int(getattr(window, "phase10_silent_anchor_ms", 0))
    clock = getattr(window, "phase10_silent_clock", None)
    if (
        getattr(window, "phase10_silent_playing", False)
        and clock is not None
        and clock.isValid()
    ):
        position += int(clock.elapsed())
    return max(0, position)


def _stop_silent_transport(window) -> None:
    if not getattr(window, "phase10_silent_playing", False):
        return
    position = _silent_transport_position(window)
    window.phase10_silent_anchor_ms = position
    window.phase10_silent_playing = False
    timer = getattr(window, "phase10_silent_timer", None)
    if timer is not None:
        timer.stop()
    window.audio_transport.positionChanged.emit(position)
    window.audio_transport.playbackChanged.emit(False)


def _phase10_toggle_playback(self) -> None:
    # Real chart audio uses QMediaPlayer. Without chart audio, keep the exact
    # same chart/preview transport semantics on a monotonic silent clock.
    if getattr(self, "phase10_silent_playing", False):
        _stop_silent_transport(self)
        return

    source = self.audio_transport.player.source()
    if not source.isEmpty():
        return self.phase10_original_toggle_audio_playback()

    chart_time = self._selected_chart_time()
    if chart_time is None:
        widget = self.tabs.currentWidget()
        if hasattr(widget, "chart_time_at_viewport_beat"):
            chart_time = widget.chart_time_at_viewport_beat()
    if chart_time is not None:
        self.phase10_silent_anchor_ms = max(
            0, round(self.audio_alignment.chart_to_audio(chart_time))
        )

    if self.audio_position.maximum() <= 0:
        # Keep the existing UI slider usable as the shared position store even
        # without a media duration. This also prevents Pause from snapping the
        # timeline back to zero when the base playbackChanged handler reads it.
        self.audio_position.setRange(0, 2_147_483_647)
    self.phase10_silent_clock.restart()
    self.phase10_silent_playing = True
    self.audio_transport.playbackChanged.emit(True)
    self.audio_transport.positionChanged.emit(self.phase10_silent_anchor_ms)
    self.phase10_silent_timer.start()


def _install_space_transport(window) -> None:
    window.phase10_original_toggle_audio_playback = window._toggle_audio_playback
    window.phase10_silent_anchor_ms = 0
    window.phase10_silent_playing = False
    window.phase10_silent_clock = QElapsedTimer()
    timer = QTimer(window)
    timer.setInterval(16)
    timer.timeout.connect(
        lambda: window.audio_transport.positionChanged.emit(
            _silent_transport_position(window)
        )
        if window.phase10_silent_playing
        else None
    )
    window.phase10_silent_timer = timer
    window._phase10_toggle_playback = MethodType(_phase10_toggle_playback, window)
    window._toggle_audio_playback = window._phase10_toggle_playback

    try:
        window.audio_play.clicked.disconnect()
    except (RuntimeError, TypeError):
        pass
    window.audio_play.clicked.connect(lambda *_: window._phase10_toggle_playback())

    shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), window)
    shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
    shortcut.activated.connect(window._phase10_toggle_playback)
    window.phase10_space_shortcut = shortcut


def install_phase10(window) -> None:
    if getattr(window, "_phase10_installed", False):
        return
    window._phase10_installed = True
    window.phase10_show_advanced_timing = False
    window.phase10_preview_windows = []
    window.phase10_raw_override = None
    window.phase10_source_slot_value = 0
    window.phase10_brain_code_value = 0
    window._phase10_click = MethodType(_phase10_click, window)
    window._phase10_hold = MethodType(_phase10_hold, window)
    window._phase10_drag_preview_allowed = MethodType(
        _phase10_drag_preview_allowed, window
    )
    window._phase10_context_action = MethodType(_phase10_context_action, window)
    window._phase10_timing_context = MethodType(_phase10_timing_context, window)
    window._apply_tool_to_selection = MethodType(
        _phase10_apply_tool_to_selection, window
    )
    window._phase10_update_selection_status = MethodType(
        _update_selection_status, window
    )

    # Toggle is the new default, while the old Tap remains available as an
    # explicit overwrite tool.  Both share Tap's enum value so the untouched
    # base application continues to understand the combo data.
    if window.tool_combo.findText("Toggle") < 0:
        window.tool_combo.insertItem(0, "Toggle", NoteTool.TAP.value)
    window.tool_combo.setCurrentIndex(window.tool_combo.findText("Toggle"))

    # Edit > Show advanced Split timing.  Reuse an existing action from
    # the recovered base when present and delete duplicates instead of stacking
    # another identical menu item on every adapter layer.
    edit_menu = next(
        (
            menu
            for menu in window.menuBar().findChildren(type(window.structure_menu))
            if menu.title().replace("&", "") == "Edit"
        ),
        None,
    )
    if edit_menu is not None:
        candidates = [
            action
            for action in edit_menu.actions()
            if action.text().replace("&", "").strip().casefold()
            == "show advanced split timing"
        ]
        # Replace legacy/duplicate actions instead of blanket-disconnecting
        # toggled(bool). PySide 6.11 warns when disconnect(None) is attempted.
        for candidate in candidates:
            edit_menu.removeAction(candidate)
        action = edit_menu.addAction("Show advanced Split timing")
        action.setCheckable(True)
        action.setChecked(False)
        action.toggled.connect(
            lambda checked: setattr(
                window, "phase10_show_advanced_timing", bool(checked)
            )
        )
        window.phase10_advanced_timing_action = action

    # Preserve the base picker beside Bank / ID, but make its purpose explicit:
    # named semantic types.  The separate Phase-10 Visual button previews the
    # real atlas image, including NXA-Patched SPECIAL.PNG.
    note_toolbar = next(
        (
            bar
            for bar in window.findChildren(QToolBar)
            if bar.windowTitle() == "Note tools"
        ),
        None,
    )
    if note_toolbar is not None:
        existing_buttons = [
            button
            for button in (
                *note_toolbar.findChildren(QPushButton),
                *note_toolbar.findChildren(QToolButton),
            )
            if button.text().strip().casefold().startswith("visual")
            or button.text().strip().casefold().startswith("type")
            or button.text().strip().casefold().startswith("special")
        ]
        type_button = existing_buttons[0] if existing_buttons else None
        if type_button is not None:
            type_button.setText("Type")
            try:
                type_button.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            type_button.clicked.connect(lambda: _type_picker(window))
            window.phase10_type_button = type_button

        # Reuse the legacy second Visual button when present. This removes the
        # obsolete DIVISION/0.PNG picker instead of accumulating a third button.
        if len(existing_buttons) >= 2:
            special = existing_buttons[1]
            special.setText("Special")
            try:
                special.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            special.clicked.connect(lambda: _special_picker(window))
            for obsolete_button in existing_buttons[2:]:
                obsolete_button.hide()
                obsolete_button.setEnabled(False)
        else:
            special = QPushButton("Special", window)
            special.clicked.connect(lambda: _special_picker(window))
            note_toolbar.addWidget(special)
        window.phase10_special_button = special

        note_toolbar.addSeparator()
        note_toolbar.addWidget(QLabel("Brain Code: "))
        brain_code = QComboBox(window)
        for value in _BASIC_BRAIN_CODES:
            brain_code.addItem(f"{value:02d} — {_BRAIN_CODE_LABELS[value]}", value)
        brain_code.setCurrentIndex(0)
        brain_code.setToolTip(
            "Basic raw[3] low-6 authoring: 00 none, 01 renderer/context, "
            "06 incorrect/X, 07 correct/O. Other 0..63 values are available "
            "through Advanced…"
        )
        brain_code.currentIndexChanged.connect(
            lambda *_: setattr(
                window,
                "phase10_brain_code_value",
                int(brain_code.currentData()) if brain_code.currentData() is not None else 0,
            )
        )
        note_toolbar.addWidget(brain_code)
        window.phase10_brain_code = brain_code

        advanced_raw = QPushButton("Advanced…", window)
        advanced_raw.setToolTip(
            "Edit Source Slot (raw[3] bits 7..6) and uncommon Brain Code values."
        )
        advanced_raw.clicked.connect(lambda: _advanced_note_raw_fields(window))
        note_toolbar.addWidget(advanced_raw)
        window.phase10_advanced_raw_button = advanced_raw

        def refresh_pickers(*_):
            tool = NoteTool(window.tool_combo.currentData())
            typed = tool in (NoteTool.ITEM, NoteTool.DIVISION)
            if type_button is not None:
                type_button.setEnabled(typed)
            special.setVisible(_patched_profile(window))
            special.setEnabled(_patched_profile(window))

        window.tool_combo.currentIndexChanged.connect(
            lambda *_: _clear_raw_override(window)
        )
        window.tool_value.valueChanged.connect(
            lambda *_: _clear_raw_override(window)
        )
        window.tool_combo.currentIndexChanged.connect(refresh_pickers)
        for profile_action in getattr(window, "profile_actions", {}).values():
            profile_action.toggled.connect(refresh_pickers)
        refresh_pickers()

    # Selection inspector derived from nx_editor-v61a's compact status line.
    # A permanent widget is used so transient operation messages can still use
    # QStatusBar.showMessage independently.
    selection_status = QLabel("Ready", window)
    selection_status.setMinimumWidth(420)
    window.statusBar().addPermanentWidget(selection_status, 1)
    window.phase10_selection_status = selection_status

    # Transport toolbar edits the chart anchor.  Moving it shifts every Block
    # Start Time by the same delta and shifts first-Block Offset / Delay too.
    audio_toolbar = next(
        (
            bar
            for bar in window.findChildren(QToolBar)
            if bar.windowTitle() == "Audio transport"
        ),
        None,
    )
    if audio_toolbar is not None:
        for label in audio_toolbar.findChildren(QLabel):
            if label.text().strip().lower().startswith("offset ms"):
                label.hide()
        window.audio_offset.hide()
        audio_toolbar.addWidget(QLabel("Chart Start Time ms: "))
        start = QDoubleSpinBox(window)
        start.setRange(-1_000_000_000.0, 1_000_000_000.0)
        start.setDecimals(4)
        start.setKeyboardTracking(False)
        start.valueChanged.connect(lambda value: _set_first_start_time(window, value))
        audio_toolbar.addWidget(start)
        window.phase10_start_time = start
        window.tabs.currentChanged.connect(lambda *_: _refresh_start_time(window))
        _refresh_start_time(window)

    # Audio menu cleanup: remove stale waveform-BPM authoring and collapse
    # duplicate calibration actions into one "Calibrate Audio Offset…" entry.
    audio_menu = next(
        (
            menu
            for menu in window.menuBar().findChildren(type(window.structure_menu))
            if menu.title().replace("&", "") == "Audio"
        ),
        None,
    )
    if audio_menu is not None:
        for action in list(audio_menu.actions()):
            normalized = action.text().replace("&", "").strip().casefold()
            if "estimate bpm" in normalized:
                audio_menu.removeAction(action)

        calibration_actions = [
            action
            for action in audio_menu.actions()
            if "calibrat" in action.text().replace("&", "").strip().casefold()
        ]
        preferred = next(
            (
                action
                for action in calibration_actions
                if "calibrate audio offset"
                in action.text().replace("&", "").strip().casefold()
            ),
            calibration_actions[0] if calibration_actions else None,
        )

        def edit_calibration():
            value, accepted = QInputDialog.getDouble(
                window,
                "Calibrate Audio Offset",
                "Session audio offset (ms):",
                float(window.audio_alignment.offset_ms),
                -1_000_000.0,
                1_000_000.0,
                3,
            )
            if accepted:
                window.audio_offset.setValue(value)

        if preferred is None:
            preferred = audio_menu.addAction("Calibrate Audio Offset…")
            preferred.triggered.connect(edit_calibration)
        else:
            preferred.setText("Calibrate Audio Offset…")
        for duplicate in calibration_actions:
            if duplicate is not preferred:
                audio_menu.removeAction(duplicate)

    _install_space_transport(window)
    _install_chart_audio_policy(window)

    # Replace the Preview QAction itself.  Do not rely on blanket
    # Signal.disconnect(), which PySide can fail to detach reliably and which
    # could invoke the base handler before the external preview callback.
    old_preview_action = window.open_preview_action
    preview_menu = old_preview_action.parent()
    if preview_menu is None or not hasattr(preview_menu, "removeAction"):
        preview_menu = next(
            (
                menu
                for menu in window.menuBar().findChildren(type(window.structure_menu))
                if menu.title().replace("&", "").strip().casefold() == "preview"
            ),
            None,
        )
    if preview_menu is None:
        raise RuntimeError("Preview menu not found while installing Phase 10")

    preview_menu.removeAction(old_preview_action)
    old_preview_action.setShortcut(QKeySequence())
    old_preview_action.setEnabled(False)
    old_preview_action.deleteLater()

    window.open_preview_action = preview_menu.addAction("Open gameplay preview…")
    window.open_preview_action.setShortcut("Ctrl+Shift+P")
    window.open_preview_action.triggered.connect(
        lambda *_: _open_external_gameplay_preview(window)
    )

    window.audio_transport.positionChanged.connect(
        lambda value: _sync_external_previews(window, value)
    )
