from __future__ import annotations

import struct
import unittest

from stepnx.codecs.nx20 import parse_bytes
from stepnx.exporters.ssc import LINES_PER_MEASURE, SscExportError, SscSongInfo
from stepnx.exporters.ssc_random import compile_ssc_export
from stepnx.exporters.ssc_xsanity import render_compiled_reports, render_compiled_simfile

from tests.fixture_factory import f32, metadata, u32


EMPTY_ROW = bytes((0x80, 0x00, 0x00, 0x00))


def block(
    rows: list[bytes],
    *,
    bpm: float = 120.0,
    scroll: float = 0.125,
    beat_split: int = 8,
) -> bytes:
    body = bytearray()
    body += f32(0.0) + f32(bpm) + f32(scroll) + f32(0.0) + f32(1.0)
    body += bytes((beat_split, 4, 0, 0))
    body += metadata()
    body += u32(len(rows))
    body += b"".join(rows)
    return bytes(body)


def document(splits: list[tuple[int, list[bytes]]], *, columns: int = 5) -> bytes:
    data = bytearray(b"NX20")
    data += u32(0) + u32(columns) + u32(0)
    data += metadata((1001, 18))
    data += u32(len(splits))
    for selector, blocks in splits:
        data += bytes((selector, 0)) + struct.pack("<H", 0)
        data += metadata()
        data += u32(len(blocks))
        data += b"".join(blocks)
    return bytes(data)


def chart_rows(text: str, chart_index: int = 0, *, columns: int = 5) -> list[str]:
    sections = text.split("#NOTEDATA:;")[1:]
    section = sections[chart_index]
    notes = section.split("#NOTES:\n", 1)[1].split(";", 1)[0].rstrip("\n")
    blank = "0" * columns
    rows: list[str] = []
    for measure in notes.split(",\n"):
        lines = measure.splitlines()
        if lines == [blank]:
            lines = [blank] * LINES_PER_MEASURE
        rows.extend(lines)
    return rows


def wrap_rows(text: str, *, columns: int = 5) -> list[int]:
    rows = chart_rows(text, 0, columns=columns)
    return [index for index, line in enumerate(rows) if "T" in line]


class XSanityRuntimeExportTest(unittest.TestCase):
    def test_random_pool_emits_runtime_envelope(self) -> None:
        two = [block([EMPTY_ROW] * 8), block([EMPTY_ROW] * 8)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 64)]),
                (0x80, two),
                (0x00, [block([EMPTY_ROW] * 32)]),
            ]
        )
        report = compile_ssc_export(parse_bytes(raw), description="RANDOM.NX")
        text = render_compiled_simfile(report, SscSongInfo(title="Runtime random"))

        self.assertEqual(report.window_count, 1)
        self.assertTrue(text.startswith("#VERSION:0.83;\n"))
        self.assertNotIn("#VERSION:0.83 xSanity;", text)
        self.assertEqual(text.count("#SPECIAL:LEVEL,RANDOM;"), 1)
        self.assertIn("#CHARTNAME:STEPNX_BASE;", text)
        self.assertIn("#CHARTNAME:STEPNX_RANDOM_001;", text)
        self.assertIn("#CHARTNAME:STEPNX_RANDOM_002;", text)
        self.assertEqual(text.count("#LABELTYPE:NORMAL;"), 1)
        self.assertEqual(text.count("#LABELTYPE:DIVISION;"), 2)
        self.assertEqual(text.count("#TICKCOUNTS:0.000000=8;"), 3)
        self.assertIn("T0000", text)
        self.assertIn("O0000", text)

    def test_non_random_export_does_not_claim_random_special(self) -> None:
        raw = document([(0x00, [block([EMPTY_ROW] * 32)])])
        report = compile_ssc_export(parse_bytes(raw), description="NORMAL.NX")
        text = render_compiled_simfile(report, SscSongInfo(title="Runtime normal"))

        self.assertEqual(report.window_count, 0)
        self.assertNotIn("#SPECIAL:LEVEL,RANDOM;", text)

    def test_wrap_crosses_zero_scroll_to_keep_two_visual_beats(self) -> None:
        two = [block([EMPTY_ROW] * 8), block([EMPTY_ROW] * 8)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 32, scroll=0.125)]),
                (0x00, [block([EMPTY_ROW] * 32, scroll=0.0)]),
                (0x80, two),
                (0x00, [block([EMPTY_ROW] * 32, scroll=0.125)]),
            ]
        )
        report = compile_ssc_export(parse_bytes(raw), description="ZERO_SCROLL.NX")
        text = render_compiled_simfile(report, SscSongInfo(title="Zero-scroll guard"))

        self.assertEqual(wrap_rows(text), [16])

    def test_wrap_keeps_two_visual_beats_when_preceding_scroll_moves(self) -> None:
        two = [block([EMPTY_ROW] * 8), block([EMPTY_ROW] * 8)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 32, scroll=0.125)]),
                (0x00, [block([EMPTY_ROW] * 32, scroll=0.125)]),
                (0x80, two),
                (0x00, [block([EMPTY_ROW] * 32, scroll=0.125)]),
            ]
        )
        report = compile_ssc_export(parse_bytes(raw), description="MOVING_SCROLL.NX")
        text = render_compiled_simfile(report, SscSongInfo(title="Moving scroll"))

        self.assertEqual(wrap_rows(text), [48])

    def test_dense_load_time_randoms_coalesce_into_one_helper_window(self) -> None:
        two = [block([EMPTY_ROW] * 8), block([EMPTY_ROW] * 8)]
        three = [block([EMPTY_ROW] * 8) for _ in range(3)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 64)]),
                (0x80, two),
                (0x80, three),
                (0x00, [block([EMPTY_ROW] * 32)]),
            ]
        )
        report = compile_ssc_export(parse_bytes(raw), description="DENSE.NX")
        text = render_compiled_simfile(report, SscSongInfo(title="Dense random"))

        self.assertEqual(report.helper_count, 6)
        self.assertEqual(report.window_count, 1)
        self.assertEqual(report.windows[0].random_split_indices, (1, 2))
        self.assertEqual(len(wrap_rows(text)), 1)
        self.assertIn("ssc.random-window-compressed-joint", {d.code for d in report.diagnostics})

    def test_sparse_helpers_drop_deterministic_tail_after_final_return(self) -> None:
        two = [block([EMPTY_ROW] * 8), block([EMPTY_ROW] * 8)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 64)]),
                (0x80, two),
                (0x00, [block([EMPTY_ROW] * 256)]),
            ]
        )
        report = compile_ssc_export(parse_bytes(raw), description="SPARSE.NX")
        text = render_compiled_simfile(report, SscSongInfo(title="Sparse helper"))

        base_rows = chart_rows(text, 0)
        helper_rows = chart_rows(text, 1)
        self.assertLess(len(helper_rows), len(base_rows))
        self.assertTrue(any("O" in row for row in helper_rows))

    def test_generated_chartnames_are_unique_beyond_historical_nine_routes(self) -> None:
        twenty = [block([EMPTY_ROW] * 8) for _ in range(20)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 64)]),
                (0x80, twenty),
                (0x00, [block([EMPTY_ROW] * 32)]),
            ]
        )
        report = compile_ssc_export(parse_bytes(raw), description="TWENTY.NX")
        text = render_compiled_simfile(report, SscSongInfo(title="Twenty routes"))

        names = [
            line.removeprefix("#CHARTNAME:").removesuffix(";")
            for line in text.splitlines()
            if line.startswith("#CHARTNAME:")
        ]
        self.assertEqual(len(names), 21)
        self.assertEqual(len(set(names)), 21)
        self.assertIn("STEPNX_RANDOM_020", names)

    def test_combined_non_random_reports_get_unique_chartnames(self) -> None:
        raw = document([(0x00, [block([EMPTY_ROW] * 32)])])
        first = compile_ssc_export(parse_bytes(raw), description="NM.NX")
        second = compile_ssc_export(parse_bytes(raw), description="HD.NX")
        text = render_compiled_reports((first, second), SscSongInfo(title="Arcade song"))

        self.assertEqual(text.count("#NOTEDATA:;"), 2)
        self.assertIn("#CHARTNAME:STEPNX_01_BASE;", text)
        self.assertIn("#CHARTNAME:STEPNX_02_BASE;", text)
        self.assertNotIn("#SPECIAL:LEVEL,RANDOM;", text)

    def test_combined_random_reports_of_same_steps_type_are_rejected(self) -> None:
        two = [block([EMPTY_ROW] * 8), block([EMPTY_ROW] * 8)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 64)]),
                (0x80, two),
            ]
        )
        first = compile_ssc_export(parse_bytes(raw), description="R1.NX")
        second = compile_ssc_export(parse_bytes(raw), description="R2.NX")

        with self.assertRaisesRegex(SscExportError, "more than one random chart"):
            render_compiled_reports((first, second), SscSongInfo(title="Conflict"))


if __name__ == "__main__":
    unittest.main()
