"""Context-menu structural command plans for the experimental Qt viewport.

Reuse the existing StepNX domain commands and tested Split cascade. This
module intentionally does not contain a second serializer or timing engine.
The UI owns all destructive confirmations.
"""
from __future__ import annotations

from dataclasses import dataclass

from stepnx.authoring.structure import (
    StructureTarget,
    insert_empty_split_after,
    remove_block,
    remove_split,
)
from stepnx.core.commands import InsertBlock
from stepnx.gui.phase10_install import (
    _MergeSplitsCommand,
    _ReplaceDocument,
    _SplitHereCommand,
    _empty_block_same_length,
)
from stepnx.gui.phase11_split_cascade import resize_split_boundary_cascade_document


@dataclass(frozen=True, slots=True)
class StructuralActionPlan:
    command: object
    description: str
    confirmation: str | None = None
    actual_rows: int | None = None


def plan_structure_action(
    document, action: str, split_id: int, block_id: int,
    *, row_index: int | None = None, requested_rows: int | None = None,
) -> StructuralActionPlan:
    split_index = next(
        (index for index, item in enumerate(document.splits)
         if item.stable_id == split_id), None
    )
    if split_index is None:
        raise ValueError("Split no longer exists")
    split = document.splits[split_index]
    block_index = next(
        (index for index, item in enumerate(split.blocks)
         if item.stable_id == block_id), None
    )
    if block_index is None:
        raise ValueError("Block no longer exists in the selected Split")
    block = split.blocks[block_index]
    target = StructureTarget(split_id, block_id)

    if action == "split-here":
        if row_index is None or not 0 < row_index < len(block.rows):
            raise ValueError("Split Here requires a row inside the current Block")
        return StructuralActionPlan(
            _SplitHereCommand(split_id, block_id, row_index),
            "Split at row",
        )
    if action == "insert-split":
        return StructuralActionPlan(
            insert_empty_split_after(document, target),
            "Insert empty Split",
            "Insert a new one-row Split using copied timing fields? "
            "You may need to edit its Start Time afterward.",
        )
    if action == "merge-splits":
        if split_index + 1 >= len(document.splits):
            raise ValueError("the final Split cannot merge with a successor")
        next_split = document.splits[split_index + 1]
        return StructuralActionPlan(
            _MergeSplitsCommand(split_id),
            "Merge two Splits",
            "Merge the current Split with the next one? This retains the upper "
            "Split's timing/metadata and Block count. Excess lower branches "
            "and independent lower timing can be discarded. "
            f"Current: {len(split.blocks)} Block(s). "
            f"Next: {len(next_split.blocks)} Block(s).",
        )
    if action == "delete-split":
        return StructuralActionPlan(
            remove_split(document, target),
            "Delete Split",
            "Delete this entire Split, including every Block and note? "
            "This is undoable until the document is saved.",
        )
    if action == "insert-block":
        before_id = (
            split.blocks[block_index + 1].stable_id
            if block_index + 1 < len(split.blocks) else None
        )
        return StructuralActionPlan(
            InsertBlock(
                split_id, _empty_block_same_length(block),
                before_block_id=before_id,
            ),
            "Insert empty Block",
        )
    if action == "duplicate-block":
        before_id = (
            split.blocks[block_index + 1].stable_id
            if block_index + 1 < len(split.blocks) else None
        )
        return StructuralActionPlan(
            InsertBlock(split_id, block, before_block_id=before_id),
            "Duplicate Block",
        )
    if action == "delete-block":
        return StructuralActionPlan(
            remove_block(document, target),
            "Delete Block",
            "Delete this Block and all of its notes? The other alternatives "
            "in this Split will remain intact.",
        )
    if action == "resize-split":
        if requested_rows is None or requested_rows < 1:
            raise ValueError("Split resize needs a positive row count")
        updated, actual = resize_split_boundary_cascade_document(
            document, split_id, block_id, requested_rows,
        )
        if actual == len(block.rows):
            raise ValueError("the requested Split length is unchanged")
        confirmation = None
        if actual < len(block.rows):
            # All branches are resized to the same *musical* length, not the
            # same number of encoded rows. Never silently truncate notes.
            before_split = split
            after_split = updated.splits[split_index]
            erased = 0
            for original, resized in zip(before_split.blocks, after_split.blocks):
                for row in original.rows[len(resized.rows):]:
                    if hasattr(row, "cells"):
                        erased += sum(bool(cell.raw and any(cell.raw)) for cell in row.cells)
                    elif hasattr(row, "raw_channels"):
                        erased += int(any(row.raw_channels))
                    elif hasattr(row, "cell_count"):
                        erased += sum(any(row.cell(lane).raw) for lane in range(row.cell_count))
            confirmation = (
                "Shortening this Split permanently truncates trailing rows "
                f"across all {len(split.blocks)} alternatives, including "
                f"{erased} nonempty note cell(s). Continue?"
            )
        else:
            confirmation = (
                "Extend this Split and shift the Start Time of ALL downstream "
                "Blocks by the same millisecond delta?"
            )
        return StructuralActionPlan(
            _ReplaceDocument(updated), "Resize Split with timing cascade",
            confirmation, actual_rows=actual,
        )
    raise ValueError(f"unknown structural action: {action}")
