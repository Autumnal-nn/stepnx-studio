from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, replace

from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import CompactRows, EmptyRow, LightmapRow, OverlayRows


@dataclass(frozen=True, slots=True)
class LightmapEdit:
    """One authorable Lightmap channel addressed by stable row ID.

    NX20 Lightmap rows occupy four bytes, but the logical field has three
    columns. Corpus evidence across NXA, Fiesta 2 and Prime 2 uses bytes 0..2 as
    binary light channels and keeps byte 3 at zero. The fourth byte therefore
    remains losslessly preserved and intentionally has no authoring lane.
    """

    row_id: int
    lane: int
    value: int

    def __post_init__(self) -> None:
        if not 0 <= int(self.lane) < 3:
            raise ValueError("a Lightmap edit lane must be between 0 and 2")
        if int(self.value) not in (0, 1):
            raise ValueError("a Lightmap edit value must be 0 or 1")


@dataclass(frozen=True, slots=True)
class SetLightmapCells:
    """Apply one or more three-lane Lightmap edits as one atomic command."""

    edits: tuple[LightmapEdit, ...]

    def __post_init__(self) -> None:
        if not self.edits:
            raise ValueError("a bulk Lightmap edit cannot be empty")
        targets = {(int(edit.row_id), int(edit.lane)) for edit in self.edits}
        if len(targets) != len(self.edits):
            raise ValueError("a bulk Lightmap edit cannot target the same cell twice")

    def apply(self, document):
        if not document.effective_lightmap:
            raise ModelInvariantError("Lightmap cell tools require a Lightmap document")
        if int(document.columns.value) != 3:
            raise ModelInvariantError(
                "Lightmap authoring requires the observed three-column field"
            )

        pending_by_row: dict[int, dict[int, int]] = {}
        for edit in self.edits:
            pending_by_row.setdefault(int(edit.row_id), {})[int(edit.lane)] = int(edit.value)

        matches = 0
        splits = []
        for split in document.splits:
            blocks = []
            split_changed = False
            for block in split.blocks:
                rows = block.rows
                base = rows.base if isinstance(rows, OverlayRows) else rows
                indexed_edits: dict[int, dict[int, int]] = {}

                if isinstance(base, CompactRows):
                    row_ids = base._row_ids
                    for row_id, row_edits in pending_by_row.items():
                        row_index = bisect_left(row_ids, row_id)
                        if row_index < len(row_ids) and int(row_ids[row_index]) == row_id:
                            indexed_edits[row_index] = row_edits
                else:
                    for row_index, row in enumerate(rows):
                        row_edits = pending_by_row.get(int(row.stable_id))
                        if row_edits:
                            indexed_edits[row_index] = row_edits

                replacements = {}
                for row_index, row_edits in indexed_edits.items():
                    row = rows[row_index]
                    if isinstance(row, EmptyRow):
                        channels = bytearray(b"\x00\x00\x00\x00")
                    elif isinstance(row, LightmapRow):
                        channels = bytearray(row.raw_channels)
                    else:
                        raise ModelInvariantError(
                            f"row {row.stable_id} is not a Lightmap row"
                        )

                    before = bytes(channels)
                    for lane, value in row_edits.items():
                        channels[lane] = value
                        matches += 1
                    after = bytes(channels)
                    if after == before:
                        continue

                    # If this row originated as an explicit EmptyRow marker and
                    # a sparse edit later returns all three channels to zero,
                    # restore that original marker instead of silently changing
                    # its structural encoding to 00 00 00 00.
                    original = rows.base[row_index] if isinstance(rows, OverlayRows) else None
                    if (
                        after == b"\x00\x00\x00\x00"
                        and isinstance(original, EmptyRow)
                    ):
                        replacement = EmptyRow(row.stable_id, original.raw, None)
                    else:
                        replacement = LightmapRow(row.stable_id, after, None)
                    replacements[row_index] = replacement

                if replacements:
                    if isinstance(rows, OverlayRows):
                        merged = dict(rows.replacements)
                        merged.update(replacements)
                        edited_rows = OverlayRows(rows.base, tuple(merged.items()))
                    elif isinstance(rows, CompactRows):
                        edited_rows = OverlayRows(rows, tuple(replacements.items()))
                    else:
                        materialized = list(rows)
                        for row_index, replacement in replacements.items():
                            materialized[row_index] = replacement
                        edited_rows = tuple(materialized)
                    block = replace(block, rows=edited_rows)
                    split_changed = True
                blocks.append(block)
            splits.append(replace(split, blocks=tuple(blocks)) if split_changed else split)

        if matches != len(self.edits):
            raise ModelInvariantError(
                f"expected {len(self.edits)} Lightmap-edit targets, found {matches}"
            )
        return replace(document, splits=tuple(splits))
