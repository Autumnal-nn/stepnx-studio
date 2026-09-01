from __future__ import annotations

from enum import Enum, IntEnum


class NoteTool(str, Enum):
    SELECT = "select"
    TAP = "tap"
    HOLD_HEAD = "hold-head"
    HOLD_BODY = "hold-body"
    HOLD_TAIL = "hold-tail"
    ITEM = "item"
    DIVISION = "division"
    ERASE = "erase"


class NoteFunction(str, Enum):
    """StepEdit-compatible meanings of the two functional bits in raw[0]."""

    NORMAL = "normal"
    BONUS = "bonus"
    GHOST = "ghost"


class NoteVisibility(IntEnum):
    INVISIBLE = 0
    APPEAR = 1
    VANISH = 2
    VISIBLE = 3
    RAW_4 = 4
    RAW_5 = 5


_FUNCTION_BITS = {
    NoteFunction.NORMAL: 0x40,
    NoteFunction.BONUS: 0x60,
    NoteFunction.GHOST: 0x20,
}


_NOTE_TYPES = {
    NoteTool.TAP: 0x3,
    NoteTool.HOLD_HEAD: 0x7,
    NoteTool.HOLD_BODY: 0xB,
    NoteTool.HOLD_TAIL: 0xF,
}


def apply_note_modifiers(
    raw: bytes,
    functionality: NoteFunction,
    visibility: NoteVisibility,
) -> bytes:
    """Change orthogonal note flags while preserving type, bank, slot, and BS.

    RAW_4 and RAW_5 are deliberate lossless aliases observed in official NX20
    charts. Their runtime behavior is not named here because it is not proven.
    """
    if len(raw) != 4:
        raise ValueError("an NX20 note requires exactly four bytes")
    if raw[0] & 0x0F == 0:
        raise ValueError("visibility/function flags cannot be applied to an empty cell")
    modified = bytearray(raw)
    modified[0] = (modified[0] & ~0x60) | _FUNCTION_BITS[functionality]
    modified[1] = (modified[1] & ~0x07) | int(visibility)
    return bytes(modified)


def note_tool_raw(
    tool: NoteTool,
    value: int = 0,
    functionality: NoteFunction = NoteFunction.NORMAL,
    visibility: NoteVisibility = NoteVisibility.VISIBLE,
) -> bytes:
    """Build a conservative four-byte NX20 preset for a placement tool.

    The value byte is a noteskin bank for taps/holds and an ID for items or
    divisions. Function and visibility are explicit; slot and Brain Shower
    remain separate raw-preserving edits.
    """

    if not 0 <= value <= 0xFF:
        raise ValueError("note tool value must fit in one byte")
    if tool is NoteTool.SELECT:
        raise ValueError("the select tool does not produce note bytes")
    if tool is NoteTool.ERASE:
        return b"\x00\x00\x00\x00"
    if tool in _NOTE_TYPES:
        return apply_note_modifiers(
            bytes((0x40 | _NOTE_TYPES[tool], 0x03, value, 0x00)),
            functionality,
            visibility,
        )
    if tool is NoteTool.ITEM:
        return apply_note_modifiers(
            bytes((0x41, 0x03, value, 0x00)), functionality, visibility
        )
    if tool is NoteTool.DIVISION:
        return bytes((0x02, 0x03, value, 0x00))
    raise ValueError(f"unsupported note tool: {tool}")