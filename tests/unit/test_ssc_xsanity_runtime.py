from __future__ import annotations

import unittest
from types import SimpleNamespace

from stepnx.exporters import SscSongInfo, render_compiled_simfile
from stepnx.exporters.ssc import SscChart
from stepnx.exporters.ssc_random import SscLabeledChart


def chart(description: str, notes: str) -> SscChart:
    return SscChart(
        steps_type="pump-double",
        difficulty="Edit",
        description=description,
        meter=22,
        credit="",
        offset=0.0,
        bpms="0=100,",
        stops="",
        delays="",
        warps="",
        scrolls="0=2,",
        speeds="0=1=1=1,",
        notes=notes,
        noteskin_banks=(),
    )


class XSanityRuntimeRenderTest(unittest.TestCase):
    def test_compiled_steps_get_unique_chartnames_labels_and_tickcounts(self) -> None:
        base = SscLabeledChart(chart("D22_22.NX", "T000000000\n"), "NORMAL")
        helper1 = SscLabeledChart(
            chart("D22_22.NX [StepNX random 1]", "O000000000\n"),
            "DIVISION",
            0,
        )
        helper2 = SscLabeledChart(
            chart("D22_22.NX [StepNX random 2]", "O000000000\n"),
            "DIVISION",
            1,
        )
        report = SimpleNamespace(charts=(base, helper1, helper2))

        text = render_compiled_simfile(report, SscSongInfo(title="1309"))

        self.assertTrue(text.startswith("#VERSION:0.83;\n"))
        self.assertNotIn("#VERSION:0.83 xSanity;", text)
        self.assertIn("#CHARTNAME:STEPNX_BASE;", text)
        self.assertIn("#CHARTNAME:STEPNX_RANDOM_001;", text)
        self.assertIn("#CHARTNAME:STEPNX_RANDOM_002;", text)
        self.assertEqual(text.count("#CHARTNAME:"), 3)
        self.assertEqual(text.count("#LABELTYPE:NORMAL;"), 1)
        self.assertEqual(text.count("#LABELTYPE:DIVISION;"), 2)
        self.assertEqual(text.count("#TICKCOUNTS:0.000000=8;"), 3)
        # Bare T/O are valid Sanity cells (e.g. Cleaner); the runtime envelope,
        # not the control-token spelling, is what this layer hardens.
        self.assertIn("T000000000", text)
        self.assertIn("O000000000", text)

    def test_generated_chartnames_are_unique_beyond_historical_nine_routes(self) -> None:
        items = [SscLabeledChart(chart("base", "0000000000\n"), "NORMAL")]
        items.extend(
            SscLabeledChart(chart(f"helper {index}", "0000000000\n"), "DIVISION", index)
            for index in range(20)
        )
        report = SimpleNamespace(charts=tuple(items))

        text = render_compiled_simfile(report, SscSongInfo(title="1309"))

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
