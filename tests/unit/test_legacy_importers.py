from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from stepnx.authoring.audio import WaveformEnvelope, WaveformError, estimate_bpm
from stepnx.codecs.nx20 import serialize
from stepnx.importers.legacy import (
    LegacyBlock,
    LegacyChart,
    LegacyRow,
    parse_ksf,
    parse_not,
    parse_not5,
    parse_stf,
    parse_stx,
    project_nx20,
    row_similarity,
)


def _xor_not(payload: bytes) -> bytes:
    key = 0xD2
    result = bytearray()
    for value in payload:
        result.append(value ^ key)
        key = (key + 0x95) & 0xFF
    return bytes(result)


class LegacyImporterTests(unittest.TestCase):
    def test_stf_accepts_1st_size(self) -> None:
        data = bytearray(280 + 1024 * 14)
        struct.pack_into("<f", data, 256, 120.0)
        data[280:] = b"0" * (1024 * 14)
        chart = parse_stf(bytes(data))
        self.assertEqual((chart.source_format, len(chart.blocks[0].rows)), ("stf", 1024))

    def test_stf_accepts_2nd_size(self) -> None:
        data = bytearray(280 + 2048 * 14)
        struct.pack_into("<f", data, 256, 150.0)
        data[280:] = b"1" * (2048 * 14)
        self.assertEqual(len(parse_stf(bytes(data)).blocks[0].rows), 2048)

    def test_stf_rejects_wrong_row_count(self) -> None:
        with self.assertRaises(Exception):
            parse_stf(bytes(280 + 3 * 14))

    def test_not_combines_masks_for_same_line(self) -> None:
        records = struct.pack("<HHHH", 2, 1, 2, 2)
        chart = parse_not(bytes(0x88) + _xor_not(records))
        self.assertEqual(chart.blocks[0].rows[2].cells[:2], (1, 1))

    def test_not_preserves_sparse_rows(self) -> None:
        record = struct.pack("<HH", 3, 4)
        chart = parse_not(bytes(0x88) + _xor_not(record))
        self.assertEqual(len(chart.blocks[0].rows), 4)
        self.assertFalse(any(chart.blocks[0].rows[0].cells))

    def test_not_rejects_misaligned_file(self) -> None:
        with self.assertRaises(Exception):
            parse_not(bytes(0x89))

    def test_not5_detects_signature(self) -> None:
        data = bytearray(0xD8 + 6)
        data[:8] = b"pump 5.0"
        struct.pack_into("<f", data, 0x20, 130.0)
        struct.pack_into("<H", data, 0xD8, 1 << 9)
        data[0xDA] = 2
        chart = parse_not5(bytes(data))
        self.assertEqual(chart.blocks[0].rows[0].cells[0], 2)

    def test_not_dispatches_not5(self) -> None:
        data = bytearray(0xD8)
        data[:8] = b"pump 5.0"
        self.assertEqual(parse_not(bytes(data)).source_format, "not5")

    def test_ksf_parses_taps(self) -> None:
        chart = parse_ksf(b"#BPM:120\n#TICKCOUNT:4\n#STEP:\n1000000000\n#END\n")
        self.assertEqual(chart.blocks[0].rows[0].cells[0], 1)

    def test_ksf_expands_hold_run(self) -> None:
        chart = parse_ksf(b"#STEP:\n4000000000\n4000000000\n4000000000\n#END\n")
        self.assertEqual([row.cells[0] for row in chart.blocks[0].rows], [2, 3, 4])

    def test_ksf_solitary_four_is_tap(self) -> None:
        chart = parse_ksf(b"#STEP:\n4000000000\n#END\n")
        self.assertEqual(chart.blocks[0].rows[0].cells[0], 1)

    def test_ksf_detects_direct_move_controls(self) -> None:
        chart = parse_ksf(b"#STEP:\nB:120\n1000000000\n#END\n")
        self.assertEqual((chart.source_format, chart.controls), ("ksf-direct-move", (("B", "120"),)))

    def test_ksf_reports_nonstandard_width(self) -> None:
        chart = parse_ksf(b"#STEP:\n10000\n#END\n")
        self.assertEqual(chart.diagnostics[0].code, "ksf.row.width")

    def test_stx_reads_zlib_block(self) -> None:
        header = struct.pack("<fIIi", 120.0, 4, 4, 0) + bytes(112)
        compressed = zlib.compress(header + bytes((1,) + (0,) * 12))
        offset = 4 + 9 * 50 * 8
        data = bytearray(offset)
        data[:4] = b"STF4"
        struct.pack_into("<II", data, 4, offset, len(compressed))
        data += compressed
        parsed = parse_stx(bytes(data))
        self.assertEqual(parsed.charts[0].blocks[0].rows[0].cells[0], 1)

    def test_stx_rejects_empty_table(self) -> None:
        with self.assertRaises(Exception):
            parse_stx(b"STF4" + bytes(4000))

    def test_stx_rejects_wrong_signature(self) -> None:
        with self.assertRaises(Exception):
            parse_stx(b"NOPE" + bytes(4000))

    def test_projection_creates_parseable_nx20(self) -> None:
        chart = LegacyChart("test", 5, (LegacyBlock(120, 4, 4, 0, (LegacyRow((1, 0, 0, 0, 0)),)),))
        document = project_nx20(chart)
        self.assertTrue(serialize(document).startswith(b"NX20"))

    def test_projection_converts_hold_types(self) -> None:
        rows = tuple(LegacyRow((value, 0, 0, 0, 0)) for value in (2, 3, 4))
        document = project_nx20(LegacyChart("test", 5, (LegacyBlock(120, 4, 4, 0, rows),)))
        types = [row.cells[0].note_type for row in document.splits[0].blocks[0].rows]
        self.assertEqual(types, [7, 11, 15])

    def test_projection_scales_scroll_by_split(self) -> None:
        chart = LegacyChart("test", 5, (LegacyBlock(120, 4, 8, 0, (), scroll=2),))
        document = project_nx20(chart)
        self.assertAlmostEqual(document.splits[0].blocks[0].scroll.value, 0.25)

    def test_projection_keeps_source_name_out_of_source_bytes(self) -> None:
        chart = LegacyChart("test", 5, (LegacyBlock(120, 4, 4, 0, ()),), "legacy.ksf")
        self.assertEqual(project_nx20(chart).source_name, "legacy.ksf [NX20 projection]")

    def test_projection_preserves_requested_start_column(self) -> None:
        chart = LegacyChart("test", 5, (LegacyBlock(120, 4, 4, 0, ()),))
        self.assertEqual(project_nx20(chart, start_column=2).start_column.value, 2)

    def test_projection_keeps_unknown_value_visible(self) -> None:
        chart = LegacyChart("test", 5, (LegacyBlock(120, 4, 4, 0, (LegacyRow((9, 0, 0, 0, 0)),)),))
        row = project_nx20(chart).splits[0].blocks[0].rows[0]
        self.assertEqual(row.cells[0].note_type, 1)

    def test_similarity_matches_identical_charts(self) -> None:
        chart = LegacyChart("a", 1, (LegacyBlock(120, 4, 4, 0, (LegacyRow((1,)),)),))
        self.assertEqual(row_similarity(chart, chart), 1.0)

    def test_similarity_penalizes_missing_rows(self) -> None:
        left = LegacyChart("a", 1, (LegacyBlock(120, 4, 4, 0, (LegacyRow((1,)), LegacyRow((1,)))),))
        right = LegacyChart("b", 1, (LegacyBlock(120, 4, 4, 0, (LegacyRow((1,)),)),))
        self.assertEqual(row_similarity(left, right), 0.5)

    def test_similarity_of_two_empty_charts_is_exact(self) -> None:
        chart = LegacyChart("a", 1, (LegacyBlock(120, 4, 4, 0, ()),))
        self.assertEqual(row_similarity(chart, chart), 1.0)

    def test_ksf_rejects_missing_rows(self) -> None:
        with self.assertRaises(Exception):
            parse_ksf(b"#BPM:120\n#STEP:\n#END\n")


class BpmEstimateTests(unittest.TestCase):
    def test_estimates_regular_120_bpm_pulses(self) -> None:
        peaks = [0.0] * 200
        for index in range(0, 200, 10):
            peaks[index] = 1.0
        bpm = estimate_bpm(WaveformEnvelope(10_000, tuple(peaks)), minimum=80, maximum=160)
        self.assertAlmostEqual(bpm, 120.0, delta=1.0)

    def test_rejects_silent_waveform(self) -> None:
        with self.assertRaises(WaveformError):
            estimate_bpm(WaveformEnvelope(1000, (0.0,) * 20))

    def test_rejects_empty_waveform(self) -> None:
        with self.assertRaises(WaveformError):
            estimate_bpm(WaveformEnvelope(0, ()))

    def test_rejects_invalid_range(self) -> None:
        with self.assertRaises(WaveformError):
            estimate_bpm(WaveformEnvelope(1000, (0.0, 1.0)), minimum=200, maximum=100)


if __name__ == "__main__":
    unittest.main()
