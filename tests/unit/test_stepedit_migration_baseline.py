from __future__ import annotations

import unittest

from stepnx.authoring.snapshot import create_authoring_snapshot
from stepnx.authoring.timeline import TimelineGeometry, TimelineLayout
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.commands import CommandStack, InsertBlock, NoteEdit, SetNoteAt, SetNotesAt
from tests.fixture_factory import make_normal_nx20


class StepEditMigrationBaselineTests(unittest.TestCase):
    """Stable engine contracts shared by the current and future editor surfaces.

    These are core-level baselines, not a claim that the StepEdit UI exists.
    """

    @staticmethod
    def _document(*, sized_trailer: bool = True):
        return parse_bytes(
            make_normal_nx20(sized_trailer=sized_trailer),
            row_storage="compact",
        )

    def test_opening_without_edits_is_byte_exact_with_or_without_sized_trailer(self) -> None:
        for sized in (False, True):
            with self.subTest(sized_trailer=sized):
                source = make_normal_nx20(sized_trailer=sized)
                self.assertEqual(
                    serialize(parse_bytes(source, row_storage="compact")),
                    source,
                )

    def test_branch_navigation_only_changes_authoring_projection(self) -> None:
        original = self._document()
        split = original.splits[0]
        branched = InsertBlock(split.stable_id, split.blocks[0]).apply(original)
        source_bytes = serialize(branched)
        blocks = branched.splits[0].blocks

        first = create_authoring_snapshot(branched)
        second = first.with_active_block(split.stable_id, blocks[1].stable_id)

        self.assertEqual(first.active_block_id(split.stable_id), blocks[0].stable_id)
        self.assertEqual(second.active_block_id(split.stable_id), blocks[1].stable_id)
        self.assertEqual(
            second.cycle_block(split.stable_id).active_block_id(split.stable_id),
            blocks[0].stable_id,
        )
        self.assertEqual(serialize(branched), source_bytes)

    def test_editing_a_hidden_alternative_does_not_touch_visible_block(self) -> None:
        original = self._document()
        split = original.splits[0]
        branched = InsertBlock(split.stable_id, split.blocks[0]).apply(original)
        first, second = branched.splits[0].blocks
        first_row_before = first.rows[0]

        changed = SetNoteAt(
            second.rows[0].stable_id, 0, b"\x43\x04\x01\x00"
        ).apply(branched)

        self.assertEqual(
            tuple(cell.raw for cell in changed.splits[0].blocks[0].rows[0].cells),
            tuple(cell.raw for cell in first_row_before.cells),
        )
        self.assertEqual(
            changed.splits[0].blocks[1].rows[0].cells[0].raw,
            b"\x43\x04\x01\x00",
        )
        self.assertEqual(first.stable_id, changed.splits[0].blocks[0].stable_id)

    def test_bulk_edit_is_one_undo_step_and_preserves_unedited_raw_cells(self) -> None:
        original = self._document(sized_trailer=False)
        first, empty = original.splits[0].blocks[0].rows
        original_untouched = first.cell(4).raw
        stack = CommandStack(original)

        edited = stack.execute(
            SetNotesAt(
                (
                    NoteEdit(first.stable_id, 0, b"\x43\x04\x01\x00"),
                    NoteEdit(empty.stable_id, 3, b"\x41\x04\x09\x00"),
                )
            )
        )
        self.assertEqual(
            edited.splits[0].blocks[0].rows[0].cells[4].raw,
            original_untouched,
        )
        final_bytes = serialize(edited)
        self.assertNotEqual(final_bytes, serialize(original))
        self.assertEqual(serialize(stack.undo()), serialize(original))
        self.assertFalse(stack.can_undo)
        self.assertEqual(serialize(stack.redo()), final_bytes)

    def test_each_paint_stroke_has_an_independent_undo_boundary(self) -> None:
        original = self._document(sized_trailer=False)
        row = original.splits[0].blocks[0].rows[0]
        stack = CommandStack(original)

        stack.execute(
            SetNoteAt(row.stable_id, 0, b"\x43\x04\x01\x00"),
            coalesce_key="first-stroke",
        )
        first_stroke = stack.execute(
            SetNoteAt(row.stable_id, 1, b"\x43\x04\x01\x00"),
            coalesce_key="first-stroke",
        )
        stack.finish_coalescing()
        stack.execute(
            SetNoteAt(row.stable_id, 2, b"\x43\x04\x01\x00"),
            coalesce_key="second-stroke",
        )
        stack.finish_coalescing()

        self.assertEqual(serialize(stack.undo()), serialize(first_stroke))
        self.assertEqual(serialize(stack.undo()), serialize(original))
        self.assertFalse(stack.can_undo)

    def test_viewport_zoom_does_not_change_serialized_document(self) -> None:
        original = self._document()
        source_bytes = serialize(original)
        snapshot = create_authoring_snapshot(original)
        regular = TimelineLayout(snapshot, TimelineGeometry(row_height=24))
        zoomed = TimelineLayout(snapshot, regular.geometry.zoomed(2))

        self.assertEqual(
            regular.segments[0].block.stable_id,
            zoomed.segments[0].block.stable_id,
        )
        self.assertGreater(zoomed.segments[0].row_height, regular.segments[0].row_height)
        self.assertEqual(serialize(original), source_bytes)


if __name__ == "__main__":
    unittest.main()
