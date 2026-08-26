from __future__ import annotations

import struct
import unittest

from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.errors import ParseError, StepNXError
from stepnx.core.model import EmptyRow, LightmapRow, NoteRow
from stepnx.core.validation import validate
from stepnx.importers.nx10 import ImportDiagnosticKind, import_bytes


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _make_nx10(
    *,
    chart_type: int = 0,
    columns: int = 5,
    bpm: float = 120.0,
    beat_split: int = 4,
    notes: tuple[int, ...] | None = None,
    division_ranges: dict[int, tuple[int, int]] | None = None,
    lightmap_row: bytes | None = None,
) -> bytes:
    if notes is None:
        notes = tuple(0 for _ in range(columns))
    if len(notes) != columns:
        raise ValueError("note fixture width does not match columns")

    split_offset = 20
    block_offset = 28
    output = bytearray(b"NX10")
    output += _u32(chart_type) + _u32(columns) + _u32(1)
    output += _u32(split_offset)
    output += _u32(1) + _u32(block_offset)

    output += struct.pack("<fffff", 0.25, bpm, 1.5, -0.125, 2.0)
    division_pointer_position = len(output)
    output += _u32(0)
    output += struct.pack("<HBBI", beat_split, 4, 1, 1)

    if lightmap_row is not None:
        if len(lightmap_row) != 4:
            raise ValueError("Lightmap fixture row must be four bytes")
        output += lightmap_row
    else:
        row_pointer_position = len(output)
        output += _u32(0)

    if division_ranges:
        division_offset = len(output)
        struct.pack_into("<I", output, division_pointer_position, division_offset)
        minimums = [0] * 10
        maximums = [0] * 10
        for meta_id, (minimum, maximum) in division_ranges.items():
            minimums[meta_id] = minimum
            maximums[meta_id] = maximum
        output += b"".join(_u32(value) for value in minimums + maximums)

    if lightmap_row is None:
        note_offset = len(output)
        # The NX2 corpus proves that Half Double stores the pointer to its six
        # active cells directly.  chart_type controls start_column, not a second
        # byte offset applied to the row pointer.
        struct.pack_into("<I", output, row_pointer_position, note_offset)
        output += b"".join(struct.pack("<H", note) for note in notes)
    return bytes(output)


def _make_two_block_nx10(first_bpm: float, second_bpm: float) -> bytes:
    split_offset = 20
    first_block_offset = 32
    first_note_offset = first_block_offset + 36
    second_block_offset = first_note_offset + 10
    second_note_offset = second_block_offset + 36

    output = bytearray(b"NX10")
    output += _u32(0) + _u32(5) + _u32(1) + _u32(split_offset)
    output += _u32(2) + _u32(first_block_offset) + _u32(second_block_offset)

    def append_block(start_time: float, bpm: float, note_offset: int) -> None:
        output.extend(struct.pack("<fffff", start_time, bpm, 1.0, 0.0, 0.0))
        output.extend(_u32(0))
        output.extend(struct.pack("<HBBI", 4, 4, 0, 1))
        output.extend(_u32(note_offset))
        output.extend(b"\x00" * 10)

    append_block(0.0, first_bpm, first_note_offset)
    append_block(1000.0, second_bpm, second_note_offset)
    return bytes(output)


class NX10ImporterTests(unittest.TestCase):
    def test_import_preserves_source_and_produces_native_nx20(self) -> None:
        source = _make_nx10(notes=(0x00B3, 0, 0, 0, 0))
        result = import_bytes(source, source="legacy.NX")

        self.assertEqual(result.source_bytes, source)
        self.assertEqual(result.document.source_bytes, source)
        self.assertEqual(result.document.profile, "nxa-native")
        self.assertTrue(result.report.is_semantically_lossless)
        row = result.document.splits[0].blocks[0].rows[0]
        self.assertIsInstance(row, NoteRow)
        self.assertEqual(struct.unpack("<I", row.cells[0].raw)[0], 0x00000343)

        native = serialize(result.document)
        self.assertEqual(native[:4], b"NX20")
        self.assertEqual(serialize(parse_bytes(native)), native)
        self.assertTrue(validate(result.document).is_valid)

    def test_official_bank_bits_are_retained_in_both_nx20_locations(self) -> None:
        source = _make_nx10(notes=(0x05B3, 0x0AB3, 0, 0, 0))
        row = import_bytes(source).document.splits[0].blocks[0].rows[0]

        self.assertEqual(struct.unpack("<I", row.cells[0].raw)[0], 0x40010343)
        self.assertEqual(struct.unpack("<I", row.cells[1].raw)[0], 0x80020343)

    def test_no_register_long_components_use_0x30_family(self) -> None:
        source = _make_nx10(notes=(0x0074, 0x0076, 0x0077, 0, 0))
        row = import_bytes(source).document.splits[0].blocks[0].rows[0]

        self.assertEqual(struct.unpack("<I", row.cells[0].raw)[0], 0x00000337)
        self.assertEqual(struct.unpack("<I", row.cells[1].raw)[0], 0x0000033B)
        self.assertEqual(struct.unpack("<I", row.cells[2].raw)[0], 0x0000033F)

    def test_division_minimums_and_maximums_project_to_ids_zero_through_nine(self) -> None:
        source = _make_nx10(division_ranges={0: (3, 4), 5: (7, 9), 9: (2, 0)})
        block = import_bytes(source).document.splits[0].blocks[0]

        self.assertEqual([entry.meta_id.value for entry in block.divisions], [0, 5, 9])
        self.assertEqual(
            [entry.value.value for entry in block.divisions],
            [(4 << 16) | 3, (9 << 16) | 7, 2],
        )

    def test_division_zero_1_over_0_becomes_split_random_start(self) -> None:
        result = import_bytes(_make_nx10(division_ranges={0: (1, 0), 1: (2, 3)}))
        split = result.document.splits[0]

        self.assertEqual(split.raw_select.value, 0x80)
        self.assertEqual([entry.meta_id.value for entry in split.blocks[0].divisions], [1])
        self.assertEqual(result.report.diagnostics[0].code, "nx10.division-0.random-select")
        self.assertIs(result.report.diagnostics[0].kind, ImportDiagnosticKind.TRANSFORMATION)

    def test_division_zero_2_over_0_becomes_split_random_follower(self) -> None:
        result = import_bytes(_make_nx10(division_ranges={0: (2, 0)}))

        self.assertEqual(result.document.splits[0].raw_select.value, 0x40)
        self.assertEqual(result.document.splits[0].blocks[0].divisions, ())

    def test_bpm_zero_becomes_smooth_warp_with_explicit_report(self) -> None:
        result = import_bytes(_make_nx10(bpm=0.0))
        block = result.document.splits[0].blocks[0]

        self.assertEqual(block.bpm.value, 120.0)
        self.assertEqual(block.smooth_speed.value, 3)
        self.assertEqual(result.report.diagnostics[0].code, "nx10.block.bpm-zero-warp")
        self.assertTrue(result.report.is_semantically_lossless)

    def test_leading_bpm_zero_defaults_to_120_instead_of_looking_ahead(self) -> None:
        result = import_bytes(_make_two_block_nx10(0.0, 121.0))
        first, second = result.document.splits[0].blocks

        self.assertEqual(first.bpm.value, 120.0)
        self.assertEqual(first.smooth_speed.value, 2)
        self.assertEqual(second.bpm.value, 121.0)
        self.assertEqual(second.smooth_speed.value, 0)

    def test_halfdouble_uses_stored_row_pointer_without_extra_offset(self) -> None:
        source = _make_nx10(
            chart_type=2,
            columns=6,
            notes=(0x00B3, 0, 0, 0, 0, 0),
        )
        result = import_bytes(source)

        self.assertEqual(result.document.start_column.value, 2)
        self.assertEqual(result.document.columns.value, 6)
        row = result.document.splits[0].blocks[0].rows[0]
        self.assertIsInstance(row, NoteRow)
        self.assertEqual(struct.unpack("<I", row.cells[0].raw)[0], 0x00000343)

    def test_halfdouble_explicit_zero_row_collapses_to_empty(self) -> None:
        source = _make_nx10(chart_type=2, columns=6, notes=(0, 0, 0, 0, 0, 0))
        result = import_bytes(source)

        row = result.document.splits[0].blocks[0].rows[0]
        self.assertIsInstance(row, EmptyRow)
        self.assertEqual(result.report.note_cells, 0)

    def test_lightmap_rows_are_inline(self) -> None:
        source = _make_nx10(
            chart_type=10,
            columns=3,
            lightmap_row=b"\x01\x02\x03\x04",
        )
        result = import_bytes(source, source="LM.NX")
        row = result.document.splits[0].blocks[0].rows[0]

        self.assertEqual(result.document.start_column.value, 0)
        self.assertEqual(result.document.lightmap_flag.value, 1)
        self.assertIsInstance(row, LightmapRow)
        self.assertEqual(row.raw_channels, b"\x01\x02\x03\x04")

    def test_null_row_pointer_becomes_nx20_empty_marker(self) -> None:
        source = bytearray(_make_nx10())
        struct.pack_into("<I", source, 60, 0)
        result = import_bytes(bytes(source))

        self.assertIsInstance(result.document.splits[0].blocks[0].rows[0], EmptyRow)
        self.assertEqual(result.report.note_cells, 0)

    def test_unknown_note_is_retained_in_source_and_reported_as_unsupported(self) -> None:
        source = _make_nx10(notes=(0x00B5, 0, 0, 0, 0))
        result = import_bytes(source)
        row = result.document.splits[0].blocks[0].rows[0]

        self.assertEqual(result.source_bytes, source)
        self.assertEqual(row.cells[0].raw, b"\x00\x00\x00\x00")
        self.assertEqual(result.report.unsupported[0].code, "nx10.note.unknown-type")
        self.assertFalse(result.report.is_semantically_lossless)

    def test_out_of_range_beat_split_is_reported(self) -> None:
        result = import_bytes(_make_nx10(beat_split=300))

        self.assertEqual(result.document.splits[0].blocks[0].beat_split.value, 44)
        self.assertEqual(result.report.approximations[0].code, "nx10.block.beat-split-narrowed")

    def test_truncated_offset_target_has_source_accurate_error(self) -> None:
        source = bytearray(_make_nx10())
        struct.pack_into("<I", source, 16, len(source) + 100)
        with self.assertRaises(ParseError) as caught:
            import_bytes(bytes(source), source="broken.NX")

        self.assertIn("broken.NX", str(caught.exception))
        self.assertIn("split 0", str(caught.exception))

    def test_deterministic_byte_mutations_fail_cleanly_or_import(self) -> None:
        source = _make_nx10(
            notes=(0x00B3, 0, 0, 0, 0),
            division_ranges={1: (2, 3)},
        )
        outcomes = 0
        for offset in range(len(source)):
            for mask in (0x01, 0x80, 0xFF):
                mutated = bytearray(source)
                mutated[offset] ^= mask
                try:
                    result = import_bytes(bytes(mutated), source="mutated.NX")
                    serialize(result.document)
                except StepNXError:
                    pass
                outcomes += 1
        self.assertEqual(outcomes, len(source) * 3)


if __name__ == "__main__":
    unittest.main()
