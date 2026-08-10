from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from stepnx.core.model import EmptyRow, LightmapRow, NoteRow, NX20Document, PackedNoteRow


@dataclass(frozen=True, slots=True)
class StructuralChange:
    path: str
    before: Any
    after: Any


def _row_bytes(row) -> bytes:
    if isinstance(row, EmptyRow):
        return row.raw
    if isinstance(row, LightmapRow):
        return row.raw_channels
    if isinstance(row, PackedNoteRow):
        return row.raw_cells
    if isinstance(row, NoteRow):
        return b"".join(cell.raw for cell in row.cells)
    raise TypeError(type(row).__name__)


def _blob_summary(raw: bytes) -> dict[str, Any]:
    return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def diff_documents(
    before: NX20Document,
    after: NX20Document,
    *,
    max_changes: int | None = None,
) -> tuple[StructuralChange, ...]:
    """Compare serializable NX20 structure by position, ignoring spans and stable IDs."""

    changes: list[StructuralChange] = []

    def add(path: str, left: Any, right: Any) -> bool:
        if left == right:
            return False
        if max_changes is None or len(changes) < max_changes:
            changes.append(StructuralChange(path, left, right))
        return max_changes is not None and len(changes) >= max_changes

    def scalar(path: str, left, right) -> bool:
        return add(path, left.raw.hex().upper(), right.raw.hex().upper())

    for name in ("start_column", "columns", "lightmap_flag"):
        if scalar(name, getattr(before, name), getattr(after, name)):
            return tuple(changes)

    def metadata(path: str, left, right) -> bool:
        if add(f"{path}.length", len(left), len(right)):
            return True
        for index, (left_entry, right_entry) in enumerate(zip(left, right)):
            if scalar(f"{path}[{index}].id", left_entry.meta_id, right_entry.meta_id):
                return True
            if scalar(f"{path}[{index}].value", left_entry.value, right_entry.value):
                return True
        return False

    if metadata("header_metadata", before.header_metadata, after.header_metadata):
        return tuple(changes)
    if add("splits.length", len(before.splits), len(after.splits)):
        return tuple(changes)

    split_fields = ("raw_select", "raw_brain", "raw_padding")
    block_fields = (
        "start_time",
        "bpm",
        "scroll",
        "offset_or_delay",
        "speed_or_freeze",
        "beat_split",
        "beat_measure",
        "smooth_speed",
        "raw_flag",
    )
    for split_index, (left_split, right_split) in enumerate(zip(before.splits, after.splits)):
        split_path = f"splits[{split_index}]"
        for name in split_fields:
            if scalar(f"{split_path}.{name}", getattr(left_split, name), getattr(right_split, name)):
                return tuple(changes)
        if metadata(f"{split_path}.metadata", left_split.metadata, right_split.metadata):
            return tuple(changes)
        if add(f"{split_path}.blocks.length", len(left_split.blocks), len(right_split.blocks)):
            return tuple(changes)

        for block_index, (left_block, right_block) in enumerate(
            zip(left_split.blocks, right_split.blocks)
        ):
            block_path = f"{split_path}.blocks[{block_index}]"
            for name in block_fields:
                if scalar(f"{block_path}.{name}", getattr(left_block, name), getattr(right_block, name)):
                    return tuple(changes)
            if metadata(f"{block_path}.divisions", left_block.divisions, right_block.divisions):
                return tuple(changes)
            if add(f"{block_path}.rows.length", len(left_block.rows), len(right_block.rows)):
                return tuple(changes)
            for row_index, (left_row, right_row) in enumerate(
                zip(left_block.rows, right_block.rows)
            ):
                left_raw = _row_bytes(left_row)
                right_raw = _row_bytes(right_row)
                if add(
                    f"{block_path}.rows[{row_index}].raw",
                    left_raw.hex().upper(),
                    right_raw.hex().upper(),
                ):
                    return tuple(changes)

    if before.envelope.kind is not after.envelope.kind:
        if add("envelope.kind", before.envelope.kind.value, after.envelope.kind.value):
            return tuple(changes)
    if before.envelope.raw != after.envelope.raw:
        add("envelope.raw", _blob_summary(before.envelope.raw), _blob_summary(after.envelope.raw))
    return tuple(changes)
