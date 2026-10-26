from __future__ import annotations

import unittest
from unittest.mock import patch

from stepnx.authoring.editor_controller import (
    EditorContextError,
    EditorController,
    InteractionProfile,
    InteractionTool,
)
from stepnx.authoring.selection import CellTarget
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.commands import CommandStack, InsertBlock, SetNoteAt
from stepnx.core.model import CompactRows, OverlayRows
from tests.fixture_factory import make_implicit_lightmap, make_large_playable, make_normal_nx20


_RAW = b"\x43\x04\x01\x00"


class EditorControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = parse_bytes(make_normal_nx20(), row_storage="compact")
        self.stack = CommandStack(self.original)
        self.controller = EditorController(self.stack)
        self.split = self.original.splits[0]
        self.block = self.split.blocks[0]
        self.first = CellTarget(self.block.rows[0].stable_id, 0)
        self.second = CellTarget(self.block.rows[1].stable_id, 3)
        self.scope = self.controller.capture_scope(self.split.stable_id, self.block.stable_id)

    def test_initial_session_is_not_serialized(self) -> None:
        source = serialize(self.original)
        self.controller.set_profile(InteractionProfile.STEPEDIT_CLASSIC)
        self.controller.set_tool(InteractionTool.ADD)
        self.controller.session.hover = self.first
        self.controller.session.keyboard_target = self.second
        self.controller.session.scroll_y = 123.5
        self.controller.session.zoom = 2.0
        self.assertEqual(serialize(self.controller.document), source)

    def test_exact_note_placement_is_undoable(self) -> None:
        edited = self.controller.set_note(self.scope, self.first, _RAW)
        self.assertEqual(edited.splits[0].blocks[0].rows[0].cells[0].raw, _RAW)
        self.assertEqual(serialize(self.controller.undo()), serialize(self.original))
        self.assertEqual(serialize(self.controller.redo()), serialize(edited))

    def test_stroke_is_preview_only_until_one_atomic_commit(self) -> None:
        before = serialize(self.original)
        lease = self.controller.start_stroke(self.scope, self.first, _RAW)
        self.controller.extend_stroke(lease, self.second)
        self.controller.extend_stroke(lease, self.second)
        self.assertEqual(len(self.controller.session.gesture.targets), 2)
        self.assertEqual(serialize(self.stack.current), before)
        final = self.controller.finish_stroke(lease)
        self.assertEqual(final.splits[0].blocks[0].rows[1].cells[3].raw, _RAW)
        self.assertIsNone(self.controller.session.gesture)
        self.assertEqual(serialize(self.controller.undo()), before)
        self.assertFalse(self.stack.can_undo)

    def test_cancel_stroke_changes_neither_document_nor_history(self) -> None:
        before = serialize(self.original)
        lease = self.controller.start_stroke(self.scope, self.first, _RAW)
        self.controller.extend_stroke(lease, self.second)
        self.controller.cancel_stroke()
        self.assertEqual(serialize(self.controller.document), before)
        self.assertFalse(self.stack.can_undo)
        with self.assertRaises(EditorContextError):
            self.controller.finish_stroke(lease)

    def test_two_strokes_have_independent_undo_steps(self) -> None:
        before = serialize(self.original)
        lease = self.controller.start_stroke(self.scope, self.first, _RAW)
        first = self.controller.finish_stroke(lease)
        scope = self.controller.capture_scope(self.split.stable_id, self.block.stable_id)
        lease = self.controller.start_stroke(scope, self.second, _RAW)
        self.controller.finish_stroke(lease)
        self.assertEqual(serialize(self.controller.undo()), serialize(first))
        self.assertEqual(serialize(self.controller.undo()), before)

    def test_wrong_lane_and_row_rejected_before_mutation(self) -> None:
        before = serialize(self.original)
        for target in (CellTarget(self.first.row_id, 99), CellTarget(999_999_999, 0)):
            with self.subTest(target=target), self.assertRaises(EditorContextError):
                self.controller.set_note(self.scope, target, _RAW)
        self.assertEqual(serialize(self.controller.document), before)
        self.assertFalse(self.stack.can_undo)

    def test_branch_switch_cancels_stroke_and_revokes_scope(self) -> None:
        doc = InsertBlock(self.split.stable_id, self.block).apply(self.original)
        controller = EditorController(CommandStack(doc))
        split = doc.splits[0]
        first_block, second_block = split.blocks
        scope = controller.capture_scope(split.stable_id, first_block.stable_id)
        before = serialize(doc)
        lease = controller.start_stroke(scope, CellTarget(first_block.rows[0].stable_id, 0), _RAW)
        controller.select_block(split.stable_id, second_block.stable_id)
        self.assertIsNone(controller.session.gesture)
        self.assertEqual(serialize(controller.document), before)
        with self.assertRaises(EditorContextError):
            controller.finish_stroke(lease)
        with self.assertRaises(EditorContextError):
            controller.set_note(scope, CellTarget(first_block.rows[0].stable_id, 0), _RAW)

    def test_hidden_branch_is_not_targetable(self) -> None:
        doc = InsertBlock(self.split.stable_id, self.block).apply(self.original)
        controller = EditorController(CommandStack(doc))
        split = doc.splits[0]
        with self.assertRaises(EditorContextError):
            controller.capture_scope(split.stable_id, split.blocks[1].stable_id)
        self.assertEqual(serialize(controller.document), serialize(doc))

    def test_active_branch_survives_note_edit_and_undo(self) -> None:
        doc = InsertBlock(self.split.stable_id, self.block).apply(self.original)
        controller = EditorController(CommandStack(doc))
        split = doc.splits[0]
        selected = split.blocks[1]
        controller.select_block(split.stable_id, selected.stable_id)
        scope = controller.capture_scope(split.stable_id, selected.stable_id)
        controller.set_note(scope, CellTarget(selected.rows[0].stable_id, 0), _RAW)
        controller.undo()
        self.assertEqual(controller.snapshot.active_block_id(split.stable_id), selected.stable_id)

    def test_external_mutation_requires_resync_and_revokes_scope(self) -> None:
        self.stack.execute(SetNoteAt(self.first.row_id, self.first.lane, _RAW))
        with self.assertRaisesRegex(EditorContextError, "sync_external_change"):
            self.controller.set_note(self.scope, self.second, _RAW)
        self.controller.sync_external_change()
        with self.assertRaises(EditorContextError):
            self.controller.set_note(self.scope, self.second, _RAW)
        scope = self.controller.capture_scope(self.split.stable_id, self.block.stable_id)
        edited = self.controller.set_note(scope, self.second, _RAW)
        self.assertEqual(edited.splits[0].blocks[0].rows[1].cells[3].raw, _RAW)

    def test_lightmap_requires_separate_editor(self) -> None:
        doc = parse_bytes(make_implicit_lightmap(), row_storage="compact")
        controller = EditorController(CommandStack(doc))
        split = doc.splits[0]
        block = split.blocks[0]
        scope = controller.capture_scope(split.stable_id, block.stable_id)
        with self.assertRaisesRegex(EditorContextError, "Lightmap"):
            controller.set_note(scope, CellTarget(block.rows[0].stable_id, 0), _RAW)
        self.assertEqual(serialize(controller.document), serialize(doc))

    def test_same_stable_ids_in_different_documents_cannot_alias(self) -> None:
        other_doc = parse_bytes(make_normal_nx20(), row_storage="compact")
        other = EditorController(CommandStack(other_doc))
        self.assertEqual(self.original.stable_id, other_doc.stable_id)
        self.assertEqual(self.split.stable_id, other_doc.splits[0].stable_id)
        with self.assertRaisesRegex(EditorContextError, "stale editor event"):
            other.set_note(self.scope, self.first, _RAW)
        self.assertEqual(serialize(other.document), serialize(other_doc))

    def test_binding_new_chart_revokes_old_event_even_if_stable_ids_repeat(self) -> None:
        other_doc = parse_bytes(make_normal_nx20(), row_storage="compact")
        self.controller.bind_document(CommandStack(other_doc))
        with self.assertRaisesRegex(EditorContextError, "stale editor event"):
            self.controller.set_note(self.scope, self.first, _RAW)
        self.assertEqual(serialize(self.controller.document), serialize(other_doc))
        new_scope = self.controller.capture_scope(self.split.stable_id, self.block.stable_id)
        self.controller.set_note(new_scope, self.first, _RAW)

    def test_stale_release_from_cancelled_stroke_cannot_commit_new_stroke(self) -> None:
        old_lease = self.controller.start_stroke(self.scope, self.first, _RAW)
        self.controller.cancel_stroke()
        new_scope = self.controller.capture_scope(self.split.stable_id, self.block.stable_id)
        new_lease = self.controller.start_stroke(new_scope, self.second, _RAW)
        with self.assertRaises(EditorContextError):
            self.controller.finish_stroke(old_lease)
        self.assertEqual(serialize(self.controller.document), serialize(self.original))
        self.controller.finish_stroke(new_lease)

    def test_previous_event_cannot_commit_after_undo_or_new_note(self) -> None:
        self.controller.set_note(self.scope, self.first, _RAW)
        with self.assertRaisesRegex(EditorContextError, "stale editor event"):
            self.controller.set_note(self.scope, self.second, _RAW)
        self.controller.undo()
        with self.assertRaisesRegex(EditorContextError, "stale editor event"):
            self.controller.set_note(self.scope, self.second, _RAW)

    def test_note_commit_undo_redo_never_revalidates_full_snapshot(self) -> None:
        scope = self.scope
        with patch(
            "stepnx.authoring.editor_controller.create_authoring_snapshot",
            side_effect=AssertionError("note edits should reuse the projection"),
        ):
            edited = self.controller.set_note(scope, self.first, _RAW)
            self.assertEqual(self.controller.snapshot.splits[0].blocks[0].rows[0].cells[0].raw, _RAW)
            self.assertEqual(serialize(self.controller.undo()), serialize(self.original))
            self.assertEqual(serialize(self.controller.redo()), serialize(edited))


class EditorSparseBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.original = parse_bytes(
            make_large_playable(rows=200_000, columns=10),
            row_storage="compact",
        )

    def test_fifty_cell_stroke_avoids_complete_row_scans_and_snapshot_rebuild(self) -> None:
        controller = EditorController(CommandStack(self.original))
        split = self.original.splits[0]
        block = split.blocks[0]
        scope = controller.capture_scope(split.stable_id, block.stable_id)
        base = block.rows
        selected_rows = 5
        targets = [
            CellTarget(int(base._row_ids[100_000 + row]), lane)
            for row in range(selected_rows)
            for lane in range(10)
        ]
        getitem = CompactRows.__getitem__
        reads = 0

        def bounded_read(rows, index):
            nonlocal reads
            reads += 1
            self.assertLessEqual(reads, 50 + 12 * selected_rows + 64)
            return getitem(rows, index)

        def forbidden_iter(rows):
            raise AssertionError("cannot iterate the full 200k-row table")

        with (
            patch.object(CompactRows, "__getitem__", bounded_read),
            patch.object(CompactRows, "__iter__", forbidden_iter),
            patch.object(OverlayRows, "__iter__", forbidden_iter),
            patch(
                "stepnx.authoring.editor_controller.create_authoring_snapshot",
                side_effect=AssertionError("slow snapshot reprojection in pointer stroke"),
            ),
        ):
            lease = controller.start_stroke(scope, targets[0], _RAW)
            for target in targets[1:]:
                controller.extend_stroke(lease, target)
            changed = controller.finish_stroke(lease)
            self.assertIsInstance(changed.splits[0].blocks[0].rows, OverlayRows)
            controller.undo()
            controller.redo()


if __name__ == "__main__":
    unittest.main()
