from __future__ import annotations

import unittest
from dataclasses import replace

from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.commands import (
    CommandStack,
    InsertBlock,
    InsertMetadata,
    InsertRow,
    InsertSplit,
    MoveBlock,
    MoveMetadata,
    MoveRow,
    MoveSplit,
    RemoveBlock,
    RemoveMetadata,
    RemoveRow,
    RemoveSplit,
    SetBlockField,
    SetMetadataValue,
    SetNoteCellRaw,
    SetRowRaw,
)
from stepnx.core.diff import diff_documents
from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import NoteRow, OverlayRows
from stepnx.core.scalars import RawF32
from stepnx.core.validation import validate
from tests.fixture_factory import make_implicit_lightmap, make_normal_nx20


class EditingTests(unittest.TestCase):
    def test_metadata_command_roundtrips_through_undo_and_redo(self) -> None:
        source = make_normal_nx20(sized_trailer=False)
        document = parse_bytes(source, row_storage="compact")
        entry = document.header_metadata[1]
        stack = CommandStack(document)

        edited = stack.execute(SetMetadataValue.from_int(entry.stable_id, 123456))
        self.assertNotEqual(serialize(edited), source)
        self.assertEqual(edited.header_metadata[1].stable_id, entry.stable_id)
        self.assertEqual(edited.header_metadata[1].value.value, 123456)
        self.assertIsNone(edited.header_metadata[1].value.span)
        self.assertEqual(serialize(stack.undo()), source)
        self.assertEqual(serialize(stack.redo()), serialize(edited))

    def test_compact_cell_edit_promotes_only_its_row(self) -> None:
        source = make_normal_nx20(sized_trailer=False)
        document = parse_bytes(source, row_storage="compact")
        block = document.splits[0].blocks[0]
        packed = block.rows[0]
        target = packed.cell(2)

        edited = SetNoteCellRaw(target.stable_id, b"\x09\x08\x07\x06").apply(document)
        edited_rows = edited.splits[0].blocks[0].rows
        self.assertIsInstance(edited_rows, OverlayRows)
        self.assertEqual(len(edited_rows.replacements), 1)
        self.assertIsInstance(edited_rows[0], NoteRow)
        self.assertEqual(edited_rows[0].cells[2].stable_id, target.stable_id)
        self.assertEqual(edited_rows[0].cells[2].raw, b"\x09\x08\x07\x06")
        self.assertEqual(edited_rows[1], block.rows[1])

    def test_row_edit_preserves_row_and_cell_ids(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False), row_storage="compact")
        row = document.splits[0].blocks[0].rows[0]
        original_ids = tuple(cell.stable_id for cell in row.cells)
        raw = b"\x01\x00\x00\x00" * 5

        edited = SetRowRaw(row.stable_id, raw).apply(document)
        replacement = edited.splits[0].blocks[0].rows[0]
        self.assertEqual(replacement.stable_id, row.stable_id)
        self.assertEqual(tuple(cell.stable_id for cell in replacement.cells), original_ids)
        self.assertEqual(b"".join(cell.raw for cell in replacement.cells), raw)

    def test_block_field_edit_rejects_the_wrong_scalar_type(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False))
        block = document.splits[0].blocks[0]
        edited = SetBlockField(block.stable_id, "bpm", RawF32.from_value(150.0)).apply(document)
        self.assertEqual(edited.splits[0].blocks[0].bpm.value, 150.0)
        self.assertEqual(edited.splits[0].blocks[0].stable_id, block.stable_id)

    def test_structural_diff_identifies_metadata_and_row_paths(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False), row_storage="compact")
        entry = document.header_metadata[0]
        row = document.splits[0].blocks[0].rows[0]
        changed = SetMetadataValue.from_int(entry.stable_id, 88).apply(document)
        changed = SetNoteCellRaw(row.cell(0).stable_id, b"\x0A\x00\x00\x00").apply(changed)

        paths = {change.path for change in diff_documents(document, changed)}
        self.assertIn("header_metadata[0].value", paths)
        self.assertIn("splits[0].blocks[0].rows[0].raw", paths)

    def test_metadata_collections_use_stable_anchors_and_preserve_duplicate_order(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False))
        owner_id = document.stable_id
        anchor = document.header_metadata[1]
        inserted = InsertMetadata.from_ints(
            owner_id, 900, 8, before_entry_id=anchor.stable_id
        ).apply(document)

        entries = inserted.header_metadata
        self.assertEqual([entry.value.value for entry in entries], [7, 8, 9, 12])
        new_entry = entries[1]
        self.assertEqual(new_entry.stable_id, document.next_stable_id)
        self.assertEqual(inserted.next_stable_id, document.next_stable_id + 1)
        self.assertIsNone(new_entry.meta_id.span)

        moved = MoveMetadata(new_entry.stable_id).apply(inserted)
        self.assertEqual([entry.value.value for entry in moved.header_metadata], [7, 9, 12, 8])
        removed = RemoveMetadata(new_entry.stable_id).apply(moved)
        self.assertEqual(serialize(removed), serialize(document))
        self.assertEqual(removed.next_stable_id, inserted.next_stable_id)

    def test_metadata_move_rejects_an_anchor_from_another_scope(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False))
        header_entry = document.header_metadata[0]
        split_entry = document.splits[0].metadata[0]
        with self.assertRaises(ModelInvariantError):
            MoveMetadata(header_entry.stable_id, split_entry.stable_id).apply(document)

    def test_row_insert_move_remove_preserves_identity_and_serializes(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False), row_storage="compact")
        split = document.splits[0]
        original_block = split.blocks[0]
        with_second_block = InsertBlock(split.stable_id, original_block).apply(document)
        second_block = with_second_block.splits[0].blocks[1]
        prototype = original_block.rows[0]
        with self.assertRaises(ModelInvariantError):
            MoveRow(
                prototype.stable_id,
                second_block.stable_id,
                before_row_id=prototype.stable_id,
            ).apply(with_second_block)

        inserted = InsertRow(
            original_block.stable_id,
            prototype,
            before_row_id=original_block.rows[1].stable_id,
        ).apply(with_second_block)
        rows = inserted.splits[0].blocks[0].rows
        new_row = rows[1]
        self.assertNotEqual(new_row.stable_id, prototype.stable_id)
        self.assertEqual(new_row.stable_id, inserted.next_stable_id - 1)
        self.assertEqual(new_row.raw_cells, prototype.raw_cells)

        moved = MoveRow(new_row.stable_id, second_block.stable_id).apply(inserted)
        self.assertEqual(moved.splits[0].blocks[1].rows[-1].stable_id, new_row.stable_id)
        removed = RemoveRow(new_row.stable_id).apply(moved)
        self.assertTrue(validate(removed).is_valid)
        self.assertEqual(parse_bytes(serialize(removed)).statistics(), removed.statistics())

    def test_block_insert_move_remove_reidentifies_the_complete_subtree(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False))
        original_split = document.splits[0]
        original_block = original_split.blocks[0]
        with_split = InsertSplit(original_split).apply(document)
        target_split = with_split.splits[1]
        with self.assertRaises(ModelInvariantError):
            MoveBlock(
                original_block.stable_id,
                target_split.stable_id,
                before_block_id=original_block.stable_id,
            ).apply(with_split)

        inserted = InsertBlock(original_split.stable_id, original_block).apply(with_split)
        copied = inserted.splits[0].blocks[1]
        original_ids = {
            original_block.stable_id,
            *(entry.stable_id for entry in original_block.divisions),
            *(row.stable_id for row in original_block.rows),
            *(
                cell.stable_id
                for row in original_block.rows
                if hasattr(row, "cells")
                for cell in row.cells
            ),
        }
        copied_ids = {
            copied.stable_id,
            *(entry.stable_id for entry in copied.divisions),
            *(row.stable_id for row in copied.rows),
            *(cell.stable_id for row in copied.rows if hasattr(row, "cells") for cell in row.cells),
        }
        self.assertTrue(original_ids.isdisjoint(copied_ids))
        self.assertIsNone(copied.span)

        moved = MoveBlock(copied.stable_id, target_split.stable_id).apply(inserted)
        self.assertEqual(moved.splits[1].blocks[-1].stable_id, copied.stable_id)
        removed = RemoveBlock(copied.stable_id).apply(moved)
        self.assertTrue(validate(removed).is_valid)

    def test_split_insert_move_remove_is_reversible_through_command_stack(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False))
        original = document.splits[0]
        stack = CommandStack(document)
        inserted = stack.execute(InsertSplit(original))
        new_split = inserted.splits[1]
        self.assertNotEqual(new_split.stable_id, original.stable_id)
        self.assertTrue(validate(inserted).is_valid)

        moved = stack.execute(MoveSplit(new_split.stable_id, original.stable_id))
        self.assertEqual(moved.splits[0].stable_id, new_split.stable_id)
        removed = stack.execute(RemoveSplit(new_split.stable_id))
        self.assertEqual(serialize(removed), serialize(document))
        self.assertEqual(serialize(stack.undo()), serialize(moved))
        self.assertEqual(serialize(stack.redo()), serialize(removed))

    def test_removed_ids_are_not_recycled(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False))
        inserted = InsertMetadata.from_ints(document.stable_id, 1, 2).apply(document)
        allocated = inserted.header_metadata[-1].stable_id
        removed = RemoveMetadata(allocated).apply(inserted)
        inserted_again = InsertMetadata.from_ints(removed.stable_id, 3, 4).apply(removed)
        self.assertGreater(inserted_again.header_metadata[-1].stable_id, allocated)

    def test_lightmap_row_insertion_preserves_four_channel_encoding(self) -> None:
        document = parse_bytes(make_implicit_lightmap(), row_storage="compact")
        block = document.splits[0].blocks[0]
        inserted = InsertRow(block.stable_id, block.rows[0]).apply(document)
        rows = inserted.splits[0].blocks[0].rows
        self.assertEqual(rows[1].raw_channels, b"\x01\x02\x03\x04")
        self.assertTrue(validate(inserted).is_valid)
        self.assertEqual(parse_bytes(serialize(inserted)).statistics(), inserted.statistics())


if __name__ == "__main__":
    unittest.main()
