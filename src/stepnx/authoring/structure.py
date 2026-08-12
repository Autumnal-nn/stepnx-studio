from __future__ import annotations

from dataclasses import dataclass, replace

from stepnx.core.commands import (
    InsertBlock,
    InsertSplit,
    MoveBlock,
    MoveSplit,
    RemoveBlock,
    RemoveSplit,
)
from stepnx.core.model import Block, EmptyRow, NX20Document, Split
from stepnx.core.scalars import RawU32


class StructureEditError(ValueError):
    """Raised when an authoring operation would create an unusable structure."""


@dataclass(frozen=True, slots=True)
class StructureTarget:
    split_id: int
    block_id: int | None = None


def _split(document: NX20Document, split_id: int) -> tuple[int, Split]:
    matches = [
        (index, split)
        for index, split in enumerate(document.splits)
        if split.stable_id == split_id
    ]
    if len(matches) != 1:
        raise StructureEditError(
            f"expected one split with stable ID {split_id}, found {len(matches)}"
        )
    return matches[0]


def _block(split: Split, block_id: int) -> tuple[int, Block]:
    matches = [
        (index, block)
        for index, block in enumerate(split.blocks)
        if block.stable_id == block_id
    ]
    if len(matches) != 1:
        raise StructureEditError(
            f"expected one block with stable ID {block_id}, found {len(matches)}"
        )
    return matches[0]


def _empty_block_prototype(block: Block) -> Block:
    """Keep adjacent timing/Division context while discarding all note data."""

    row = EmptyRow(stable_id=block.stable_id, raw=b"\x80\x00\x00\x00", span=None)
    return replace(
        block,
        row_count=RawU32.from_value(1),
        rows=(row,),
        span=None,
    )


def insert_empty_block_after(
    document: NX20Document, target: StructureTarget
) -> InsertBlock:
    if target.block_id is None:
        raise StructureEditError("an empty block insertion requires a selected block")
    _, split = _split(document, target.split_id)
    index, block = _block(split, target.block_id)
    before_id = (
        split.blocks[index + 1].stable_id if index + 1 < len(split.blocks) else None
    )
    return InsertBlock(
        split.stable_id,
        _empty_block_prototype(block),
        before_block_id=before_id,
    )


def insert_empty_split_after(
    document: NX20Document, target: StructureTarget
) -> InsertSplit:
    split_index, split = _split(document, target.split_id)
    if target.block_id is not None:
        _, source_block = _block(split, target.block_id)
    elif split.blocks:
        source_block = split.blocks[0]
    else:
        raise StructureEditError("cannot derive a new split from a split with no blocks")
    prototype = replace(
        split,
        block_count=RawU32.from_value(1),
        blocks=(_empty_block_prototype(source_block),),
        span=None,
    )
    before_id = (
        document.splits[split_index + 1].stable_id
        if split_index + 1 < len(document.splits)
        else None
    )
    return InsertSplit(prototype, before_split_id=before_id)


def remove_split(document: NX20Document, target: StructureTarget) -> RemoveSplit:
    _split(document, target.split_id)
    if len(document.splits) <= 1:
        raise StructureEditError("a chart must retain at least one split")
    return RemoveSplit(target.split_id)


def remove_block(document: NX20Document, target: StructureTarget) -> RemoveBlock:
    if target.block_id is None:
        raise StructureEditError("a block removal requires a selected block")
    _, split = _split(document, target.split_id)
    _block(split, target.block_id)
    if len(split.blocks) <= 1:
        raise StructureEditError("a split must retain at least one block")
    return RemoveBlock(target.block_id)


def move_split(
    document: NX20Document, target: StructureTarget, delta: int
) -> MoveSplit | None:
    if delta not in (-1, 1):
        raise ValueError("a split move delta must be -1 or 1")
    index, _ = _split(document, target.split_id)
    destination = index + delta
    if not 0 <= destination < len(document.splits):
        return None
    before_id = (
        document.splits[destination].stable_id
        if delta < 0
        else document.splits[destination + 1].stable_id
        if destination + 1 < len(document.splits)
        else None
    )
    return MoveSplit(target.split_id, before_split_id=before_id)


def move_block(
    document: NX20Document, target: StructureTarget, delta: int
) -> MoveBlock | None:
    if delta not in (-1, 1):
        raise ValueError("a block move delta must be -1 or 1")
    if target.block_id is None:
        raise StructureEditError("a block move requires a selected block")
    _, split = _split(document, target.split_id)
    index, _ = _block(split, target.block_id)
    destination = index + delta
    if not 0 <= destination < len(split.blocks):
        return None
    before_id = (
        split.blocks[destination].stable_id
        if delta < 0
        else split.blocks[destination + 1].stable_id
        if destination + 1 < len(split.blocks)
        else None
    )
    return MoveBlock(target.block_id, split.stable_id, before_block_id=before_id)
