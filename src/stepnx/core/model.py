from __future__ import annotations

import struct
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


@dataclass(frozen=True, slots=True)
class LightmapRow:
    stable_id: StableId
    raw_channels: bytes
    span: SourceSpan | None

    def __post_init__(self) -> None:
        if len(self.raw_channels) != 4 or (self.span is not None and self.span.size != 4):
            raise ValueError("a Lightmap row must occupy exactly four bytes")


Row: TypeAlias = EmptyRow | NoteRow | LightmapRow


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
    rows: tuple[Row, ...]
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
                for row in block.rows:
                    if isinstance(row, EmptyRow):
                        empty_rows += 1
                    elif isinstance(row, NoteRow):
                        note_rows += 1
                        notes += len(row.cells)
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
