from __future__ import annotations

import os
import shutil
import struct
import tempfile
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from stepnx.codecs.binary import BinaryReader, ParseLimits
from stepnx.core.errors import ModelInvariantError, OutputExistsError, ParseError, UnsupportedFormatError
from stepnx.core.model import (
    Block,
    CompactRows,
    EmptyRow,
    Envelope,
    EnvelopeKind,
    LightmapRow,
    MetadataEntry,
    NoteCell,
    NoteRow,
    NX20Document,
    OverlayRows,
    PackedNoteRow,
    Split,
)
from stepnx.core.scalars import RawF32, RawU8, RawU16, RawU32, SourceSpan


NX20_MAGIC = b"NX20"
NX10_MAGIC = b"NX10"


@dataclass(slots=True)
class _IdAllocator:
    next_value: int = 1

    def take(self) -> int:
        value = self.next_value
        self.next_value += 1
        return value

    def take_many(self, count: int) -> int:
        if count < 0:
            raise ValueError("cannot allocate a negative stable-ID range")
        first = self.next_value
        self.next_value += count
        return first


def _metadata(reader: BinaryReader, ids: _IdAllocator, label: str) -> MetadataEntry:
    start = reader.position
    meta_id = reader.scalar(RawU32, f"{label} id")
    value = reader.scalar(RawU32, f"{label} value")
    return MetadataEntry(ids.take(), meta_id, value, SourceSpan(start, reader.position))


def _classify_envelope(data: bytes, body_end: int) -> Envelope:
    raw = data[body_end:]
    span = SourceSpan(body_end, len(data))
    if not raw:
        return Envelope(EnvelopeKind.NONE, raw, span)
    if len(raw) >= 4 and struct.unpack_from("<I", raw, len(raw) - 4)[0] == len(raw):
        return Envelope(EnvelopeKind.SIZED_TRAILER, raw, span)
    return Envelope(EnvelopeKind.OPAQUE_TAIL, raw, span)


def _compact_rows(
    reader: BinaryReader,
    ids: _IdAllocator,
    *,
    row_count: int,
    column_count: int,
    effective_lightmap: bool,
    label: str,
) -> CompactRows:
    offsets = array("Q")
    row_ids = array("Q")
    first_cell_ids = array("Q")
    kinds = array("B")

    for row_index in range(row_count):
        offsets.append(reader.position)
        row_prefix = f"{label} row {row_index}"
        first_raw, _ = reader.read_exact(4, f"{row_prefix} first cell or marker")
        if first_raw[0] & 0x80:
            first_cell_ids.append(0)
            row_ids.append(ids.take())
            kinds.append(CompactRows.EMPTY)
        elif effective_lightmap:
            first_cell_ids.append(0)
            row_ids.append(ids.take())
            kinds.append(CompactRows.LIGHTMAP)
        else:
            reader.read_exact((column_count - 1) * 4, f"{row_prefix} remaining cells")
            first_cell_ids.append(ids.take_many(column_count))
            row_ids.append(ids.take())
            kinds.append(CompactRows.NOTE)
    offsets.append(reader.position)
    return CompactRows(
        source=reader.data,
        offsets=offsets,
        row_ids=row_ids,
        first_cell_ids=first_cell_ids,
        kinds=kinds,
        columns=column_count,
        effective_lightmap=effective_lightmap,
    )


def parse_bytes(
    data: bytes,
    *,
    source: str | None = None,
    profile: str = "nxa-native",
    limits: ParseLimits | None = None,
    row_storage: Literal["rich", "compact"] = "compact",
) -> NX20Document:
    """Parse NX20 without normalizing any serializable field.

    The parser deliberately rejects NX10.  NX10 is an importer concern, not a
    second dialect to smuggle into the canonical NX20 codec.
    """

    if row_storage not in {"rich", "compact"}:
        raise ValueError(f"unsupported row storage mode: {row_storage!r}")

    active_limits = limits or ParseLimits()
    reader = BinaryReader(data, source)
    ids = _IdAllocator()

    magic, _ = reader.read_exact(4, "magic")
    if magic == NX10_MAGIC:
        raise UnsupportedFormatError(0, "magic", "NX10 requires the import-only codec", source)
    if magic != NX20_MAGIC:
        raise ParseError(0, "magic", f"expected NX20, found {magic!r}", source)

    start_column = reader.scalar(RawU32, "start column")
    columns = reader.scalar(RawU32, "column count")
    lightmap_flag = reader.scalar(RawU32, "lightmap flag")
    column_count = int(columns.value)
    if not 1 <= column_count <= active_limits.max_columns:
        raise ParseError(columns.span.start, "column count", f"unsupported value {column_count}", source)
    effective_lightmap = bool(lightmap_flag.value or column_count == 3)

    header_metadata_count = reader.count("header metadata count", active_limits, 8)
    header_metadata = tuple(
        _metadata(reader, ids, f"header metadata {index}")
        for index in range(int(header_metadata_count.value))
    )

    split_count = reader.count("split count", active_limits, 12)
    splits: list[Split] = []
    for split_index in range(int(split_count.value)):
        split_start = reader.position
        prefix = f"split {split_index}"
        raw_select = reader.scalar(RawU8, f"{prefix} select byte")
        raw_brain = reader.scalar(RawU8, f"{prefix} brain byte")
        raw_padding = reader.scalar(RawU16, f"{prefix} padding")
        metadata_count = reader.count(f"{prefix} metadata count", active_limits, 8)
        metadata = tuple(
            _metadata(reader, ids, f"{prefix} metadata {index}")
            for index in range(int(metadata_count.value))
        )
        block_count = reader.count(f"{prefix} block count", active_limits, 32)
        blocks: list[Block] = []

        for block_index in range(int(block_count.value)):
            block_start = reader.position
            block_prefix = f"{prefix} block {block_index}"
            start_time = reader.scalar(RawF32, f"{block_prefix} start time")
            bpm = reader.scalar(RawF32, f"{block_prefix} bpm")
            scroll = reader.scalar(RawF32, f"{block_prefix} scroll")
            offset_or_delay = reader.scalar(RawF32, f"{block_prefix} offset or delay")
            speed_or_freeze = reader.scalar(RawF32, f"{block_prefix} speed or freeze")
            beat_split = reader.scalar(RawU8, f"{block_prefix} beat split")
            beat_measure = reader.scalar(RawU8, f"{block_prefix} beat measure")
            smooth_speed = reader.scalar(RawU8, f"{block_prefix} smooth speed")
            raw_flag = reader.scalar(RawU8, f"{block_prefix} raw flag")
            division_count = reader.count(f"{block_prefix} division metadata count", active_limits, 8)
            divisions = tuple(
                _metadata(reader, ids, f"{block_prefix} division metadata {index}")
                for index in range(int(division_count.value))
            )
            row_count = reader.count(f"{block_prefix} row count", active_limits, 4)
            if row_storage == "compact":
                rows = _compact_rows(
                    reader,
                    ids,
                    row_count=int(row_count.value),
                    column_count=column_count,
                    effective_lightmap=effective_lightmap,
                    label=block_prefix,
                )
            else:
                rich_rows = []
                for row_index in range(int(row_count.value)):
                    row_start = reader.position
                    row_prefix = f"{block_prefix} row {row_index}"
                    first_raw, first_span = reader.read_exact(4, f"{row_prefix} first cell or marker")
                    if first_raw[0] & 0x80:
                        rich_rows.append(EmptyRow(ids.take(), first_raw, first_span))
                    elif effective_lightmap:
                        rich_rows.append(LightmapRow(ids.take(), first_raw, first_span))
                    else:
                        cells = [NoteCell(ids.take(), first_raw, first_span)]
                        for column_index in range(1, column_count):
                            raw, span = reader.read_exact(4, f"{row_prefix} column {column_index}")
                            cells.append(NoteCell(ids.take(), raw, span))
                        rich_rows.append(
                            NoteRow(ids.take(), tuple(cells), SourceSpan(row_start, reader.position))
                        )
                rows = tuple(rich_rows)

            blocks.append(
                Block(
                    stable_id=ids.take(),
                    start_time=start_time,
                    bpm=bpm,
                    scroll=scroll,
                    offset_or_delay=offset_or_delay,
                    speed_or_freeze=speed_or_freeze,
                    beat_split=beat_split,
                    beat_measure=beat_measure,
                    smooth_speed=smooth_speed,
                    raw_flag=raw_flag,
                    division_count=division_count,
                    divisions=divisions,
                    row_count=row_count,
                    rows=rows,
                    span=SourceSpan(block_start, reader.position),
                )
            )

        splits.append(
            Split(
                stable_id=ids.take(),
                raw_select=raw_select,
                raw_brain=raw_brain,
                raw_padding=raw_padding,
                metadata_count=metadata_count,
                metadata=metadata,
                block_count=block_count,
                blocks=tuple(blocks),
                span=SourceSpan(split_start, reader.position),
            )
        )

    body_end = reader.position
    document_source = source
    return NX20Document(
        stable_id=ids.take(),
        start_column=start_column,
        columns=columns,
        lightmap_flag=lightmap_flag,
        header_metadata_count=header_metadata_count,
        header_metadata=header_metadata,
        split_count=split_count,
        splits=tuple(splits),
        body_span=SourceSpan(0, body_end),
        envelope=_classify_envelope(data, body_end),
        profile=profile,
        role=NX20Document.infer_role(document_source),
        source_name=document_source,
        source_bytes=data,
    )


def _write_count(output: bytearray, raw_count: RawU32, actual: int) -> None:
    if int(raw_count.value) == actual:
        output.extend(raw_count.raw)
    else:
        output.extend(RawU32.from_value(actual).raw)


def _write_metadata(output: bytearray, entries: tuple[MetadataEntry, ...]) -> None:
    for entry in entries:
        output.extend(entry.meta_id.raw)
        output.extend(entry.value.raw)


def _validate_scalar_types(document: NX20Document) -> None:
    columns = int(document.columns.value)
    if not 1 <= columns <= 64:
        raise ModelInvariantError(f"column count {columns} is outside the supported structural range 1..64")

    envelope = document.envelope
    if envelope.kind is EnvelopeKind.NONE and envelope.raw:
        raise ModelInvariantError("NoTrailer envelope cannot contain bytes")
    if envelope.kind is EnvelopeKind.SIZED_TRAILER:
        if len(envelope.raw) < 4:
            raise ModelInvariantError("sized trailer is shorter than its u32 size marker")
        marker = struct.unpack_from("<I", envelope.raw, len(envelope.raw) - 4)[0]
        if marker != len(envelope.raw):
            raise ModelInvariantError(
                f"sized trailer marker says {marker} bytes, actual size is {len(envelope.raw)}"
            )


def _write_row(
    output: bytearray,
    row,
    *,
    columns: int,
    effective_lightmap: bool,
    location: str,
) -> None:
    if isinstance(row, EmptyRow):
        if len(row.raw) != 4 or not (row.raw[0] & 0x80):
            raise ModelInvariantError(f"{location}: invalid empty-row marker")
        output.extend(row.raw)
    elif effective_lightmap:
        if not isinstance(row, LightmapRow):
            raise ModelInvariantError(f"{location}: effective Lightmap requires LightmapRow")
        if len(row.raw_channels) != 4:
            raise ModelInvariantError(f"{location}: Lightmap row is not four bytes")
        output.extend(row.raw_channels)
    elif isinstance(row, PackedNoteRow):
        if row.cell_count != columns:
            raise ModelInvariantError(
                f"{location}: row has {row.cell_count} cells, expected {columns}"
            )
        output.extend(row.raw_cells)
    else:
        if not isinstance(row, NoteRow):
            raise ModelInvariantError(f"{location}: normal chart requires NoteRow")
        if len(row.cells) != columns:
            raise ModelInvariantError(
                f"{location}: row has {len(row.cells)} cells, expected {columns}"
            )
        for cell in row.cells:
            if len(cell.raw) != 4:
                raise ModelInvariantError(f"{location}: note cell is not four bytes")
            output.extend(cell.raw)


def serialize(document: NX20Document) -> bytes:
    """Rebuild the complete file from the model, including any opaque tail."""

    _validate_scalar_types(document)
    output = bytearray(NX20_MAGIC)
    output.extend(document.start_column.raw)
    output.extend(document.columns.raw)
    output.extend(document.lightmap_flag.raw)
    _write_count(output, document.header_metadata_count, len(document.header_metadata))
    _write_metadata(output, document.header_metadata)
    _write_count(output, document.split_count, len(document.splits))

    columns = int(document.columns.value)
    effective_lightmap = document.effective_lightmap
    for split_index, split in enumerate(document.splits):
        output.extend(split.raw_select.raw)
        output.extend(split.raw_brain.raw)
        output.extend(split.raw_padding.raw)
        _write_count(output, split.metadata_count, len(split.metadata))
        _write_metadata(output, split.metadata)
        _write_count(output, split.block_count, len(split.blocks))

        for block_index, block in enumerate(split.blocks):
            for scalar in (
                block.start_time,
                block.bpm,
                block.scroll,
                block.offset_or_delay,
                block.speed_or_freeze,
                block.beat_split,
                block.beat_measure,
                block.smooth_speed,
                block.raw_flag,
            ):
                output.extend(scalar.raw)
            _write_count(output, block.division_count, len(block.divisions))
            _write_metadata(output, block.divisions)
            _write_count(output, block.row_count, len(block.rows))

            if isinstance(block.rows, CompactRows):
                if block.rows.columns != columns:
                    raise ModelInvariantError(
                        f"split {split_index}, block {block_index}: compact rows use "
                        f"{block.rows.columns} columns, document uses {columns}"
                    )
                if block.rows.effective_lightmap != effective_lightmap:
                    raise ModelInvariantError(
                        f"split {split_index}, block {block_index}: compact row kind no longer "
                        "matches the document Lightmap state"
                    )
                output.extend(block.rows.raw_bytes)
                continue

            if isinstance(block.rows, OverlayRows):
                base = block.rows.base
                if base.columns != columns or base.effective_lightmap != effective_lightmap:
                    raise ModelInvariantError(
                        f"split {split_index}, block {block_index}: overlay base no longer "
                        "matches the document layout"
                    )
                cursor = 0
                for row_index, row in block.rows.replacements:
                    output.extend(base.raw_range(cursor, row_index))
                    _write_row(
                        output,
                        row,
                        columns=columns,
                        effective_lightmap=effective_lightmap,
                        location=f"split {split_index}, block {block_index}, row {row_index}",
                    )
                    cursor = row_index + 1
                output.extend(base.raw_range(cursor, len(base)))
                continue

            for row_index, row in enumerate(block.rows):
                location = f"split {split_index}, block {block_index}, row {row_index}"
                _write_row(
                    output,
                    row,
                    columns=columns,
                    effective_lightmap=effective_lightmap,
                    location=location,
                )

    output.extend(document.envelope.raw)
    return bytes(output)


def load(
    path: str | os.PathLike[str],
    *,
    profile: str = "nxa-native",
    row_storage: Literal["rich", "compact"] = "compact",
) -> NX20Document:
    source = Path(path)
    return parse_bytes(
        source.read_bytes(),
        source=str(source),
        profile=profile,
        row_storage=row_storage,
    )


def save_atomic(
    document: NX20Document,
    path: str | os.PathLike[str],
    *,
    overwrite: bool = False,
    backup: bool = False,
) -> Path:
    """Serialize and atomically publish a file in the target directory."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise OutputExistsError(f"refusing to overwrite existing file: {target}")

    payload = serialize(document)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if backup and target.exists():
            shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
        os.replace(temporary_name, target)
        temporary_name = None
        return target
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
