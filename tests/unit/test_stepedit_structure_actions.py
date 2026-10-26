from __future__ import annotations

import unittest

from stepnx.authoring.editor_controller import EditorController
from stepnx.authoring.structure import StructureTarget, insert_empty_split_after
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.commands import CommandStack
from stepnx.gui.stepedit_structure_actions import plan_structure_action
from tests.fixture_factory import make_normal_nx20, make_large_playable


class StepEditStructuralMenuTests(unittest.TestCase):
    def setUp(self):
        doc = parse_bytes(make_large_playable(rows=64), row_storage="compact")
        self.controller = EditorController(CommandStack(doc))
        self.source = doc
        self.split = doc.splits[0]
        self.block = self.split.blocks[0]

    def plan(self, action, *, requested_rows=None, row_index=None):
        return plan_structure_action(
            self.controller.document,
            action, self.split.stable_id, self.block.stable_id,
            requested_rows=requested_rows, row_index=row_index,
        )

    def test_insert_and_delete_block_roundtrips_with_one_undo_per_action(self):
        original = serialize(self.source)
        command = self.plan("insert-block")
        self.assertIsNone(command.confirmation)
        changed = self.controller.execute(command.command)
        self.assertEqual(len(changed.splits[0].blocks), 2)
        self.assertEqual(
            len(changed.splits[0].blocks[0].rows),
            len(changed.splits[0].blocks[1].rows),
        )
        self.assertEqual(serialize(self.controller.undo()), original)
        self.assertEqual(serialize(self.controller.redo()), serialize(changed))
        inserted = self.controller.document.splits[0].blocks[1]
        deletion = plan_structure_action(
            self.controller.document, "delete-block",
            self.split.stable_id, inserted.stable_id,
        )
        self.assertIsNotNone(deletion.confirmation)
        self.controller.execute(deletion.command)
        self.assertEqual(serialize(self.controller.document), original)

    def test_duplicate_block_is_an_independent_copy(self):
        original = serialize(self.source)
        plan = self.plan("duplicate-block")
        doc = self.controller.execute(plan.command)
        self.assertEqual(len(doc.splits[0].blocks), 2)
        a, b = doc.splits[0].blocks
        self.assertNotEqual(a.stable_id, b.stable_id)
        self.assertNotEqual(a.rows[0].stable_id, b.rows[0].stable_id)
        self.assertEqual(serialize(self.controller.undo()), original)

    def test_split_here_preserves_rows_and_is_single_undo(self):
        before = serialize(self.source)
        plan = self.plan("split-here", row_index=20)
        result = self.controller.execute(plan.command)
        self.assertEqual(len(result.splits), 2)
        self.assertEqual(len(result.splits[0].blocks[0].rows), 20)
        self.assertEqual(len(result.splits[1].blocks[0].rows), 44)
        self.assertEqual(serialize(self.controller.undo()), before)

    def test_new_split_delete_and_merge_are_explicitly_warning_gated(self):
        plan = self.plan("insert-split")
        self.assertIsNotNone(plan.confirmation)
        result = self.controller.execute(plan.command)
        self.assertEqual(len(result.splits), 2)
        plan = self.plan("merge-splits")
        self.assertIn("discard", plan.confirmation)
        self.controller.execute(plan.command)
        self.assertEqual(len(self.controller.document.splits), 1)
        self.controller.undo()
        result = self.controller.document
        delete = plan_structure_action(
            result, "delete-split",
            result.splits[1].stable_id,
            result.splits[1].blocks[0].stable_id,
        )
        self.assertIsNotNone(delete.confirmation)
        self.controller.execute(delete.command)
        self.assertEqual(len(self.controller.document.splits), 1)

    def test_resize_split_shifts_every_downstream_block_as_one_command(self):
        doc = self.plan("insert-split").command.apply(self.source)
        doc = self.plan("insert-split").command.apply(doc)
        self.controller = EditorController(CommandStack(doc))
        before = serialize(doc)
        old = [
            float(s.blocks[0].start_time.value)
            for s in doc.splits[1:]
        ]
        action = self.plan("resize-split", requested_rows=72)
        self.assertIsNotNone(action.confirmation)
        self.assertEqual(action.actual_rows, 72)
        after = self.controller.execute(action.command)
        self.assertEqual(len(after.splits[0].blocks[0].rows), 72)
        self.assertEqual(len(after.splits), 3)
        for index, split in enumerate(after.splits[1:]):
            shift = float(split.blocks[0].start_time.value) - old[index]
            self.assertGreater(shift, 0)
        self.assertEqual(serialize(self.controller.undo()), before)

    def test_resize_truncation_is_never_silent(self):
        self.controller = EditorController(CommandStack(
            self.plan("insert-split").command.apply(self.source)
        ))
        plan = self.plan("resize-split", requested_rows=40)
        self.assertIsNotNone(plan.confirmation)
        self.assertIn("truncates", plan.confirmation)
        self.assertEqual(len(self.controller.document.splits[0].blocks[0].rows), 64)

    def test_invalid_structural_targets_fail_without_edits(self):
        before = serialize(self.source)
        for action, idx, rows in (
            ("split-here", 0, None),
            ("split-here", 64, None),
            ("resize-split", None, 0),
            ("delete-block", None, None),
            ("delete-split", None, None),
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.plan(action, row_index=idx, requested_rows=rows)
        self.assertEqual(serialize(self.controller.document), before)


if __name__ == "__main__":
    unittest.main()
