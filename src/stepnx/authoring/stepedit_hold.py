"""Pure, lossless Hold gesture planner for the opt-in STEPEdit Qt surface.

The active NX20 Block remains the authority for each cell's original bytes.
The planner never writes a chart: it emits a single atomic SetNotesAt batch.
"""
from __future__ import annotations

from collections.abc import Callable

from stepnx.authoring.selection import CellTarget
from stepnx.core.commands import NoteEdit
from stepnx.core.model import EmptyRow, LightmapRow, NoteRow, PackedNoteRow


_EMPTY = b"\x00\x00\x00\x00"
_HEAD, _BODY, _TAIL = 0x7, 0xB, 0xF
_TYPES = frozenset((_HEAD, _BODY, _TAIL))


class HoldGestureError(ValueError):
    """Cannot apply a Hold gesture without replacing existing chart data."""


def _cell(rows, index: int, lane: int) -> bytes:
    row = rows[index]
    if isinstance(row, EmptyRow):
        return _EMPTY
    if isinstance(row, PackedNoteRow):
        return row.cell(lane).raw
    if isinstance(row, NoteRow):
        return row.cells[lane].raw
    if isinstance(row, LightmapRow):
        raise HoldGestureError("Lightmap rows do not contain Holds")
    raise HoldGestureError("unknown row encoding")


def plan_hold_creation(block, lane: int, start_index: int, end_index: int,
                       raw_for_type: Callable[[int], bytes]) -> tuple[NoteEdit, ...]:
    """Head at lowest row index, tail at highest; reject ANY occupied bytes."""
    rows = block.rows
    if not 0 <= start_index < len(rows) or not 0 <= end_index < len(rows):
        raise HoldGestureError("Hold endpoint is outside the selected Block")
    if start_index == end_index:
        raise HoldGestureError("Hold requires at least two rows")
    lo, hi = sorted((start_index, end_index))
    for i in range(lo, hi + 1):
        if _cell(rows, i, lane) != _EMPTY:
            raise HoldGestureError(
                "Hold requires completely empty cells throughout its span"
            )
    edits = []
    for i in range(lo, hi + 1):
        part = _HEAD if i == lo else _TAIL if i == hi else _BODY
        raw = raw_for_type(part)
        if len(raw) != 4 or (raw[0] & 0x0F) != part:
            raise HoldGestureError(f"invalid authored Hold part 0x{part:X}")
        edits.append(NoteEdit(rows[i].stable_id, lane, raw))
    return tuple(edits)


def plan_hold_erasure(block, lane: int, row_index: int) -> tuple[NoteEdit, ...]:
    """Erase exactly one complete contiguous Hold, never adjacent notes."""
    rows = block.rows
    if not 0 <= row_index < len(rows):
        raise HoldGestureError("Hold cell is outside the selected Block")
    kind = _cell(rows, row_index, lane)[0] & 0x0F
    if kind not in _TYPES:
        raise HoldGestureError("selected cell is not part of a Hold")
    lo = hi = row_index
    if kind != _HEAD:
        while lo > 0:
            previous = _cell(rows, lo - 1, lane)[0] & 0x0F
            if previous == _HEAD:
                lo -= 1
                break
            if previous != _BODY:
                break
            lo -= 1
    if kind != _TAIL:
        while hi + 1 < len(rows):
            following = _cell(rows, hi + 1, lane)[0] & 0x0F
            if following == _TAIL:
                hi += 1
                break
            if following != _BODY:
                break
            hi += 1
    if lo == hi or (_cell(rows, lo, lane)[0] & 0x0F) != _HEAD or (
        _cell(rows, hi, lane)[0] & 0x0F
    ) != _TAIL:
        raise HoldGestureError("incomplete Hold: preserving unknown source data")
    if any((_cell(rows, i, lane)[0] & 0x0F) != _BODY for i in range(lo + 1, hi)):
        raise HoldGestureError("unexpected note in Hold body")
    return tuple(NoteEdit(rows[i].stable_id, lane, _EMPTY) for i in range(lo, hi + 1))
