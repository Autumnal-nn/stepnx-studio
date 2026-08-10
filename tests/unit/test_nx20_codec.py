from __future__ import annotations

import struct
import unittest
from dataclasses import replace

from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.errors import ModelInvariantError, ParseError, UnsupportedFormatError
from stepnx.core.model import EnvelopeKind, LightmapRow, MetadataEntry, NoteRow, PackedNoteRow
from stepnx.core.scalars import RawU32
from tests.fixture_factory import make_implicit_lightmap, make_normal_nx20, make_nx10, u32


class NX20CodecTests(unittest.TestCase):
    def test_normal_chart_roundtrip_is_byte_exact(self) -> None:
        source = make_normal_nx20()
        document = parse_bytes(source, source="synthetic.NX")
        self.assertEqual(serialize(document), source)

    def test_raw_fields_and_duplicate_order_survive(self) -> None:
        document = parse_bytes(make_normal_nx20())
        self.assertEqual([entry.meta_id.value for entry in document.header_metadata], [900, 900, 0x0001044F])
        self.assertEqual([entry.value.value for entry in document.header_metadata[:2]], [7, 9])
        split = document.splits[0]
        self.assertEqual(split.raw_select.value, 0x5A)
        self.assertEqual(split.raw_brain.value, 0x81)
        self.assertEqual(split.raw_padding.value, 0xBEEF)
        block = split.blocks[0]
        self.assertEqual(block.start_time.bits, 0x80000000)
        self.assertEqual(block.scroll.bits, 0x7FA12345)
        self.assertEqual(block.smooth_speed.value, 3)
        self.assertEqual(block.raw_flag.value, 0xA5)
        self.assertEqual(block.divisions[0].meta_id.value, 111)

    def test_rows_keep_exact_encoding(self) -> None:
        document = parse_bytes(make_normal_nx20())
        rows = document.splits[0].blocks[0].rows
        self.assertIsInstance(rows[0], NoteRow)
        self.assertEqual(len(rows[0].cells), 5)
        self.assertEqual(rows[1].raw, bytes.fromhex("80123456"))

    def test_compact_rows_materialize_cells_without_changing_identity(self) -> None:
        source = make_normal_nx20(sized_trailer=False)
        rich = parse_bytes(source, row_storage="rich")
        compact = parse_bytes(source, row_storage="compact")
        rich_row = rich.splits[0].blocks[0].rows[0]
        compact_row = compact.splits[0].blocks[0].rows[0]

        self.assertIsInstance(rich_row, NoteRow)
        self.assertIsInstance(compact_row, PackedNoteRow)
        self.assertEqual(compact_row.stable_id, rich_row.stable_id)
        self.assertEqual(compact_row.cells, rich_row.cells)
        self.assertEqual(compact.splits[0].blocks[0].stable_id, rich.splits[0].blocks[0].stable_id)
        self.assertEqual(serialize(compact), source)

    def test_compact_row_rejects_width_mismatch(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False), row_storage="compact")
        split = document.splits[0]
        block = split.blocks[0]
        row = block.rows[0]
        bad_row = replace(row, raw_cells=row.raw_cells[:-4], span=None)
        bad_block = replace(block, rows=(bad_row, *block.rows[1:]))
        bad_split = replace(split, blocks=(bad_block,))
        with self.assertRaises(ModelInvariantError):
            serialize(replace(document, splits=(bad_split,)))

    def test_unknown_row_storage_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_bytes(make_normal_nx20(), row_storage="wishful-thinking")

    def test_sized_trailer_is_classified_without_parsing_payload(self) -> None:
        source = make_normal_nx20()
        document = parse_bytes(source)
        self.assertIs(document.envelope.kind, EnvelopeKind.SIZED_TRAILER)
        self.assertEqual(document.envelope.marker_size, len(document.envelope.raw))
        self.assertEqual(serialize(document), source)

    def test_four_byte_empty_trailer_is_valid(self) -> None:
        source = make_normal_nx20(sized_trailer=False) + u32(4)
        document = parse_bytes(source)
        self.assertIs(document.envelope.kind, EnvelopeKind.SIZED_TRAILER)
        self.assertEqual(document.envelope.payload, b"")
        self.assertEqual(serialize(document), source)

    def test_invalid_sized_trailer_model_is_rejected(self) -> None:
        document = parse_bytes(make_normal_nx20())
        broken = replace(document.envelope, raw=document.envelope.raw[:-1])
        with self.assertRaises(ModelInvariantError):
            serialize(replace(document, envelope=broken))

    def test_opaque_tail_is_not_promoted_to_trailer(self) -> None:
        source = make_normal_nx20(sized_trailer=False, opaque_tail=True)
        document = parse_bytes(source)
        self.assertIs(document.envelope.kind, EnvelopeKind.OPAQUE_TAIL)
        self.assertEqual(serialize(document), source)

    def test_implicit_lightmap_uses_four_byte_rows(self) -> None:
        source = make_implicit_lightmap()
        document = parse_bytes(source, source="LM.NX")
        self.assertTrue(document.effective_lightmap)
        row = document.splits[0].blocks[0].rows[0]
        self.assertIsInstance(row, LightmapRow)
        self.assertEqual(row.raw_channels, b"\x01\x02\x03\x04")
        self.assertEqual(serialize(document), source)

    def test_collection_edit_recalculates_count_only(self) -> None:
        source = make_normal_nx20(sized_trailer=False)
        document = parse_bytes(source)
        entry = MetadataEntry(
            stable_id=9999,
            meta_id=RawU32.from_value(1234),
            value=RawU32.from_value(5678),
            span=None,
        )
        edited = replace(document, header_metadata=document.header_metadata + (entry,))
        rebuilt = serialize(edited)
        self.assertEqual(struct.unpack_from("<I", rebuilt, 16)[0], 4)
        reparsed = parse_bytes(rebuilt)
        self.assertEqual(len(reparsed.header_metadata), 4)
        self.assertEqual(reparsed.header_metadata[-1].meta_id.value, 1234)

    def test_row_width_mismatch_is_rejected(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False))
        split = document.splits[0]
        block = split.blocks[0]
        row = block.rows[0]
        bad_row = replace(row, cells=row.cells[:-1])
        bad_block = replace(block, rows=(bad_row, *block.rows[1:]))
        bad_split = replace(split, blocks=(bad_block,))
        with self.assertRaises(ModelInvariantError):
            serialize(replace(document, splits=(bad_split,)))

    def test_truncation_has_offset_and_field(self) -> None:
        complete = make_normal_nx20()
        body_end = parse_bytes(complete).body_span.end
        source = complete[: body_end - 2]
        with self.assertRaises(ParseError) as caught:
            parse_bytes(source, source="truncated.NX")
        self.assertGreater(caught.exception.offset, 0)
        self.assertIn("truncated.NX", str(caught.exception))
        self.assertIn("row", str(caught.exception))

    def test_absurd_count_is_rejected_at_count_offset(self) -> None:
        source = b"NX20" + u32(0) + u32(5) + u32(0) + u32(0xFFFFFFFF)
        with self.assertRaises(ParseError) as caught:
            parse_bytes(source)
        self.assertEqual(caught.exception.offset, 16)
        self.assertIn("unreasonable count", str(caught.exception))

    def test_nx10_is_recognized_but_not_parsed_as_nx20(self) -> None:
        with self.assertRaises(UnsupportedFormatError):
            parse_bytes(make_nx10(), source="legacy.NX")


if __name__ == "__main__":
    unittest.main()
