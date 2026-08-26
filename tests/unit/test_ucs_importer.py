from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stepnx.importers import load_importable, parse_ucs, project_nx20
from tests.fixture_factory import make_normal_nx20


class UCSImporterTests(unittest.TestCase):
    def test_single_multisegment_ucs_projects_taps_holds_and_timing(self) -> None:
        source = b""":Format=1\n:Mode=Single\n:BPM=120\n:Delay=0\n:Beat=4\n:Split=4\nX....\n.....\nM....\nH....\nW....\n:BPM=150\n:Delay=12,5\n:Beat=3\n:Split=8\n....X\n"""
        chart = parse_ucs(source, source="fixture.ucs")
        self.assertEqual(chart.source_format, "ucs")
        self.assertEqual(chart.columns, 5)
        self.assertEqual(len(chart.blocks), 2)
        self.assertEqual(chart.blocks[0].bpm, 120.0)
        self.assertEqual(chart.blocks[1].bpm, 150.0)
        self.assertEqual(chart.blocks[1].delay_ms, 12.5)
        self.assertEqual(chart.blocks[1].beat_measure, 3)
        self.assertEqual(chart.blocks[1].beat_split, 8)
        self.assertEqual(chart.blocks[0].rows[0].cells, (1, 0, 0, 0, 0))
        self.assertEqual(chart.blocks[0].rows[2].cells[0], 2)
        self.assertEqual(chart.blocks[0].rows[3].cells[0], 3)
        self.assertEqual(chart.blocks[0].rows[4].cells[0], 4)

        projected = project_nx20(chart)
        self.assertEqual(int(projected.columns.value), 5)
        self.assertEqual(len(projected.splits), 2)

    def test_performance_mode_is_preserved_as_explicit_approximation(self) -> None:
        source = b":Format=1\n:Mode=D-Performance\n:BPM=120\n:Delay=0\n:Beat=4\n:Split=4\nX.........\n"
        chart = parse_ucs(source)
        self.assertEqual(chart.columns, 10)
        self.assertTrue(any(item.code == "ucs.performance-mode" for item in chart.diagnostics))

    def test_unknown_directive_is_preserved_not_invented(self) -> None:
        source = b":Format=1\n:Mode=Single\n:EditorFoo=bar\n:BPM=120\n:Delay=0\n:Beat=4\n:Split=4\n.....\n"
        chart = parse_ucs(source)
        self.assertIn(("EditorFoo", "bar"), chart.controls)
        self.assertTrue(any(item.code == "ucs.directive.unknown" for item in chart.diagnostics))

    def test_invalid_row_width_and_symbol_are_rejected(self) -> None:
        prefix = b":Format=1\n:Mode=Single\n:BPM=120\n:Delay=0\n:Beat=4\n:Split=4\n"
        with self.assertRaises(Exception):
            parse_ucs(prefix + b"X...\n")
        with self.assertRaises(Exception):
            parse_ucs(prefix + b"X..A.\n")

    def test_dispatch_accepts_ucs_suffix(self) -> None:
        source = b":Format=1\n:Mode=Single\n:BPM=120\n:Delay=0\n:Beat=4\n:Split=4\n.....\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chart.UCS"
            path.write_bytes(source)
            chart = load_importable(path)
        self.assertEqual(chart.source_format, "ucs")


if __name__ == "__main__":
    unittest.main()
