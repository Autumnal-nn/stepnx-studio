from __future__ import annotations

import struct
import unittest

from stepnx.codecs.nx20 import parse_bytes
from stepnx.exporters.ssc import LINES_PER_MEASURE, SscSongInfo
from stepnx.exporters.ssc_random import compile_ssc_export
from stepnx.exporters.ssc_xsanity import render_compiled_simfile

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


def first_chart_rows(text: str, *, columns: int = 5) -> list[str]:
    section = text.split("#NOTEDATA:;", 1)[1].split("#NOTEDATA:;", 1)[0]
    notes = section.split("#NOTES:\n", 1)[1].rstrip("\n")
    blank = "0" * columns
    rows: list[str] = []
    for measure in notes.split(",\n"):
        lines = measure.splitlines()
        if lines == [blank]:
            lines = [blank] * LINES_PER_MEASURE
        rows.extend(lines)
    return rows


def wrap_rows(text: str, *, columns: int = 5) -> list[int]:
    rows = first_chart_rows(text, columns=columns)
    return [index for index, line in enumerate(rows) if "T" in line]


class XSanityRuntimeExportTest(unittest.TestCase):
    def test_random_pool_emits_runtime_envelope(self) -> None:
        two = [block([EMPTY_ROW] * 8), block([EMPTY_ROW] * 8)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 32)]),
                (0x80, two),
                (0x00, [block([EMPTY_ROW] * 32)]),
            ]
        )
        report = compile_ssc_export(parse_bytes(raw), description="RANDOM.NX")
        text = render_compiled_simfile(report, SscSongInfo(title="Runtime random"))

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

        self.assertNotIn("#SPECIAL:LEVEL,RANDOM;", text)

    def test_wrap_crosses_zero_scroll_then_keeps_two_visual_beats(self) -> None:
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

        # Random starts at row 64. Rows 32..63 have zero visual travel, so the
        # two visual beats must come from 16 rows of normal 0.125 NX scroll.
        self.assertEqual(wrap_rows(text), [16])

    def test_wrap_keeps_two_visual_beats_at_normal_scroll(self) -> None:
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

        # At normal scroll each NX row contributes 0.125 visual beat, so two
        # visual beats require 16 rows of lead from the random start at row 64.
        self.assertEqual(wrap_rows(text), [48])

    def test_wrap_uses_more_rows_when_scroll_is_slower(self) -> None:
        two = [block([EMPTY_ROW] * 8), block([EMPTY_ROW] * 8)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 64, scroll=0.0625)]),
                (0x80, two),
                (0x00, [block([EMPTY_ROW] * 32, scroll=0.125)]),
            ]
        )
        report = compile_ssc_export(parse_bytes(raw), description="SLOW_SCROLL.NX")
        text = render_compiled_simfile(report, SscSongInfo(title="Slow-scroll guard"))

        # Half normal visual speed needs 32 source rows for the same two-beat
        # visible lead.
        self.assertEqual(wrap_rows(text), [32])

    def test_generated_chartnames_are_unique_beyond_historical_nine_routes(self) -> None:
        twenty = [block([EMPTY_ROW] * 8) for _ in range(20)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 32)]),
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


if __name__ == "__main__":
    unittest.main()
