from __future__ import annotations

import unittest
from dataclasses import replace

from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.commands import (
    CommandStack,
    SetBlockField,
    SetMetadataValue,
    SetNoteCellRaw,
    SetRowRaw,
)
from stepnx.core.diff import diff_documents
from stepnx.core.model import NoteRow, OverlayRows
from stepnx.core.scalars import RawF32
from tests.fixture_factory import make_normal_nx20


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


if __name__ == "__main__":
    unittest.main()
