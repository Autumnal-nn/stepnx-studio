from __future__ import annotations

import unittest

from stepnx.authoring.editor_controller import (
    EditorContextError,
    EditorController,
    InteractionProfile,
    InteractionTool,
)
from stepnx.authoring.selection import CellTarget
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.commands import CommandStack, InsertBlock, SetNoteAt
from tests.fixture_factory import make_implicit_lightmap, make_normal_nx20


class EditorControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = parse_bytes(
            make_normal_nx20(sized_trailer=True), row_storage="compact"
        )
        self.stack = CommandStack(self.original)
        self.controller = EditorController(self.stack)
        self.split = self.original.splits[0]
        self.block = self.split.blocks[0]
        self.first = CellTarget(self.block.rows[0].stable_id, 0)
        self.second = CellTarget(self.block.rows[1].stable_id, 3)

    def test_initial_session_is_not_serialized(self) -> None:
        before = serialize(self.stack.current)
        self.controller.set_profile(InteractionProfile.STEPEDIT_CLASSIC)
        self.controller.set_tool(InteractionTool.ADD)
        self.controller.session.hover = self.first
        self.controller.session.keyboard_target = self.second
        self.controller.session.scroll_y = 123.5
        self.controller.session.zoom = 2.0
        self.assertEqual(serialize(self.stack.current), before)

    def test_exact_note_placement_delegates_to_existing_command_stack(self) -> None:
        edited = self.controller.set_note(
            self.split.stable_id, self.block.stable_id, self.first,
            b"\x43\x04\x01\x00",
        )
        self.assertEqual(
            edited.splits[0].blocks[0].rows[0].cells[0].raw,
            b"\x43\x04\x01\x00",
        )
        self.assertEqual(serialize(self.controller.undo()), serialize(self.original))
        self.assertEqual(serialize(self.controller.redo()), serialize(edited))

    def test_stroke_keeps_document_unchanged_until_atomic_commit(self) -> None:
        before = serialize(self.stack.current)
        self.controller.start_stroke(
            self.split.stable_id, self.block.stable_id,
            self.first, b"\x43\x04\x01\x00",
        )
        self.controller.extend_stroke(self.second)
        self.controller.extend_stroke(self.second)
        self.assertEqual(len(self.controller.session.gesture.targets), 2)
        self.assertEqual(serialize(self.stack.current), before)
        final = self.controller.finish_stroke()
        self.assertEqual(
            final.splits[0].blocks[0].rows[1].cells[3].raw,
            b"\x43\x04\x01\x00",
        )
        self.assertIsNone(self.controller.session.gesture)
        self.assertEqual(serialize(self.controller.undo()), before)
        self.assertFalse(self.stack.can_undo)

    def test_cancel_stroke_has_no_side_effects(self) -> None:
        before = serialize(self.stack.current)
        self.controller.start_stroke(
            self.split.stable_id, self.block.stable_id,
            self.first, b"\x43\x04\x01\x00",
        )
        self.controller.extend_stroke(self.second)
        self.controller.cancel_stroke()
        self.assertIsNone(self.controller.session.gesture)
        self.assertEqual(serialize(self.stack.current), before)
        self.assertFalse(self.stack.can_undo)

    def test_two_strokes_are_separate_undo_steps(self) -> None:
        before = serialize(self.stack.current)
        self.controller.start_stroke(
            self.split.stable_id, self.block.stable_id,
            self.first, b"\x43\x04\x01\x00",
        )
        first_state = self.controller.finish_stroke()
        self.controller.start_stroke(
            self.split.stable_id, self.block.stable_id,
            self.second, b"\x43\x04\x01\x00",
        )
        self.controller.finish_stroke()
        self.assertEqual(serialize(self.controller.undo()), serialize(first_state))
        self.assertEqual(serialize(self.controller.undo()), before)

    def test_wrong_lane_and_wrong_row_are_rejected_without_mutation(self) -> None:
        before = serialize(self.stack.current)
        for target in (CellTarget(self.first.row_id, 99), CellTarget(999_999_999, 0)):
            with self.subTest(target=target), self.assertRaises(EditorContextError):
                self.controller.set_note(
                    self.split.stable_id, self.block.stable_id,
                    target, b"\x43\x04\x01\x00",
                )
        self.assertEqual(serialize(self.stack.current), before)
        self.assertFalse(self.stack.can_undo)

    def test_branch_switch_cancels_pending_stroke_and_keeps_data(self) -> None:
        new_doc = InsertBlock(self.split.stable_id, self.block).apply(self.stack.current)
        controller = EditorController(CommandStack(new_doc))
        split = new_doc.splits[0]
        first_block, second_block = split.blocks
        before = serialize(controller.document)
        controller.start_stroke(
            split.stable_id, first_block.stable_id,
            CellTarget(first_block.rows[0].stable_id, 0), b"\x43\x04\x01\x00",
        )
        controller.select_block(split.stable_id, second_block.stable_id)
        self.assertIsNone(controller.session.gesture)
        self.assertEqual(
            controller.snapshot.active_block_id(split.stable_id),
            second_block.stable_id,
        )
        self.assertEqual(serialize(controller.document), before)
        with self.assertRaises(EditorContextError):
            controller.finish_stroke()

    def test_hidden_branch_target_is_rejected(self) -> None:
        new_doc = InsertBlock(self.split.stable_id, self.block).apply(self.stack.current)
        controller = EditorController(CommandStack(new_doc))
        split = new_doc.splits[0]
        before = serialize(controller.document)
        hidden_row_id = split.blocks[1].rows[0].stable_id
        with self.assertRaises(EditorContextError):
            controller.set_note(
                split.stable_id, split.blocks[1].stable_id,
                CellTarget(hidden_row_id, 0), b"\x43\x04\x01\x00",
            )
        self.assertEqual(serialize(controller.document), before)

    def test_selected_branch_survives_a_note_edit_and_undo(self) -> None:
        new_doc = InsertBlock(self.split.stable_id, self.block).apply(self.stack.current)
        controller = EditorController(CommandStack(new_doc))
        split = new_doc.splits[0]
        selected = split.blocks[1]
        controller.select_block(split.stable_id, selected.stable_id)
        controller.set_note(
            split.stable_id, selected.stable_id,
            CellTarget(selected.rows[0].stable_id, 0), b"\x43\x04\x01\x00",
        )
        controller.undo()
        self.assertEqual(
            controller.snapshot.active_block_id(split.stable_id), selected.stable_id
        )

    def test_external_changes_require_explicit_resynchronization(self) -> None:
        self.stack.execute(
            SetNoteAt(self.first.row_id, self.first.lane, b"\x43\x04\x01\x00")
        )
        with self.assertRaisesRegex(EditorContextError, "sync_external_change"):
            self.controller.set_note(
                self.split.stable_id, self.block.stable_id,
                self.second, b"\x43\x04\x01\x00",
            )
        self.controller.sync_external_change()
        self.controller.set_note(
            self.split.stable_id, self.block.stable_id,
            self.second, b"\x43\x04\x01\x00",
        )
        self.assertEqual(
            self.controller.document.splits[0].blocks[0].rows[1].cells[3].raw,
            b"\x43\x04\x01\x00",
        )

    def test_lightmap_does_not_pass_through_note_writer(self) -> None:
        doc = parse_bytes(make_implicit_lightmap(), row_storage="compact")
        controller = EditorController(CommandStack(doc))
        block = doc.splits[0].blocks[0]
        with self.assertRaisesRegex(EditorContextError, "Lightmap"):
            controller.set_note(
                doc.splits[0].stable_id, block.stable_id,
                CellTarget(block.rows[0].stable_id, 0), b"\x43\x04\x01\x00",
            )
        self.assertEqual(serialize(controller.document), serialize(doc))


if __name__ == "__main__":
    unittest.main()
