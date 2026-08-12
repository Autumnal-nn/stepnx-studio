from __future__ import annotations

import unittest

from stepnx.authoring.structure import (
    StructureEditError,
    StructureTarget,
    insert_empty_block_after,
    insert_empty_split_after,
    move_block,
    move_split,
    remove_block,
    remove_split,
)
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.commands import CommandStack, InsertBlock, InsertSplit
from stepnx.core.model import EmptyRow
from stepnx.core.validation import validate
from tests.fixture_factory import make_normal_nx20


class StructureAuthoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = parse_bytes(
            make_normal_nx20(sized_trailer=False), row_storage="compact"
        )
        self.split = self.document.splits[0]
        self.block = self.split.blocks[0]
        self.target = StructureTarget(self.split.stable_id, self.block.stable_id)

    def test_empty_block_insertion_preserves_context_but_not_notes(self) -> None:
        edited = insert_empty_block_after(self.document, self.target).apply(self.document)

        self.assertEqual(len(edited.splits[0].blocks), 2)
        inserted = edited.splits[0].blocks[1]
        self.assertEqual(inserted.bpm.value, self.block.bpm.value)
        self.assertEqual(inserted.beat_split.value, self.block.beat_split.value)
        self.assertEqual(len(inserted.divisions), len(self.block.divisions))
        self.assertEqual(len(inserted.rows), 1)
        self.assertIsInstance(inserted.rows[0], EmptyRow)
        self.assertNotEqual(inserted.stable_id, self.block.stable_id)
        self.assertTrue(validate(edited).is_valid)

    def test_empty_split_insertion_keeps_split_context_and_one_empty_block(self) -> None:
        edited = insert_empty_split_after(self.document, self.target).apply(self.document)

        self.assertEqual(len(edited.splits), 2)
        inserted = edited.splits[1]
        self.assertEqual(inserted.raw_select.value, self.split.raw_select.value)
        self.assertEqual(len(inserted.metadata), len(self.split.metadata))
        self.assertEqual(len(inserted.blocks), 1)
        self.assertEqual(len(inserted.blocks[0].rows), 1)
        self.assertIsInstance(inserted.blocks[0].rows[0], EmptyRow)
        self.assertTrue(validate(edited).is_valid)

    def test_split_and_block_moves_use_stable_anchors(self) -> None:
        with_split = InsertSplit(self.split).apply(self.document)
        second_split = with_split.splits[1]
        moved_split = move_split(
            with_split, StructureTarget(second_split.stable_id), -1
        ).apply(with_split)
        self.assertEqual(moved_split.splits[0].stable_id, second_split.stable_id)
        self.assertIsNone(
            move_split(moved_split, StructureTarget(second_split.stable_id), -1)
        )

        with_block = InsertBlock(self.split.stable_id, self.block).apply(self.document)
        second_block = with_block.splits[0].blocks[1]
        moved_block = move_block(
            with_block,
            StructureTarget(self.split.stable_id, second_block.stable_id),
            -1,
        ).apply(with_block)
        self.assertEqual(moved_block.splits[0].blocks[0].stable_id, second_block.stable_id)

    def test_last_split_and_last_block_cannot_be_removed(self) -> None:
        with self.assertRaisesRegex(StructureEditError, "at least one split"):
            remove_split(self.document, self.target)
        with self.assertRaisesRegex(StructureEditError, "at least one block"):
            remove_block(self.document, self.target)

    def test_structural_commands_remain_one_step_undoable(self) -> None:
        stack = CommandStack(self.document)
        edited = stack.execute(insert_empty_block_after(self.document, self.target))
        self.assertEqual(len(edited.splits[0].blocks), 2)
        self.assertEqual(serialize(stack.undo()), serialize(self.document))
        self.assertEqual(serialize(stack.redo()), serialize(edited))

        second = edited.splits[0].blocks[1]
        removed = stack.execute(
            remove_block(
                edited,
                StructureTarget(self.split.stable_id, second.stable_id),
            )
        )
        self.assertEqual(len(removed.splits[0].blocks), 1)
