from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, TypeVar

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


def _replace_split(document: NX20Document, split_id: int, transform) -> NX20Document:
    matches = 0
    splits = []
    for split in document.splits:
        if split.stable_id == split_id:
            split = transform(split)
            matches += 1
        splits.append(split)
    if matches != 1:
        raise ModelInvariantError(f"expected one split with stable ID {split_id}, found {matches}")
    return replace(document, splits=tuple(splits))


@dataclass(slots=True)
class _StableIdAllocator:
    next_value: int

    def take(self) -> int:
        value = self.next_value
        self.next_value += 1
        return value


T = TypeVar("T")


def _insert_before(
    items: tuple[T, ...], item: T, before_id: int | None, label: str
) -> tuple[T, ...]:
    if before_id is None:
        return (*items, item)
    matches = [index for index, candidate in enumerate(items) if candidate.stable_id == before_id]
    if len(matches) != 1:
        raise ModelInvariantError(
            f"expected one {label} anchor with stable ID {before_id}, found {len(matches)}"
        )
    index = matches[0]
    return (*items[:index], item, *items[index:])


def _remove_by_id(items: tuple[T, ...], stable_id: int, label: str) -> tuple[tuple[T, ...], T]:
    matches = [(index, item) for index, item in enumerate(items) if item.stable_id == stable_id]
    if len(matches) != 1:
        raise ModelInvariantError(
            f"expected one {label} with stable ID {stable_id}, found {len(matches)}"
        )
    index, item = matches[0]
    return (*items[:index], *items[index + 1 :]), item


def _clone_scalar(value: RawScalar) -> RawScalar:
    return replace(value, span=None)


def _clone_metadata(entry: MetadataEntry, ids: _StableIdAllocator) -> MetadataEntry:
    return MetadataEntry(
        stable_id=ids.take(),
        meta_id=replace(entry.meta_id, span=None),
        value=replace(entry.value, span=None),
        span=None,
    )


def _clone_row(row: Row, ids: _StableIdAllocator) -> Row:
    if isinstance(row, EmptyRow):
        return EmptyRow(ids.take(), row.raw, None)
    if isinstance(row, LightmapRow):
        return LightmapRow(ids.take(), row.raw_channels, None)
    if isinstance(row, PackedNoteRow):
        first_cell_id = ids.next_value
        ids.next_value += row.cell_count
        return PackedNoteRow(ids.take(), first_cell_id, row.raw_cells, None)
    cells = tuple(NoteCell(ids.take(), cell.raw, None) for cell in row.cells)
    return NoteRow(ids.take(), cells, None)


def _clone_block(block: Block, ids: _StableIdAllocator) -> Block:
    divisions = tuple(_clone_metadata(entry, ids) for entry in block.divisions)
    rows = tuple(_clone_row(row, ids) for row in block.rows)
    return Block(
        stable_id=ids.take(),
        start_time=_clone_scalar(block.start_time),
        bpm=_clone_scalar(block.bpm),
        scroll=_clone_scalar(block.scroll),
        offset_or_delay=_clone_scalar(block.offset_or_delay),
        speed_or_freeze=_clone_scalar(block.speed_or_freeze),
        beat_split=_clone_scalar(block.beat_split),
        beat_measure=_clone_scalar(block.beat_measure),
        smooth_speed=_clone_scalar(block.smooth_speed),
        raw_flag=_clone_scalar(block.raw_flag),
        division_count=_clone_scalar(block.division_count),
        divisions=divisions,
        row_count=_clone_scalar(block.row_count),
        rows=rows,
        span=None,
    )


def _clone_split(split: Split, ids: _StableIdAllocator) -> Split:
    metadata = tuple(_clone_metadata(entry, ids) for entry in split.metadata)
    blocks = tuple(_clone_block(block, ids) for block in split.blocks)
    return Split(
        stable_id=ids.take(),
        raw_select=_clone_scalar(split.raw_select),
        raw_brain=_clone_scalar(split.raw_brain),
        raw_padding=_clone_scalar(split.raw_padding),
        metadata_count=_clone_scalar(split.metadata_count),
        metadata=metadata,
        block_count=_clone_scalar(split.block_count),
        blocks=blocks,
        span=None,
    )


def _replace_metadata_owner(document: NX20Document, owner_id: int, transform) -> NX20Document:
    matches = 0
    if document.stable_id == owner_id:
        matches += 1
        document = replace(document, header_metadata=transform(document.header_metadata))

    splits = []
    for split in document.splits:
        split_changed = False
        if split.stable_id == owner_id:
            matches += 1
            split = replace(split, metadata=transform(split.metadata))
            split_changed = True
        blocks = []
        for block in split.blocks:
            if block.stable_id == owner_id:
                matches += 1
                block = replace(block, divisions=transform(block.divisions))
                split_changed = True
            blocks.append(block)
        if split_changed:
            split = replace(split, blocks=tuple(blocks))
        splits.append(split)
    if matches != 1:
        raise ModelInvariantError(
            f"expected one metadata owner with stable ID {owner_id}, found {matches}"
        )
    return replace(document, splits=tuple(splits))


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
                blocks.append(
                    replace(block, divisions=divisions)
                    if divisions != block.divisions
                    else block
                )
            if metadata != split.metadata or tuple(blocks) != split.blocks:
                split = replace(split, metadata=metadata, blocks=tuple(blocks))
            splits.append(split)
        if matches != 1:
            raise ModelInvariantError(
                f"expected one metadata entry with stable ID {self.entry_id}, found {matches}"
            )
        return replace(document, header_metadata=header, splits=tuple(splits))


@dataclass(frozen=True, slots=True)
class InsertMetadata:
    """Insert metadata before an optional stable-ID anchor owned by a document, split, or block."""

    owner_id: int
    meta_id: RawU32
    value: RawU32
    before_entry_id: int | None = None

    @classmethod
    def from_ints(
        cls,
        owner_id: int,
        meta_id: int,
        value: int,
        *,
        before_entry_id: int | None = None,
    ) -> InsertMetadata:
        return cls(
            owner_id,
            RawU32.from_value(meta_id),
            RawU32.from_value(value),
            before_entry_id,
        )

    def apply(self, document: NX20Document) -> NX20Document:
        ids = _StableIdAllocator(document.next_stable_id)
        entry = MetadataEntry(
            stable_id=ids.take(),
            meta_id=replace(self.meta_id, span=None),
            value=replace(self.value, span=None),
            span=None,
        )
        updated = _replace_metadata_owner(
            document,
            self.owner_id,
            lambda entries: _insert_before(
                entries, entry, self.before_entry_id, "metadata entry"
            ),
        )
        return replace(updated, next_stable_id=ids.next_value)


@dataclass(frozen=True, slots=True)
class RemoveMetadata:
    entry_id: int

    def apply(self, document: NX20Document) -> NX20Document:
        matches = 0

        def remove(entries: tuple[MetadataEntry, ...]) -> tuple[MetadataEntry, ...]:
            nonlocal matches
            retained = tuple(entry for entry in entries if entry.stable_id != self.entry_id)
            matches += len(entries) - len(retained)
            return retained

        header = remove(document.header_metadata)
        splits = []
        for split in document.splits:
            metadata = remove(split.metadata)
            blocks = []
            for block in split.blocks:
                divisions = remove(block.divisions)
                blocks.append(
                    replace(block, divisions=divisions)
                    if divisions != block.divisions
                    else block
                )
            split_blocks = tuple(blocks)
            if metadata != split.metadata or split_blocks != split.blocks:
                split = replace(split, metadata=metadata, blocks=split_blocks)
            splits.append(split)
        if matches != 1:
            raise ModelInvariantError(
                f"expected one metadata entry with stable ID {self.entry_id}, found {matches}"
            )
        return replace(document, header_metadata=header, splits=tuple(splits))


@dataclass(frozen=True, slots=True)
class MoveMetadata:
    entry_id: int
    before_entry_id: int | None = None

    def apply(self, document: NX20Document) -> NX20Document:
        if self.before_entry_id == self.entry_id:
            return document
        matches = 0

        def move(entries: tuple[MetadataEntry, ...]) -> tuple[MetadataEntry, ...]:
            nonlocal matches
            if not any(entry.stable_id == self.entry_id for entry in entries):
                return entries
            matches += 1
            retained, entry = _remove_by_id(entries, self.entry_id, "metadata entry")
            return _insert_before(retained, entry, self.before_entry_id, "metadata entry")

        header = move(document.header_metadata)
        splits = []
        for split in document.splits:
            metadata = move(split.metadata)
            blocks = []
            for block in split.blocks:
                divisions = move(block.divisions)
                blocks.append(
                    replace(block, divisions=divisions)
                    if divisions != block.divisions
                    else block
                )
            split_blocks = tuple(blocks)
            if metadata != split.metadata or split_blocks != split.blocks:
                split = replace(split, metadata=metadata, blocks=split_blocks)
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


@dataclass(frozen=True, slots=True)
class SetBlockFields:
    """Replace several scalar fields on one Block as one undoable operation."""

    block_id: int
    values: tuple[tuple[str, RawScalar], ...]

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("a Block field edit cannot be empty")
        fields = [field for field, _ in self.values]
        if len(fields) != len(set(fields)):
            raise ValueError("a Block field edit cannot contain duplicate fields")

    def apply(self, document: NX20Document) -> NX20Document:
        def transform(block: Block) -> Block:
            replacements = {}
            for field, value in self.values:
                if field not in _BLOCK_FIELDS:
                    raise ModelInvariantError(
                        f"unsupported editable block field: {field}"
                    )
                current = getattr(block, field)
                if type(current) is not type(value):
                    raise ModelInvariantError(
                        f"block field {field} requires {type(current).__name__}, "
                        f"not {type(value).__name__}"
                    )
                replacements[field] = replace(value, span=None)
            return replace(block, **replacements)

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
        if self.raw[0] & 0x80:
            raise ValueError("a note cell cannot contain an NX20 empty-row marker")

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
                        edited_rows = _replace_row(
                            edited_rows,
                            row_index,
                            replace(row, cells=tuple(cells)),
                        )
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
class NoteEdit:
    """One lane edit addressed by a stable row ID.

    Row addressing lets the authoring view place the first note on a compact
    empty row, which has no cell IDs yet.  A zero cell clears the lane.
    """

    row_id: int
    lane: int
    raw: bytes

    def __post_init__(self) -> None:
        if self.lane < 0:
            raise ValueError("a note lane cannot be negative")
        if len(self.raw) != 4:
            raise ValueError("an NX20 note edit requires exactly four bytes")
        if self.raw[0] & 0x80:
            raise ValueError("a note cell cannot contain an NX20 empty-row marker")


@dataclass(frozen=True, slots=True)
class SetNotesAt:
    """Apply one or more row/lane note edits as one atomic command."""

    edits: tuple[NoteEdit, ...]

    def __post_init__(self) -> None:
        if not self.edits:
            raise ValueError("a bulk note edit cannot be empty")
        targets = {(edit.row_id, edit.lane) for edit in self.edits}
        if len(targets) != len(self.edits):
            raise ValueError("a bulk note edit cannot target the same cell twice")

    def apply(self, document: NX20Document) -> NX20Document:
        pending_by_row: dict[int, dict[int, bytes]] = {}
        for edit in self.edits:
            pending_by_row.setdefault(edit.row_id, {})[edit.lane] = edit.raw
        matches = 0
        ids = _StableIdAllocator(document.next_stable_id)
        columns = int(document.columns.value)
        splits: list[Split] = []

        for split in document.splits:
            blocks: list[Block] = []
            split_changed = False
            for block in split.blocks:
                rows = block.rows
                edited_rows: list[Row] | None = None
                for row_index, candidate in enumerate(rows):
                    row_edits = pending_by_row.get(candidate.stable_id)
                    if not row_edits:
                        continue
                    if isinstance(candidate, LightmapRow):
                        raise ModelInvariantError("note tools cannot edit a Lightmap row")
                    for lane in row_edits:
                        if lane >= columns:
                            raise ModelInvariantError(
                                f"lane {lane} is outside the document's {columns} columns"
                            )

                    if isinstance(candidate, EmptyRow):
                        if all(raw == b"\x00\x00\x00\x00" for raw in row_edits.values()):
                            matches += len(row_edits)
                            continue
                        cells = [
                            NoteCell(ids.take(), b"\x00\x00\x00\x00", None)
                            for _ in range(columns)
                        ]
                    else:
                        rich = _rich_note_row(candidate)
                        if rich.cell_count != columns:
                            raise ModelInvariantError(
                                f"row {candidate.stable_id} has {rich.cell_count} cells, "
                                f"expected {columns}"
                            )
                        cells = list(rich.cells)

                    for lane, raw in row_edits.items():
                        cell = cells[lane]
                        cells[lane] = NoteCell(cell.stable_id, raw, None)
                        matches += 1

                    if all(cell.raw == b"\x00\x00\x00\x00" for cell in cells):
                        replacement: Row = EmptyRow(
                            candidate.stable_id, b"\x80\x00\x00\x00", None
                        )
                    else:
                        replacement = NoteRow(candidate.stable_id, tuple(cells), None)
                    if edited_rows is None:
                        edited_rows = list(rows)
                    edited_rows[row_index] = replacement

                if edited_rows is not None:
                    block = replace(block, rows=tuple(edited_rows))
                    split_changed = True
                blocks.append(block)
            splits.append(replace(split, blocks=tuple(blocks)) if split_changed else split)

        if matches != len(self.edits):
            raise ModelInvariantError(
                f"expected {len(self.edits)} note-edit targets, found {matches}"
            )
        return replace(
            document,
            splits=tuple(splits),
            next_stable_id=ids.next_value,
        )


@dataclass(frozen=True, slots=True)
class SetNoteAt:
    """Set or clear one lane while preserving the row's stable identity."""

    row_id: int
    lane: int
    raw: bytes

    def apply(self, document: NX20Document) -> NX20Document:
        return SetNotesAt((NoteEdit(self.row_id, self.lane, self.raw),)).apply(document)


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
            raise ModelInvariantError(
                f"expected one row with stable ID {self.row_id}, found {matches}"
            )
        return result


@dataclass(frozen=True, slots=True)
class InsertSplit:
    prototype: Split
    before_split_id: int | None = None

    def apply(self, document: NX20Document) -> NX20Document:
        ids = _StableIdAllocator(document.next_stable_id)
        split = _clone_split(self.prototype, ids)
        splits = _insert_before(document.splits, split, self.before_split_id, "split")
        return replace(document, splits=splits, next_stable_id=ids.next_value)


@dataclass(frozen=True, slots=True)
class RemoveSplit:
    split_id: int

    def apply(self, document: NX20Document) -> NX20Document:
        splits, _ = _remove_by_id(document.splits, self.split_id, "split")
        return replace(document, splits=splits)


@dataclass(frozen=True, slots=True)
class MoveSplit:
    split_id: int
    before_split_id: int | None = None

    def apply(self, document: NX20Document) -> NX20Document:
        if self.before_split_id == self.split_id:
            return document
        splits, split = _remove_by_id(document.splits, self.split_id, "split")
        return replace(
            document,
            splits=_insert_before(splits, split, self.before_split_id, "split"),
        )


@dataclass(frozen=True, slots=True)
class InsertBlock:
    split_id: int
    prototype: Block
    before_block_id: int | None = None

    def apply(self, document: NX20Document) -> NX20Document:
        ids = _StableIdAllocator(document.next_stable_id)
        block = _clone_block(self.prototype, ids)
        updated = _replace_split(
            document,
            self.split_id,
            lambda split: replace(
                split,
                blocks=_insert_before(
                    split.blocks, block, self.before_block_id, "block"
                ),
            ),
        )
        return replace(updated, next_stable_id=ids.next_value)


@dataclass(frozen=True, slots=True)
class RemoveBlock:
    block_id: int

    def apply(self, document: NX20Document) -> NX20Document:
        matches = 0
        splits = []
        for split in document.splits:
            retained = tuple(block for block in split.blocks if block.stable_id != self.block_id)
            matches += len(split.blocks) - len(retained)
            splits.append(replace(split, blocks=retained) if retained != split.blocks else split)
        if matches != 1:
            raise ModelInvariantError(
                f"expected one block with stable ID {self.block_id}, found {matches}"
            )
        return replace(document, splits=tuple(splits))


@dataclass(frozen=True, slots=True)
class MoveBlock:
    block_id: int
    target_split_id: int
    before_block_id: int | None = None

    def apply(self, document: NX20Document) -> NX20Document:
        block_matches = 0
        target_matches = 0
        moving: Block | None = None
        source_split_id: int | None = None
        stripped = []
        for split in document.splits:
            blocks = []
            for block in split.blocks:
                if block.stable_id == self.block_id:
                    block_matches += 1
                    moving = block
                    source_split_id = split.stable_id
                else:
                    blocks.append(block)
            stripped_blocks = tuple(blocks)
            stripped.append(
                replace(split, blocks=stripped_blocks)
                if stripped_blocks != split.blocks
                else split
            )
        if block_matches != 1 or moving is None:
            raise ModelInvariantError(
                f"expected one block with stable ID {self.block_id}, found {block_matches}"
            )
        if self.before_block_id == self.block_id:
            if self.target_split_id == source_split_id:
                return document
            raise ModelInvariantError("a block cannot use itself as an anchor in another split")

        result = []
        for split in stripped:
            if split.stable_id == self.target_split_id:
                target_matches += 1
                split = replace(
                    split,
                    blocks=_insert_before(
                        split.blocks, moving, self.before_block_id, "block"
                    ),
                )
            result.append(split)
        if target_matches != 1:
            raise ModelInvariantError(
                f"expected one target split with stable ID {self.target_split_id}, "
                f"found {target_matches}"
            )
        return replace(document, splits=tuple(result))


@dataclass(frozen=True, slots=True)
class InsertRow:
    block_id: int
    prototype: Row
    before_row_id: int | None = None

    def apply(self, document: NX20Document) -> NX20Document:
        ids = _StableIdAllocator(document.next_stable_id)
        row = _clone_row(self.prototype, ids)

        def insert(block: Block) -> Block:
            rows = tuple(block.rows)
            return replace(
                block,
                rows=_insert_before(rows, row, self.before_row_id, "row"),
            )

        updated = _replace_block(document, self.block_id, insert)
        return replace(updated, next_stable_id=ids.next_value)


@dataclass(frozen=True, slots=True)
class RemoveRow:
    row_id: int

    def apply(self, document: NX20Document) -> NX20Document:
        matches = 0

        def remove(block: Block) -> Block:
            nonlocal matches
            if not any(row.stable_id == self.row_id for row in block.rows):
                return block
            rows = tuple(block.rows)
            retained = tuple(row for row in rows if row.stable_id != self.row_id)
            matches += len(rows) - len(retained)
            return replace(block, rows=retained) if retained != rows else block

        splits = []
        for split in document.splits:
            blocks = tuple(remove(block) for block in split.blocks)
            splits.append(replace(split, blocks=blocks) if blocks != split.blocks else split)
        if matches != 1:
            raise ModelInvariantError(
                f"expected one row with stable ID {self.row_id}, found {matches}"
            )
        return replace(document, splits=tuple(splits))


@dataclass(frozen=True, slots=True)
class MoveRow:
    row_id: int
    target_block_id: int
    before_row_id: int | None = None

    def apply(self, document: NX20Document) -> NX20Document:
        row_matches = 0
        target_matches = 0
        moving: Row | None = None
        source_block_id: int | None = None
        stripped_splits = []
        for split in document.splits:
            blocks = []
            for block in split.blocks:
                if not any(row.stable_id == self.row_id for row in block.rows):
                    blocks.append(block)
                    continue
                rows = tuple(block.rows)
                retained = []
                for row in rows:
                    if row.stable_id == self.row_id:
                        row_matches += 1
                        moving = row
                        source_block_id = block.stable_id
                    else:
                        retained.append(row)
                retained_rows = tuple(retained)
                blocks.append(
                    replace(block, rows=retained_rows) if retained_rows != rows else block
                )
            stripped_blocks = tuple(blocks)
            stripped_splits.append(
                replace(split, blocks=stripped_blocks)
                if stripped_blocks != split.blocks
                else split
            )
        if row_matches != 1 or moving is None:
            raise ModelInvariantError(
                f"expected one row with stable ID {self.row_id}, found {row_matches}"
            )
        if self.before_row_id == self.row_id:
            if self.target_block_id == source_block_id:
                return document
            raise ModelInvariantError("a row cannot use itself as an anchor in another block")

        result = []
        for split in stripped_splits:
            blocks = []
            for block in split.blocks:
                if block.stable_id == self.target_block_id:
                    target_matches += 1
                    block = replace(
                        block,
                        rows=_insert_before(
                            tuple(block.rows), moving, self.before_row_id, "row"
                        ),
                    )
                blocks.append(block)
            result_blocks = tuple(blocks)
            result.append(
                replace(split, blocks=result_blocks)
                if result_blocks != split.blocks
                else split
            )
        if target_matches != 1:
            raise ModelInvariantError(
                f"expected one target block with stable ID {self.target_block_id}, "
                f"found {target_matches}"
            )
        return replace(document, splits=tuple(result))


class CommandStack:
    """In-memory snapshot history for immutable NX20 documents."""

    def __init__(self, document: NX20Document) -> None:
        self._current = document
        self._undo: list[NX20Document] = []
        self._redo: list[NX20Document] = []
        self._coalesce_key: object | None = None

    @property
    def current(self) -> NX20Document:
        return self._current

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def execute(self, command: Command, *, coalesce_key: object | None = None) -> NX20Document:
        updated = command.apply(self._current)
        if coalesce_key is None or coalesce_key != self._coalesce_key:
            self._undo.append(self._current)
        self._current = updated
        self._redo.clear()
        self._coalesce_key = coalesce_key
        return updated

    def finish_coalescing(self) -> None:
        """End the current drag/paint gesture without changing the document."""

        self._coalesce_key = None

    def undo(self) -> NX20Document:
        if not self._undo:
            raise ModelInvariantError("nothing to undo")
        self._redo.append(self._current)
        self._current = self._undo.pop()
        self._coalesce_key = None
        return self._current

    def redo(self) -> NX20Document:
        if not self._redo:
            raise ModelInvariantError("nothing to redo")
        self._undo.append(self._current)
        self._current = self._redo.pop()
        self._coalesce_key = None
        return self._current
