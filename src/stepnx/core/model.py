from __future__ import annotations

import struct
from array import array
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TypeAlias

from stepnx.core.scalars import RawF32, RawU8, RawU16, RawU32, SourceSpan


StableId: TypeAlias = int


class DeploymentRole(str, Enum):
    CHART = "chart"
    LIGHTMAP = "lightmap"
    MISSION = "mission"


class EnvelopeKind(str, Enum):
    NONE = "none"
    SIZED_TRAILER = "sized-trailer"
    OPAQUE_TAIL = "opaque-tail"


@dataclass(frozen=True, slots=True)
class MetadataEntry:
    stable_id: StableId
    meta_id: RawU32
    value: RawU32
    span: SourceSpan | None


@dataclass(frozen=True, slots=True)
class NoteCell:
    stable_id: StableId
    raw: bytes
    span: SourceSpan | None

    def __post_init__(self) -> None:
        if len(self.raw) != 4 or (self.span is not None and self.span.size != 4):
            raise ValueError("an NX20 note cell must occupy exactly four bytes")

    @property
    def note_type(self) -> int:
        return self.raw[0] & 0x0F


@dataclass(frozen=True, slots=True)
class EmptyRow:
    stable_id: StableId
    raw: bytes
    span: SourceSpan | None

    def __post_init__(self) -> None:
        if len(self.raw) != 4 or not (self.raw[0] & 0x80):
            raise ValueError("an empty row must be a four-byte row marker")


@dataclass(frozen=True, slots=True)
class NoteRow:
    stable_id: StableId
    cells: tuple[NoteCell, ...]
    span: SourceSpan | None

    @property
    def cell_count(self) -> int:
        return len(self.cells)


@dataclass(frozen=True, slots=True)
class PackedNoteRow:
    """Unedited note row stored as one byte string.

    Cells remain addressable by stable ID and source span, but their Python
    objects are created only when a caller asks for them.  Edited rows can be
    promoted to :class:`NoteRow`; the writer accepts both representations.
    """

    stable_id: StableId
    first_cell_id: StableId
    raw_cells: bytes
    span: SourceSpan | None

    def __post_init__(self) -> None:
        if not self.raw_cells or len(self.raw_cells) % 4:
            raise ValueError("a packed NX20 row must contain one or more four-byte cells")
        if self.span is not None and self.span.size != len(self.raw_cells):
            raise ValueError("a packed NX20 row span must match its raw cell bytes")

    @property
    def cell_count(self) -> int:
        return len(self.raw_cells) // 4

    def cell(self, index: int) -> NoteCell:
        if not 0 <= index < self.cell_count:
            raise IndexError(index)
        offset = index * 4
        span = None
        if self.span is not None:
            span = SourceSpan(self.span.start + offset, self.span.start + offset + 4)
        return NoteCell(
            stable_id=self.first_cell_id + index,
            raw=self.raw_cells[offset : offset + 4],
            span=span,
        )

    @property
    def cells(self) -> tuple[NoteCell, ...]:
        return tuple(self.cell(index) for index in range(self.cell_count))


@dataclass(frozen=True, slots=True)
class LightmapRow:
    stable_id: StableId
    raw_channels: bytes
    span: SourceSpan | None

    def __post_init__(self) -> None:
        if len(self.raw_channels) != 4 or (self.span is not None and self.span.size != 4):
            raise ValueError("a Lightmap row must occupy exactly four bytes")


Row: TypeAlias = EmptyRow | NoteRow | PackedNoteRow | LightmapRow


class CompactRows(Sequence[Row]):
    """Read-only row table backed by the document's original bytes.

    The table retains offsets and stable IDs in packed numeric arrays.  A row
    object is materialized only while a caller is inspecting it.  Any edit can
    replace this collection, or an individual materialized row, with the rich
    tuple representation.
    """

    __slots__ = (
        "_source",
        "_offsets",
        "_row_ids",
        "_first_cell_ids",
        "_kinds",
        "columns",
        "effective_lightmap",
    )

    EMPTY = 0
    NOTE = 1
    LIGHTMAP = 2

    def __init__(
        self,
        *,
        source: bytes,
        offsets: array,
        row_ids: array,
        first_cell_ids: array,
        kinds: array,
        columns: int,
        effective_lightmap: bool,
    ) -> None:
        count = len(row_ids)
        if len(offsets) != count + 1:
            raise ValueError("compact row offsets need one terminal entry")
        if len(first_cell_ids) != count or len(kinds) != count:
            raise ValueError("compact row indexes must have equal lengths")
        if offsets and (offsets[0] < 0 or offsets[-1] > len(source)):
            raise ValueError("compact row offsets fall outside the source")
        self._source = source
        self._offsets = offsets
        self._row_ids = row_ids
        self._first_cell_ids = first_cell_ids
        self._kinds = kinds
        self.columns = columns
        self.effective_lightmap = effective_lightmap

    def __len__(self) -> int:
        return len(self._row_ids)

    def __getitem__(self, index: int | slice) -> Row | tuple[Row, ...]:
        if isinstance(index, slice):
            return tuple(self[position] for position in range(*index.indices(len(self))))
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)

        start = int(self._offsets[index])
        end = int(self._offsets[index + 1])
        span = SourceSpan(start, end)
        raw = self._source[start:end]
        stable_id = int(self._row_ids[index])
        kind = int(self._kinds[index])
        if kind == self.EMPTY:
            return EmptyRow(stable_id, raw, span)
        if kind == self.LIGHTMAP:
            return LightmapRow(stable_id, raw, span)
        if kind == self.NOTE:
            return PackedNoteRow(
                stable_id=stable_id,
                first_cell_id=int(self._first_cell_ids[index]),
                raw_cells=raw,
                span=span,
            )
        raise ValueError(f"unknown compact row kind {kind}")

    def __iter__(self) -> Iterator[Row]:
        for index in range(len(self)):
            yield self[index]

    @property
    def raw_bytes(self) -> bytes:
        if not self._offsets:
            return b""
        return self._source[int(self._offsets[0]) : int(self._offsets[-1])]

    def statistics(self) -> tuple[int, int, int, int]:
        empty = self._kinds.count(self.EMPTY)
        notes = self._kinds.count(self.NOTE)
        lightmaps = self._kinds.count(self.LIGHTMAP)
        return empty, notes, lightmaps, notes * self.columns

    @property
    def stable_id_bounds(self) -> tuple[int, int] | None:
        """Return the half-open contiguous ID range owned by this row table."""

        if not len(self):
            return None
        first = (
            int(self._first_cell_ids[0])
            if int(self._kinds[0]) == self.NOTE
            else int(self._row_ids[0])
        )
        return first, int(self._row_ids[-1]) + 1

    def has_contiguous_stable_ids(self) -> bool:
        """Check the compact parser's cell-then-row allocation invariant."""

        bounds = self.stable_id_bounds
        if bounds is None:
            return True
        expected = bounds[0]
        for index in range(len(self)):
            kind = int(self._kinds[index])
            row_id = int(self._row_ids[index])
            first_cell_id = int(self._first_cell_ids[index])
            if kind == self.NOTE:
                if first_cell_id != expected or row_id != expected + self.columns:
                    return False
                expected = row_id + 1
            elif kind in (self.EMPTY, self.LIGHTMAP):
                if first_cell_id != 0 or row_id != expected:
                    return False
                expected += 1
            else:
                return False
        return expected == bounds[1]

    def with_row(self, index: int, row: Row) -> OverlayRows:
        """Return a sparse editable view with one materialized replacement."""

        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return OverlayRows(self, ((index, row),))

    def raw_range(self, start: int, end: int) -> bytes:
        """Return source bytes for the half-open row range without materializing rows."""

        if not 0 <= start <= end <= len(self):
            raise IndexError((start, end))
        return self._source[int(self._offsets[start]) : int(self._offsets[end])]


class OverlayRows(Sequence[Row]):
    """Sparse immutable edits layered over compact source-backed rows.

    Only touched rows are retained as rich objects. Untouched rows remain in
    :class:`CompactRows`, so a one-cell edit does not allocate an entire chart.
    """

    __slots__ = ("base", "replacements")

    def __init__(self, base: CompactRows, replacements: tuple[tuple[int, Row], ...]) -> None:
        normalized = tuple(sorted(replacements, key=lambda item: item[0]))
        indexes = [index for index, _ in normalized]
        if len(indexes) != len(set(indexes)):
            raise ValueError("overlay row indexes must be unique")
        if any(index < 0 or index >= len(base) for index in indexes):
            raise IndexError("overlay row index is outside its compact base")
        self.base = base
        self.replacements = normalized

    def __len__(self) -> int:
        return len(self.base)

    def __getitem__(self, index: int | slice) -> Row | tuple[Row, ...]:
        if isinstance(index, slice):
            return tuple(self[position] for position in range(*index.indices(len(self))))
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        for replacement_index, row in self.replacements:
            if replacement_index == index:
                return row
            if replacement_index > index:
                break
        return self.base[index]

    def __iter__(self) -> Iterator[Row]:
        replacements = iter(self.replacements)
        current = next(replacements, None)
        for index in range(len(self)):
            if current is not None and current[0] == index:
                yield current[1]
                current = next(replacements, None)
            else:
                yield self.base[index]

    def with_row(self, index: int, row: Row) -> OverlayRows:
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        merged = dict(self.replacements)
        merged[index] = row
        return OverlayRows(self.base, tuple(merged.items()))

    def statistics(self) -> tuple[int, int, int, int]:
        empty, notes, lightmaps, cells = self.base.statistics()
        for index, replacement in self.replacements:
            original = self.base[index]
            for row, delta in ((original, -1), (replacement, 1)):
                if isinstance(row, EmptyRow):
                    empty += delta
                elif isinstance(row, (NoteRow, PackedNoteRow)):
                    notes += delta
                    cells += delta * row.cell_count
                else:
                    lightmaps += delta
        return empty, notes, lightmaps, cells


@dataclass(frozen=True, slots=True)
class Block:
    stable_id: StableId
    start_time: RawF32
    bpm: RawF32
    scroll: RawF32
    offset_or_delay: RawF32
    speed_or_freeze: RawF32
    beat_split: RawU8
    beat_measure: RawU8
    smooth_speed: RawU8
    raw_flag: RawU8
    division_count: RawU32
    divisions: tuple[MetadataEntry, ...]
    row_count: RawU32
    rows: tuple[Row, ...] | CompactRows | OverlayRows
    span: SourceSpan | None


@dataclass(frozen=True, slots=True)
class Split:
    stable_id: StableId
    raw_select: RawU8
    raw_brain: RawU8
    raw_padding: RawU16
    metadata_count: RawU32
    metadata: tuple[MetadataEntry, ...]
    block_count: RawU32
    blocks: tuple[Block, ...]
    span: SourceSpan | None


@dataclass(frozen=True, slots=True)
class Envelope:
    kind: EnvelopeKind
    raw: bytes
    span: SourceSpan | None

    @property
    def marker_size(self) -> int | None:
        if self.kind is not EnvelopeKind.SIZED_TRAILER:
            return None
        return struct.unpack_from("<I", self.raw, len(self.raw) - 4)[0]

    @property
    def payload(self) -> bytes:
        if self.kind is EnvelopeKind.SIZED_TRAILER:
            return self.raw[:-4]
        return self.raw


@dataclass(frozen=True, slots=True)
class NX20Document:
    stable_id: StableId
    start_column: RawU32
    columns: RawU32
    lightmap_flag: RawU32
    header_metadata_count: RawU32
    header_metadata: tuple[MetadataEntry, ...]
    split_count: RawU32
    splits: tuple[Split, ...]
    body_span: SourceSpan
    envelope: Envelope
    profile: str = "nxa-native"
    role: DeploymentRole = DeploymentRole.CHART
    source_name: str | None = None
    source_bytes: bytes = field(default=b"", repr=False, compare=False)
    # Editor-only allocation watermark; it is never serialized into NX20.
    next_stable_id: StableId = field(default=1, repr=False)

    @property
    def effective_lightmap(self) -> bool:
        return bool(self.lightmap_flag.value or self.columns.value == 3)

    @property
    def source_size(self) -> int:
        return len(self.source_bytes)

    @staticmethod
    def infer_role(path: str | Path | None) -> DeploymentRole:
        if path is None:
            return DeploymentRole.CHART
        candidate = Path(path)
        if candidate.suffix.upper() == ".NFO":
            return DeploymentRole.MISSION
        if candidate.name.upper() == "LM.NX":
            return DeploymentRole.LIGHTMAP
        return DeploymentRole.CHART

    def statistics(self) -> dict[str, int]:
        blocks = rows = empty_rows = note_rows = lightmap_rows = notes = divisions = 0
        split_metadata = 0
        for split in self.splits:
            blocks += len(split.blocks)
            split_metadata += len(split.metadata)
            for block in split.blocks:
                divisions += len(block.divisions)
                rows += len(block.rows)
                if isinstance(block.rows, (CompactRows, OverlayRows)):
                    compact_empty, compact_notes, compact_lightmaps, compact_cells = (
                        block.rows.statistics()
                    )
                    empty_rows += compact_empty
                    note_rows += compact_notes
                    lightmap_rows += compact_lightmaps
                    notes += compact_cells
                    continue
                for row in block.rows:
                    if isinstance(row, EmptyRow):
                        empty_rows += 1
                    elif isinstance(row, (NoteRow, PackedNoteRow)):
                        note_rows += 1
                        notes += row.cell_count
                    else:
                        lightmap_rows += 1
        return {
            "header_metadata": len(self.header_metadata),
            "splits": len(self.splits),
            "split_metadata": split_metadata,
            "blocks": blocks,
            "division_metadata": divisions,
            "rows": rows,
            "empty_rows": empty_rows,
            "note_rows": note_rows,
            "lightmap_rows": lightmap_rows,
            "note_cells": notes,
        }
