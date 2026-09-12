from __future__ import annotations

import unittest
from types import SimpleNamespace

from stepnx.exporters.ssc import LINES_PER_MEASURE, SscChart, SscExportError
from stepnx.exporters.ssc_random import SscLabeledChart
from stepnx.exporters.ssc_xsanity import _materialize_startup_random


def _notes(rows: list[str], columns: int = 5) -> str:
    blank = "0" * columns
    padded = list(rows)
    if len(padded) % LINES_PER_MEASURE:
        padded.extend([blank] * (LINES_PER_MEASURE - len(padded) % LINES_PER_MEASURE))
    measures = []
    for start in range(0, len(padded), LINES_PER_MEASURE):
        measure = padded[start : start + LINES_PER_MEASURE]
        measures.append("\n".join(measure) + "\n")
    return ",\n".join(measures)


def _rows(notes: str, columns: int = 5) -> list[str]:
    blank = "0" * columns
    result: list[str] = []
    for measure in notes.rstrip("\n").split(",\n"):
        lines = measure.splitlines()
        if lines == [blank]:
            lines = [blank] * LINES_PER_MEASURE
        result.extend(lines)
    return result


def _chart(notes: str, description: str) -> SscChart:
    return SscChart(
        steps_type="pump-single",
        difficulty="Edit",
        description=description,
        meter=1,
        credit="",
        offset=0.0,
        bpms="0=120,",
        stops="",
        delays="",
        warps="",
        scrolls="0=1,",
        speeds="",
        notes=notes,
        noteskin_banks=(),
    )


def _report(base_rows: list[str], helper_rows: list[str]):
    return SimpleNamespace(
        helper_count=1,
        program=SimpleNamespace(base_snapshot=SimpleNamespace(columns=5)),
        charts=(
            SscLabeledChart(_chart(_notes(base_rows), "BASE"), "NORMAL"),
            SscLabeledChart(_chart(_notes(helper_rows), "HELPER"), "DIVISION", 0),
        ),
    )


class SscHoldSafeSwitchTests(unittest.TestCase):
    def test_startup_swap_restores_taps_and_hold_that_were_outside_sparse_window(self) -> None:
        blank = "00000"
        base_rows = [blank] * 64
        base_rows[8] = "10000"
        base_rows[10] = "01000"
        base_rows[12] = "20000"
        base_rows[20] = "T0000"
        base_rows[24] = "30000"
        base_rows[32] = "00010"

        helper_rows = [blank] * 64
        helper_rows[24] = "30000"
        helper_rows[32] = "00001"
        helper_rows[40] = "O0000"

        runtime = _materialize_startup_random(_report(base_rows, helper_rows))
        rebuilt_base = _rows(runtime[0].chart.notes)
        rebuilt_helper = _rows(runtime[1].chart.notes)

        self.assertIn("T", rebuilt_base[0])
        self.assertTrue(all("T" not in row for row in rebuilt_base[1:]))
        self.assertEqual(rebuilt_helper[8], "10000")
        self.assertEqual(rebuilt_helper[10], "01000")
        self.assertEqual(rebuilt_helper[12], "20000")
        self.assertEqual(rebuilt_helper[24], "30000")
        self.assertEqual(rebuilt_helper[32], "00001")
        self.assertTrue(all("O" not in row for row in rebuilt_helper))

    def test_startup_swap_rejects_chart_with_note_on_first_row(self) -> None:
        blank = "00000"
        base_rows = [blank] * 64
        base_rows[0] = "10000"
        base_rows[20] = "T0000"

        helper_rows = [blank] * 64
        helper_rows[40] = "O0000"

        with self.assertRaisesRegex(
            SscExportError,
            "no empty SSC row before its first judged note",
        ):
            _materialize_startup_random(_report(base_rows, helper_rows))


if __name__ == "__main__":
    unittest.main()
