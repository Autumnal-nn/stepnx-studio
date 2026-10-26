from __future__ import annotations

import unittest

from stepnx.authoring.editor_controller import EditorController
from stepnx.authoring.stepedit_hold import (
    HoldGestureError, plan_hold_creation, plan_hold_erasure,
)
from stepnx.authoring.tools import NoteTool, note_tool_raw
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.commands import CommandStack, SetNoteAt
from tests.fixture_factory import make_large_playable


_TYPES = {
    7: NoteTool.HOLD_HEAD,
    0xB: NoteTool.HOLD_BODY,
    0xF: NoteTool.HOLD_TAIL,
}


def hold_raw(kind):
    return note_tool_raw(_TYPES[kind])


class StepEditHoldPlannerTests(unittest.TestCase):
    def setUp(self):
        self.document = parse_bytes(make_large_playable(rows=64), row_storage="compact")
        self.controller = EditorController(CommandStack(self.document))
        self.split = self.document.splits[0]
        self.block = self.split.blocks[0]
        self.scope = self.controller.capture_scope(
            self.split.stable_id, self.block.stable_id
        )

    def test_reversed_drag_places_complete_hold_and_one_undo(self):
        edits = plan_hold_creation(self.block, 1, 7, 2, hold_raw)
        self.assertEqual(len(edits), 6)
        self.assertEqual(
            [edit.raw[0] & 0x0F for edit in edits],
            [7, 0xB, 0xB, 0xB, 0xB, 0xF],
        )
        original = serialize(self.document)
        changed = self.controller.apply_note_batch(self.scope, edits)
        self.assertNotEqual(serialize(changed), original)
        self.assertEqual(serialize(self.controller.undo()), original)
        self.assertFalse(self.controller._stack.can_undo)
        self.assertEqual(serialize(self.controller.redo()), serialize(changed))

    def test_erasure_from_middle_removes_exact_complete_hold(self):
        edits = plan_hold_creation(self.block, 1, 2, 6, hold_raw)
        self.controller.apply_note_batch(self.scope, edits)
        new_block = self.controller.document.splits[0].blocks[0]
        erase = plan_hold_erasure(new_block, 1, 4)
        self.assertEqual(len(erase), 5)
        self.assertTrue(all(edit.raw == b"\0" * 4 for edit in erase))
        new_scope = self.controller.capture_scope(self.split.stable_id, self.block.stable_id)
        self.controller.apply_note_batch(new_scope, erase)
        self.assertEqual(serialize(self.controller.document), serialize(self.document))

    def test_occupied_tap_cancels_entire_creation(self):
        occupied_row = self.block.rows[4]
        self.controller._stack.execute(
            SetNoteAt(occupied_row.stable_id, 1, b"\x43\x03\x00\x00")
        )
        self.controller.sync_external_change()
        modified = self.controller.document.splits[0].blocks[0]
        before = serialize(self.controller.document)
        with self.assertRaisesRegex(HoldGestureError, "empty"):
            plan_hold_creation(modified, 1, 2, 6, hold_raw)
        self.assertEqual(serialize(self.controller.document), before)

    def test_opaque_nonzero_type_zero_cannot_be_overwritten(self):
        row = self.block.rows[4]
        self.controller._stack.execute(
            SetNoteAt(row.stable_id, 1, b"\x00\x02\x03\x04")
        )
        changed = self.controller.document.splits[0].blocks[0]
        with self.assertRaises(HoldGestureError):
            plan_hold_creation(changed, 1, 2, 6, hold_raw)

    def test_incomplete_hold_cannot_be_partially_erased(self):
        row = self.block.rows[3]
        self.controller._stack.execute(
            SetNoteAt(row.stable_id, 1, hold_raw(0xB))
        )
        changed = self.controller.document.splits[0].blocks[0]
        with self.assertRaisesRegex(HoldGestureError, "incomplete"):
            plan_hold_erasure(changed, 1, 3)

    def test_invalid_raw_part_and_missing_endpoint_are_rejected(self):
        with self.assertRaises(HoldGestureError):
            plan_hold_creation(self.block, 1, 4, 4, hold_raw)
        with self.assertRaises(HoldGestureError):
            plan_hold_creation(self.block, 1, 4, 99, hold_raw)
        with self.assertRaises(HoldGestureError):
            plan_hold_creation(self.block, 1, 2, 4, lambda _: b"\x43\x03\x00\x00")

    def test_invalid_batch_never_commits_an_existing_note(self):
        edits = plan_hold_creation(self.block, 1, 2, 6, hold_raw)
        with self.assertRaises(ValueError):
            self.controller.apply_note_batch(self.scope, edits + edits[:1])
        self.assertEqual(serialize(self.controller.document), serialize(self.document))
        self.assertFalse(self.controller._stack.can_undo)


if __name__ == "__main__":
    unittest.main()
