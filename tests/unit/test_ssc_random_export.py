from __future__ import annotations

import struct
import unittest

from stepnx.authoring.random_state import RandomPoolPolicy
from stepnx.codecs.nx20 import parse_bytes
from stepnx.exporters.ssc import SscExportError, SscSongInfo
from stepnx.exporters.ssc_random import compile_ssc_export, render_compiled_simfile

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


class RandomSscExportTest(unittest.TestCase):
    def test_twenty_way_named_bank_becomes_twenty_division_helpers(self) -> None:
        twenty = [block([EMPTY_ROW]) for _ in range(20)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 16)]),
                (0x81, twenty),
                (0x41, twenty),
                (0x00, [block([EMPTY_ROW] * 16)]),
            ]
        )
        report = compile_ssc_export(parse_bytes(raw), description="D22_22.NX")

        self.assertEqual(report.helper_count, 20)
        self.assertTrue(report.exact_probabilities)
        self.assertEqual(len(report.charts), 21)
        self.assertEqual(report.charts[0].label_type, "NORMAL")
        self.assertTrue(all(item.label_type == "DIVISION" for item in report.charts[1:]))
        self.assertIn("T0000", report.charts[0].chart.notes)
        self.assertNotIn("O0000", report.charts[0].chart.notes)
        self.assertTrue(all("O0000" in item.chart.notes for item in report.charts[1:]))
        self.assertNotIn("ssc.alternate-branches-dropped", [d.code for d in report.diagnostics])

        text = render_compiled_simfile(report, SscSongInfo(title="1309"))
        self.assertEqual(text.count("#NOTEDATA:;"), 21)
        self.assertEqual(text.count("#LABELTYPE:NORMAL;"), 1)
        self.assertEqual(text.count("#LABELTYPE:DIVISION;"), 20)

    def test_scroll_uses_corpus_confirmed_times_eight_conversion(self) -> None:
        raw = document([(0x00, [block([EMPTY_ROW], scroll=0.25, beat_split=16)])])
        report = compile_ssc_export(parse_bytes(raw), description="CR.NX")
        self.assertEqual(report.charts[0].chart.scrolls, "0=2,")

    def test_non_random_alternate_blocks_remain_an_explicit_pending_diagnostic(self) -> None:
        raw = document([(0x00, [block([EMPTY_ROW]), block([EMPTY_ROW])])])
        report = compile_ssc_export(parse_bytes(raw), description="CR.NX")
        self.assertEqual(report.helper_count, 0)
        self.assertIn("ssc.conditional-branches-pending", [d.code for d in report.diagnostics])

    def test_variable_length_random_alternatives_are_rejected_for_now(self) -> None:
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 16)]),
                (0x80, [block([EMPTY_ROW]), block([EMPTY_ROW] * 2)]),
            ]
        )
        with self.assertRaisesRegex(SscExportError, "variable-length alternatives"):
            compile_ssc_export(parse_bytes(raw), description="CR.NX")

    def test_approximate_pool_reports_probability_error(self) -> None:
        seven = [block([EMPTY_ROW]) for _ in range(7)]
        nine = [block([EMPTY_ROW]) for _ in range(9)]
        raw = document(
            [
                (0x00, [block([EMPTY_ROW] * 16)]),
                (0x80, seven),
                (0x00, [block([EMPTY_ROW] * 16)]),
                (0x80, nine),
                (0x00, [block([EMPTY_ROW] * 16)]),
            ]
        )
        report = compile_ssc_export(
            parse_bytes(raw),
            description="CR.NX",
            policy=RandomPoolPolicy(max_probability_error=0.0, max_helpers=9),
        )
        self.assertEqual(report.helper_count, 9)
        self.assertFalse(report.exact_probabilities)
        self.assertIn("ssc.random-probability-approximation", [d.code for d in report.diagnostics])


if __name__ == "__main__":
    unittest.main()
