from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import (
    Block,
    CompactRows,
    EmptyRow,
    LightmapRow,
    MetadataEntry,
    NoteCell,
    NoteRow,
    NX20Document,
    OverlayRows,
    PackedNoteRow,
    Row,
    Split,
)
from stepnx.core.scalars import RawScalar, RawU32


class Command(Protocol):
    """An immutable document transformation suitable for undo/redo."""

    def apply(self, document: NX20Document) -> NX20Document: ...


def _replace_row(rows, index: int, row: Row):
    if isinstance(rows, (CompactRows, OverlayRows)):
        return rows.with_row(index, row)
    return rows[:index] + (row,) + rows[index + 1 :]


def _replace_block(document: NX20Document, block_id: int, transform) -> NX20Document:
    matches = 0
    new_splits: list[Split] = []
    for split in document.splits:
        new_blocks: list[Block] = []
        split_changed = False
        for block in split.blocks:
            if block.stable_id == block_id:
                block = transform(block)
                matches += 1
                split_changed = True
            new_blocks.append(block)
        new_splits.append(replace(split, blocks=tuple(new_blocks)) if split_changed else split)
    if matches != 1:
        raise ModelInvariantError(f"expected one block with stable ID {block_id}, found {matches}")
    return replace(document, splits=tuple(new_splits))


@dataclass(frozen=True, slots=True)
class SetMetadataValue:
    entry_id: int
    value: RawU32

    @classmethod
    def from_int(cls, entry_id: int, value: int) -> SetMetadataValue:
        return cls(entry_id, RawU32.from_value(value))

    def apply(self, document: NX20Document) -> NX20Document:
        matches = 0

        def edit(entries: tuple[MetadataEntry, ...]) -> tuple[MetadataEntry, ...]:
            nonlocal matches
            result = []
            for entry in entries:
                if entry.stable_id == self.entry_id:
                    entry = replace(entry, value=replace(self.value, span=None))
                    matches += 1
                result.append(entry)
            return tuple(result)

        header = edit(document.header_metadata)
        splits: list[Split] = []
        for split in document.splits:
            metadata = edit(split.metadata)
            blocks: list[Block] = []
            for block in split.blocks:
                divisions = edit(block.divisions)
                blocks.append(replace(block, divisions=divisions) if divisions != block.divisions else block)
            if metadata != split.metadata or tuple(blocks) != split.blocks:
                split = replace(split, metadata=metadata, blocks=tuple(blocks))
            splits.append(split)
        if matches != 1:
            raise ModelInvariantError(
                f"expected one metadata entry with stable ID {self.entry_id}, found {matches}"
            )
        return replace(document, header_metadata=header, splits=tuple(splits))


_BLOCK_FIELDS = {
    "start_time",
    "bpm",
    "scroll",
    "offset_or_delay",
    "speed_or_freeze",
    "beat_split",
    "beat_measure",
    "smooth_speed",
    "raw_flag",
}


@dataclass(frozen=True, slots=True)
class SetBlockField:
    block_id: int
    field: str
    value: RawScalar

    def apply(self, document: NX20Document) -> NX20Document:
        if self.field not in _BLOCK_FIELDS:
            raise ModelInvariantError(f"unsupported editable block field: {self.field}")

        def transform(block: Block) -> Block:
            current = getattr(block, self.field)
            if type(current) is not type(self.value):
                raise ModelInvariantError(
                    f"block field {self.field} requires {type(current).__name__}, "
                    f"not {type(self.value).__name__}"
                )
            return replace(block, **{self.field: replace(self.value, span=None)})

        return _replace_block(document, self.block_id, transform)


def _rich_note_row(row: NoteRow | PackedNoteRow) -> NoteRow:
    if isinstance(row, NoteRow):
        return row
    return NoteRow(row.stable_id, row.cells, row.span)


@dataclass(frozen=True, slots=True)
class SetNoteCellRaw:
    cell_id: int
    raw: bytes

    def __post_init__(self) -> None:
        if len(self.raw) != 4:
            raise ValueError("an NX20 note cell edit requires exactly four bytes")

    def apply(self, document: NX20Document) -> NX20Document:
        matches = 0
        splits: list[Split] = []
        for split in document.splits:
            blocks: list[Block] = []
            split_changed = False
            for block in split.blocks:
                rows = block.rows
                edited_rows = rows
                for row_index, candidate in enumerate(rows):
                    if not isinstance(candidate, (NoteRow, PackedNoteRow)):
                        continue
                    if isinstance(candidate, PackedNoteRow) and not (
                        candidate.first_cell_id
                        <= self.cell_id
                        < candidate.first_cell_id + candidate.cell_count
                    ):
                        continue
                    if isinstance(candidate, NoteRow) and not any(
                        cell.stable_id == self.cell_id for cell in candidate.cells
                    ):
                        continue
                    row = _rich_note_row(candidate)
                    cells = list(row.cells)
                    for cell_index, cell in enumerate(cells):
                        if cell.stable_id == self.cell_id:
                            cells[cell_index] = NoteCell(cell.stable_id, self.raw, None)
                            matches += 1
                    if tuple(cells) != row.cells:
                        edited_rows = _replace_row(edited_rows, row_index, replace(row, cells=tuple(cells)))
                if edited_rows is not rows:
                    block = replace(block, rows=edited_rows)
                    split_changed = True
                blocks.append(block)
            splits.append(replace(split, blocks=tuple(blocks)) if split_changed else split)
        if matches != 1:
            raise ModelInvariantError(
                f"expected one note cell with stable ID {self.cell_id}, found {matches}"
            )
        return replace(document, splits=tuple(splits))


@dataclass(frozen=True, slots=True)
class SetRowRaw:
    row_id: int
    raw: bytes

    def apply(self, document: NX20Document) -> NX20Document:
        matches = 0

        def transform(block: Block) -> Block:
            nonlocal matches
            rows = block.rows
            edited_rows = rows
            for index, row in enumerate(rows):
                if row.stable_id != self.row_id:
                    continue
                matches += 1
                if isinstance(row, EmptyRow):
                    replacement: Row = EmptyRow(row.stable_id, self.raw, None)
                elif isinstance(row, LightmapRow):
                    replacement = LightmapRow(row.stable_id, self.raw, None)
                else:
                    rich = _rich_note_row(row)
                    expected = len(rich.cells) * 4
                    if len(self.raw) != expected:
                        raise ModelInvariantError(
                            f"row {self.row_id} requires {expected} bytes, got {len(self.raw)}"
                        )
                    cells = tuple(
                        NoteCell(cell.stable_id, self.raw[index * 4 : index * 4 + 4], None)
                        for index, cell in enumerate(rich.cells)
                    )
                    replacement = replace(rich, cells=cells, span=None)
                edited_rows = _replace_row(edited_rows, index, replacement)
            return replace(block, rows=edited_rows) if edited_rows is not rows else block

        result = document
        for split in document.splits:
            for block in split.blocks:
                if any(row.stable_id == self.row_id for row in block.rows):
                    result = _replace_block(result, block.stable_id, transform)
        if matches != 1:
            raise ModelInvariantError(f"expected one row with stable ID {self.row_id}, found {matches}")
        return result


class CommandStack:
    """In-memory snapshot history for immutable NX20 documents."""

    def __init__(self, document: NX20Document) -> None:
        self._current = document
        self._undo: list[NX20Document] = []
        self._redo: list[NX20Document] = []

    @property
    def current(self) -> NX20Document:
        return self._current

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def execute(self, command: Command) -> NX20Document:
        updated = command.apply(self._current)
        self._undo.append(self._current)
        self._current = updated
        self._redo.clear()
        return updated

    def undo(self) -> NX20Document:
        if not self._undo:
            raise ModelInvariantError("nothing to undo")
        self._redo.append(self._current)
        self._current = self._undo.pop()
        return self._current

    def redo(self) -> NX20Document:
        if not self._redo:
            raise ModelInvariantError("nothing to redo")
        self._undo.append(self._current)
        self._current = self._redo.pop()
        return self._current
