from __future__ import annotations

import unittest
from dataclasses import replace

from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.model import MetadataEntry, NoteCell, NoteRow, OverlayRows
from stepnx.core.validation import Severity, validate
from tests.fixture_factory import make_normal_nx20


class ValidationTests(unittest.TestCase):
    def test_valid_rich_and_compact_documents_have_no_issues(self) -> None:
        source = make_normal_nx20()
        self.assertTrue(validate(parse_bytes(source, row_storage="rich")).is_valid)
        self.assertEqual(validate(parse_bytes(source, row_storage="compact")).issues, ())

    def test_stale_raw_count_is_a_warning_because_writer_recalculates_it(self) -> None:
        document = parse_bytes(make_normal_nx20())
        edited = replace(document, header_metadata=document.header_metadata[:-1])
        report = validate(edited)
        self.assertTrue(report.is_valid)
        self.assertEqual(report.warnings[0].code, "count.stale")

    def test_duplicate_stable_id_is_an_error(self) -> None:
        document = parse_bytes(make_normal_nx20())
        original = document.header_metadata[0]
        duplicate = MetadataEntry(
            original.stable_id,
            document.header_metadata[1].meta_id,
            document.header_metadata[1].value,
            document.header_metadata[1].span,
        )
        edited = replace(document, header_metadata=(original, duplicate, *document.header_metadata[2:]))
        report = validate(edited)
        self.assertFalse(report.is_valid)
        self.assertTrue(
            any(
                issue.severity is Severity.ERROR and issue.code == "stable-id.duplicate"
                for issue in report.issues
            )
        )

    def test_overlay_cannot_change_cell_identity_during_promotion(self) -> None:
        document = parse_bytes(make_normal_nx20(), row_storage="compact")
        split = document.splits[0]
        block = split.blocks[0]
        packed = block.rows[0]
        cells = list(packed.cells)
        cells[0] = NoteCell(999999, cells[0].raw, None)
        replacement = NoteRow(packed.stable_id, tuple(cells), packed.span)
        overlay = OverlayRows(block.rows, ((0, replacement),))
        edited_block = replace(block, rows=overlay)
        edited_split = replace(split, blocks=(edited_block,))

        report = validate(replace(document, splits=(edited_split,)))
        self.assertFalse(report.is_valid)
        self.assertTrue(
            any(issue.code == "stable-id.replaced-cell" for issue in report.issues)
        )


if __name__ == "__main__":
    unittest.main()
