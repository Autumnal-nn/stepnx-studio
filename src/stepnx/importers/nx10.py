from __future__ import annotations

import math
import struct
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from stepnx.codecs.binary import ParseLimits
from stepnx.core.errors import ParseError
from stepnx.core.model import (
    Block,
    EmptyRow,
    Envelope,
    EnvelopeKind,
    LightmapRow,
    MetadataEntry,
    NoteCell,
    NoteRow,
    NX20Document,
    Split,
)
from stepnx.core.scalars import RawF32, RawU8, RawU16, RawU32, SourceSpan


NX10_MAGIC = b"NX10"
NX20_RANDOM_START = 0x80
NX20_RANDOM_SPLIT = 0x40
NX20_SMOOTH_WARP = 0x02


class ImportDiagnosticKind(str, Enum):
    TRANSFORMATION = "transformation"
    APPROXIMATION = "approximation"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ImportDiagnostic:
    kind: ImportDiagnosticKind
    code: str
    message: str
    offset: int | None = None
    path: str | None = None


@dataclass(frozen=True, slots=True)
class NX10ImportReport:
    diagnostics: tuple[ImportDiagnostic, ...]
    source_size: int
    splits: int
    blocks: int
    rows: int
    note_cells: int

    @property
    def approximations(self) -> tuple[ImportDiagnostic, ...]:
        return tuple(
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.kind is ImportDiagnosticKind.APPROXIMATION
        )

    @property
    def unsupported(self) -> tuple[ImportDiagnostic, ...]:
        return tuple(
            diagnostic
            for diagnostic in self.diagnostics
            if diagnostic.kind is ImportDiagnosticKind.UNSUPPORTED
        )

    @property
    def is_semantically_lossless(self) -> bool:
        return not self.approximations and not self.unsupported


@dataclass(frozen=True, slots=True)
class NX10ImportResult:
    document: NX20Document
    report: NX10ImportReport
    source_bytes: bytes


@dataclass(slots=True)
class _IdAllocator:
    next_value: int = 1

    def take(self) -> int:
        value = self.next_value
        self.next_value += 1
        return value


@dataclass(frozen=True, slots=True)
class _HeaderMode:
    start_column: int
    columns: int
    lightmap: bool
    step_offset: int


class _NX10Reader:
    def __init__(self, data: bytes, source: str | None, limits: ParseLimits):
        self.data = data
        self.source = source
        self.limits = limits

    def exact_at(self, offset: int, size: int, label: str) -> tuple[bytes, SourceSpan]:
        if offset < 0 or size < 0 or offset > len(self.data) or size > len(self.data) - offset:
            available = max(0, len(self.data) - max(0, offset))
            raise ParseError(
                max(0, offset),
                label,
                f"truncated: need {size} byte(s), have {available}",
                self.source,
            )
        return self.data[offset : offset + size], SourceSpan(offset, offset + size)

    def u8(self, offset: int, label: str) -> RawU8:
        raw, span = self.exact_at(offset, 1, label)
        return RawU8(raw, span)

    def u16(self, offset: int, label: str) -> RawU16:
        raw, span = self.exact_at(offset, 2, label)
        return RawU16(raw, span)

    def u32(self, offset: int, label: str) -> RawU32:
        raw, span = self.exact_at(offset, 4, label)
        return RawU32(raw, span)

    def f32(self, offset: int, label: str) -> RawF32:
        raw, span = self.exact_at(offset, 4, label)
        return RawF32(raw, span)

    def count(self, offset: int, label: str, *, item_size: int = 0) -> RawU32:
        count = self.u32(offset, label)
        value = int(count.value)
        if value > self.limits.max_count:
            raise ParseError(offset, label, f"unreasonable count {value}", self.source)
        if item_size:
            table_start = offset + 4
            remaining = max(0, len(self.data) - table_start)
            if value > remaining // item_size:
                raise ParseError(
                    offset,
                    label,
                    f"{value} item(s) cannot fit in {remaining} remaining byte(s)",
                    self.source,
                )
        return count

    def offset_table(self, offset: int, count: int, label: str) -> tuple[RawU32, ...]:
        self.exact_at(offset, count * 4, label)
        return tuple(self.u32(offset + index * 4, f"{label} {index}") for index in range(count))


_NX10_TO_NX20_TYPE = {1: 1, 2: 2, 3: 3, 4: 7, 6: 11, 7: 15}
_NX10_ITEM_TO_NX20 = {
    16128: 15,
    11008: 10,
    13056: 12,
    14080: 13,
    15104: 14,
    768: 0,
    1792: 1,
    2816: 2,
    3840: 3,
    4864: 4,
    5888: 5,
    6912: 6,
    7936: 7,
    8960: 8,
    9984: 9,
    12032: 11,
    17152: 16,
    18176: 17,
    19200: 18,
    20224: 19,
    21248: 20,
}
_NX10_SKIN_TO_BANK = {0: (0, False), 1280: (1, False), 2560: (2, False)}
_NX10_SKIN_TO_BANK.update({61440: (0, True), 61696: (1, True), 61952: (2, True)})
_NX10_ACCUMULATOR_TO_ID = {3: 0, 7: 1, 11: 2, 15: 3, 19: 4}


def _mode(chart_type: RawU32, columns: RawU32, source: str | None) -> _HeaderMode:
    pair = int(chart_type.value), int(columns.value)
    modes = {
        (0, 5): _HeaderMode(0, 5, False, 0),
        (0, 10): _HeaderMode(0, 10, False, 0),
        (2, 6): _HeaderMode(2, 6, False, 4),
        (10, 3): _HeaderMode(0, 3, True, 20),
    }
    try:
        return modes[pair]
    except KeyError as error:
        raise ParseError(
            chart_type.span.start,
            "NX10 header mode",
            f"unsupported chart type/column combination {pair[0]}/{pair[1]}",
            source,
        ) from error


def _diagnostic(
    diagnostics: list[ImportDiagnostic],
    kind: ImportDiagnosticKind,
    code: str,
    message: str,
    *,
    offset: int | None = None,
    path: str | None = None,
) -> None:
    diagnostics.append(ImportDiagnostic(kind, code, message, offset, path))


def _note_to_nx20(
    raw: bytes,
    diagnostics: list[ImportDiagnostic],
    *,
    offset: int,
    path: str,
) -> bytes:
    code = struct.unpack("<H", raw)[0]
    if code == 0:
        return b"\x00\x00\x00\x00"

    nx10_type = code & 0x0F
    note_type = _NX10_TO_NX20_TYPE.get(nx10_type)
    if note_type is None:
        _diagnostic(
            diagnostics,
            ImportDiagnosticKind.UNSUPPORTED,
            "nx10.note.unknown-type",
            f"unknown NX10 note type 0x{nx10_type:X}; projected as empty",
            offset=offset,
            path=path,
        )
        return b"\x00\x00\x00\x00"

    visibility_function = code & 0xF0
    if visibility_function in {0x70, 0xB0, 0xF0}:
        visibility = 3
    elif visibility_function in {0x50, 0x90, 0xD0}:
        visibility = 1
    elif visibility_function in {0x80, 0xC0}:
        visibility = 0
    elif visibility_function in {0x60, 0xA0, 0xE0}:
        visibility = 2
    else:
        visibility = 3
        _diagnostic(
            diagnostics,
            ImportDiagnosticKind.APPROXIMATION,
            "nx10.note.unknown-visibility-function",
            f"unknown NX10 visibility/function byte 0x{visibility_function:02X}; "
            "projected as Visible",
            offset=offset,
            path=path,
        )

    if visibility_function < 0x80:
        functionality = "noreg"
    elif visibility_function >= 0xC0:
        functionality = "register-no-combo"
    else:
        functionality = "normal"

    high = code & 0xFF00
    roll = False
    bank = 0
    item_id: int | None = None
    accumulator_id = 0
    if nx10_type == 1:
        item_id = _NX10_ITEM_TO_NX20.get(high)
        if item_id is None:
            _diagnostic(
                diagnostics,
                ImportDiagnosticKind.UNSUPPORTED,
                "nx10.note.unknown-item",
                f"unknown NX10 item code 0x{high:04X}; projected as empty",
                offset=offset,
                path=path,
            )
            return b"\x00\x00\x00\x00"
    elif nx10_type == 2:
        accumulator_raw = high >> 8
        if accumulator_raw not in _NX10_ACCUMULATOR_TO_ID:
            _diagnostic(
                diagnostics,
                ImportDiagnosticKind.APPROXIMATION,
                "nx10.note.unknown-accumulator",
                f"unknown NX10 accumulator selector 0x{accumulator_raw:02X}; "
                "projected as accumulator 0",
                offset=offset,
                path=path,
            )
        accumulator_id = _NX10_ACCUMULATOR_TO_ID.get(accumulator_raw, 0)
    else:
        skin = _NX10_SKIN_TO_BANK.get(high)
        if skin is None:
            _diagnostic(
                diagnostics,
                ImportDiagnosticKind.APPROXIMATION,
                "nx10.note.unknown-skin",
                f"unknown NX10 skin/roll code 0x{high:04X}; projected as skin bank 0",
                offset=offset,
                path=path,
            )
        else:
            bank, roll = skin

    if functionality == "normal":
        low = 0x50 if note_type not in {2, 3} and not roll else 0x40
    elif functionality == "register-no-combo":
        low = 0x60 if note_type not in {7, 11, 15} or roll else 0x70
    else:
        low = 0x20
    value = low | note_type | (visibility << 8)
    if item_id is not None:
        value |= 0xC0000000 | (item_id << 16)
    elif note_type == 2:
        value |= 0xC0000000 | (accumulator_id << 16)
    else:
        value |= bank << 16
    return struct.pack("<I", value)


def _safe_bpm(blocks: list[Block], index: int) -> RawF32:
    for candidate in range(index - 1, -1, -1):
        value = float(blocks[candidate].bpm.value)
        if value > 0.0 and math.isfinite(value):
            return RawF32(blocks[candidate].bpm.raw, None)
    for candidate in range(index + 1, len(blocks)):
        value = float(blocks[candidate].bpm.value)
        if value > 0.0 and math.isfinite(value):
            return RawF32(blocks[candidate].bpm.raw, None)
    return RawF32.from_value(120.0)


def _project_divisions(
    reader: _NX10Reader,
    ids: _IdAllocator,
    extra_offset: int,
    diagnostics: list[ImportDiagnostic],
    *,
    path: str,
) -> tuple[tuple[MetadataEntry, ...], int]:
    if extra_offset == 0:
        return (), 0
    reader.exact_at(extra_offset, 80, f"{path} Division metadata table")
    minimums = tuple(
        reader.u32(extra_offset + index * 4, f"{path} Division {index} minimum")
        for index in range(10)
    )
    maximums = tuple(
        reader.u32(extra_offset + 40 + index * 4, f"{path} Division {index} maximum")
        for index in range(10)
    )

    raw_select = 0
    metadata: list[MetadataEntry] = []
    for meta_id, (minimum, maximum) in enumerate(zip(minimums, maximums)):
        lower = int(minimum.value)
        upper = int(maximum.value)
        if meta_id == 0 and upper == 0 and lower in {1, 2}:
            raw_select |= NX20_RANDOM_START if lower == 1 else NX20_RANDOM_SPLIT
            _diagnostic(
                diagnostics,
                ImportDiagnosticKind.TRANSFORMATION,
                "nx10.division-0.random-select",
                f"Division 0 range {lower}/0 projected to Split select bit "
                f"0x{(NX20_RANDOM_START if lower == 1 else NX20_RANDOM_SPLIT):02X}",
                offset=minimum.span.start,
                path=path,
            )
            continue
        if lower == 0 and upper == 0:
            continue
        if lower > 0xFFFF or upper > 0xFFFF:
            _diagnostic(
                diagnostics,
                ImportDiagnosticKind.APPROXIMATION,
                "nx10.division.range-narrowed",
                f"Division {meta_id} range {lower}/{upper} exceeds NX20's packed "
                "u16 range; high bits discarded",
                offset=minimum.span.start,
                path=path,
            )
        packed = ((upper & 0xFFFF) << 16) | (lower & 0xFFFF)
        metadata.append(
            MetadataEntry(
                stable_id=ids.take(),
                meta_id=RawU32.from_value(meta_id),
                value=RawU32.from_value(packed),
                span=None,
            )
        )
    return tuple(metadata), raw_select


def import_bytes(
    data: bytes,
    *,
    source: str | None = None,
    profile: str = "nxa-native",
    limits: ParseLimits | None = None,
) -> NX10ImportResult:
    """Import one NX10 chart into the canonical NX20 document model.

    The source bytes remain attached to the result. The returned document is a
    deterministic NX20 projection and can be serialized by the native NX20
    codec; no NX10 writer is provided.
    """

    active_limits = limits or ParseLimits()
    reader = _NX10Reader(data, source, active_limits)
    magic, _ = reader.exact_at(0, 4, "magic")
    if magic != NX10_MAGIC:
        raise ParseError(0, "magic", f"expected NX10, found {magic!r}", source)

    chart_type = reader.u32(4, "NX10 chart type")
    columns = reader.u32(8, "NX10 column count")
    mode = _mode(chart_type, columns, source)
    if mode.columns > active_limits.max_columns:
        raise ParseError(
            columns.span.start,
            "NX10 column count",
            f"unsupported value {mode.columns}",
            source,
        )
    split_count = reader.count(12, "NX10 split count", item_size=4)
    split_offsets = reader.offset_table(16, int(split_count.value), "NX10 split offset")

    ids = _IdAllocator()
    diagnostics: list[ImportDiagnostic] = []
    splits: list[Split] = []
    total_blocks = total_rows = total_cells = 0

    for split_index, split_offset_raw in enumerate(split_offsets):
        split_offset = int(split_offset_raw.value)
        split_path = f"split {split_index}"
        if split_offset == 0:
            raise ParseError(split_offset_raw.span.start, split_path, "null split offset", source)
        block_count = reader.count(split_offset, f"{split_path} block count", item_size=4)
        block_offsets = reader.offset_table(
            split_offset + 4,
            int(block_count.value),
            f"{split_path} block offset",
        )
        blocks: list[Block] = []
        split_select = 0

        for block_index, block_offset_raw in enumerate(block_offsets):
            block_offset = int(block_offset_raw.value)
            block_path = f"{split_path} block {block_index}"
            if block_offset == 0:
                raise ParseError(
                    block_offset_raw.span.start,
                    block_path,
                    "null block offset",
                    source,
                )
            reader.exact_at(block_offset, 32, f"{block_path} header")
            start_time = reader.f32(block_offset, f"{block_path} start time")
            bpm = reader.f32(block_offset + 4, f"{block_path} BPM")
            scroll = reader.f32(block_offset + 8, f"{block_path} scroll")
            offset_or_delay = reader.f32(block_offset + 12, f"{block_path} offset or delay")
            speed_or_freeze = reader.f32(block_offset + 16, f"{block_path} speed or freeze")
            extra_offset = int(
                reader.u32(
                    block_offset + 20,
                    f"{block_path} Division table offset",
                ).value
            )
            beat_split_16 = reader.u16(block_offset + 24, f"{block_path} beat split")
            beat_measure = reader.u8(block_offset + 26, f"{block_path} beat measure")
            smooth = reader.u8(block_offset + 27, f"{block_path} smooth speed")
            row_count = reader.count(block_offset + 28, f"{block_path} row count")

            beat_split_value = int(beat_split_16.value)
            if beat_split_value > 0xFF:
                _diagnostic(
                    diagnostics,
                    ImportDiagnosticKind.APPROXIMATION,
                    "nx10.block.beat-split-narrowed",
                    f"beat split {beat_split_value} exceeds NX20 u8; high byte discarded",
                    offset=beat_split_16.span.start,
                    path=block_path,
                )
            beat_split = RawU8.from_value(beat_split_value & 0xFF)

            divisions, select_bits = _project_divisions(
                reader,
                ids,
                extra_offset,
                diagnostics,
                path=block_path,
            )
            split_select |= select_bits

            rows = []
            if mode.lightmap:
                rows_start = block_offset + 32
                reader.exact_at(rows_start, int(row_count.value) * 4, f"{block_path} Lightmap rows")
                for row_index in range(int(row_count.value)):
                    row_offset = rows_start + row_index * 4
                    raw, span = reader.exact_at(row_offset, 4, f"{block_path} row {row_index}")
                    if raw[0] & 0x80:
                        rows.append(EmptyRow(ids.take(), raw, span))
                    else:
                        rows.append(LightmapRow(ids.take(), raw, span))
            else:
                row_offsets_start = block_offset + 32
                row_offsets = reader.offset_table(
                    row_offsets_start,
                    int(row_count.value),
                    f"{block_path} row offset",
                )
                for row_index, row_offset_raw in enumerate(row_offsets):
                    row_path = f"{block_path} row {row_index}"
                    stored_offset = int(row_offset_raw.value)
                    if stored_offset == 0:
                        rows.append(EmptyRow(ids.take(), b"\x80\x00\x00\x00", None))
                        continue
                    row_offset = stored_offset + mode.step_offset
                    row_size = mode.columns * 2
                    _, row_span = reader.exact_at(row_offset, row_size, row_path)
                    cells = []
                    for column in range(mode.columns):
                        note_offset = row_offset + column * 2
                        raw, _ = reader.exact_at(note_offset, 2, f"{row_path} column {column}")
                        converted = _note_to_nx20(
                            raw,
                            diagnostics,
                            offset=note_offset,
                            path=f"{row_path} column {column}",
                        )
                        cells.append(NoteCell(ids.take(), converted, None))
                    rows.append(NoteRow(ids.take(), tuple(cells), row_span))
                    total_cells += mode.columns

            smooth_value = int(smooth.value)
            block_end = max(
                [
                    block_offset + 32 + int(row_count.value) * 4,
                    extra_offset + 80 if extra_offset else block_offset + 32,
                    *(row.span.end for row in rows if row.span is not None),
                ]
            )
            block = Block(
                stable_id=ids.take(),
                start_time=start_time,
                bpm=bpm,
                scroll=scroll,
                offset_or_delay=offset_or_delay,
                speed_or_freeze=speed_or_freeze,
                beat_split=beat_split,
                beat_measure=beat_measure,
                smooth_speed=RawU8.from_value(smooth_value),
                raw_flag=RawU8.from_value(0),
                division_count=RawU32.from_value(len(divisions)),
                divisions=divisions,
                row_count=RawU32.from_value(len(rows)),
                rows=tuple(rows),
                span=SourceSpan(block_offset, block_end),
            )
            blocks.append(block)
            total_rows += len(rows)

        frozen_blocks = tuple(blocks)
        total_blocks += len(frozen_blocks)
        split_end = max(
            [
                split_offset + 4 + len(block_offsets) * 4,
                *(block.span.end for block in frozen_blocks if block.span is not None),
            ]
        )
        splits.append(
            Split(
                stable_id=ids.take(),
                raw_select=RawU8.from_value(split_select),
                raw_brain=RawU8.from_value(0),
                raw_padding=RawU16.from_value(0),
                metadata_count=RawU32.from_value(0),
                metadata=(),
                block_count=RawU32.from_value(len(frozen_blocks)),
                blocks=frozen_blocks,
                span=SourceSpan(split_offset, split_end),
            )
        )

    flat_locations = [
        (split_index, block_index)
        for split_index, split in enumerate(splits)
        for block_index in range(len(split.blocks))
    ]
    flat_blocks = [
        splits[split_index].blocks[block_index]
        for split_index, block_index in flat_locations
    ]
    for flat_index, (split_index, block_index) in enumerate(flat_locations):
        block = flat_blocks[flat_index]
        if float(block.bpm.value) != 0.0:
            continue
        replacement = _safe_bpm(flat_blocks, flat_index)
        converted = replace(
            block,
            bpm=replacement,
            smooth_speed=RawU8.from_value(int(block.smooth_speed.value) | NX20_SMOOTH_WARP),
        )
        flat_blocks[flat_index] = converted
        split = splits[split_index]
        updated_blocks = list(split.blocks)
        updated_blocks[block_index] = converted
        splits[split_index] = replace(split, blocks=tuple(updated_blocks))
        _diagnostic(
            diagnostics,
            ImportDiagnosticKind.TRANSFORMATION,
            "nx10.block.bpm-zero-warp",
            f"BPM 0 projected to NX20 smooth warp using auxiliary BPM {replacement.value:g}",
            offset=block.bpm.span.start,
            path=f"split {split_index} block {block_index}",
        )

    document = NX20Document(
        stable_id=ids.take(),
        start_column=RawU32.from_value(mode.start_column),
        columns=RawU32.from_value(mode.columns),
        lightmap_flag=RawU32.from_value(1 if mode.lightmap else 0),
        header_metadata_count=RawU32.from_value(0),
        header_metadata=(),
        split_count=RawU32.from_value(len(splits)),
        splits=tuple(splits),
        body_span=SourceSpan(0, len(data)),
        envelope=Envelope(EnvelopeKind.NONE, b"", SourceSpan(len(data), len(data))),
        profile=profile,
        role=NX20Document.infer_role(source),
        source_name=source,
        source_bytes=data,
        next_stable_id=ids.next_value,
    )
    report = NX10ImportReport(
        diagnostics=tuple(diagnostics),
        source_size=len(data),
        splits=len(splits),
        blocks=total_blocks,
        rows=total_rows,
        note_cells=total_cells,
    )
    return NX10ImportResult(document, report, data)


def load(
    path: str | Path,
    *,
    profile: str = "nxa-native",
    limits: ParseLimits | None = None,
) -> NX10ImportResult:
    source = Path(path)
    return import_bytes(
        source.read_bytes(),
        source=str(source),
        profile=profile,
        limits=limits,
    )
