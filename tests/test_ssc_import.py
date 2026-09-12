from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stepnx.exporters.ssc import export_chart
from stepnx.importers.andamiro import AndamiroImportResult
from stepnx.importers.dispatch import load_importable
from stepnx.importers.ssc import parse_ssc


def _ssc(*, steps_type: str, description: str, notes: str, meter: int = 7) -> bytes:
    return f"""#VERSION:0.83;
#TITLE:SSC import fixture;
#OFFSET:-1;
#BPMS:0=120;
#SCROLLS:0=1;
#SPEEDS:0=1=0=0;
#NOTEDATA:;
#STEPSTYPE:{steps_type};
#DESCRIPTION:{description};
#METER:{meter};
#OFFSET:-1;
#BPMS:0=120;
#SCROLLS:0=1;
#SPEEDS:0=1=0=0;
#NOTES:
{notes}
;
""".encode("utf-8")


class SscImportTests(unittest.TestCase):
    def test_halfdouble_geometry_meter_and_hold_projection(self) -> None:
        data = _ssc(
            steps_type="pump-halfdouble",
            description="HD7",
            notes="\n".join(("200000", "000000", "300000", "000000")),
        )
        result = parse_ssc(data, source="fixture.ssc")
        self.assertEqual(len(result.charts), 1)
        document = result.charts[0].document
        self.assertEqual(int(document.columns.value), 6)
        self.assertEqual(int(document.start_column.value), 2)
        self.assertTrue(
            any(
                (int(entry.meta_id.value) & 0xFFFF) == 1001
                and int(entry.value.value) == 7
                for entry in document.header_metadata
            )
        )
        rendered = export_chart(document, description="HD7")
        self.assertIn("2", rendered.chart.notes)
        self.assertIn("3", rendered.chart.notes)

    def test_stepf2_and_xsanity_extensions_are_accepted_with_diagnostics(self) -> None:
        rows = ["00000"] * 32
        rows[0] = "{1|v|0|0}0000"
        rows[8] = "X0000"
        rows[16] = "{103}0000"
        rows[24] = "{z07}0000"
        result = parse_ssc(
            _ssc(steps_type="pump-single", description="S9", notes="\n".join(rows), meter=9),
            source="extensions.ssc",
        )
        chart = result.charts[0]
        self.assertTrue(any("ssc.stepf2.player-ownership" in d for d in chart.diagnostics))
        rendered = export_chart(chart.document, description="S9")
        self.assertIn("{101}", rendered.chart.notes)
        self.assertIn("{103}", rendered.chart.notes)
        self.assertIn("{z07}", rendered.chart.notes)

    def test_couple_uses_actual_notefield_width_and_recovers_missing_stepstype_semicolon(self) -> None:
        data = b"""#VERSION:0.81;
#BPMS:0=120;
#NOTEDATA:;
#STEPSTYPE:pump-couple
#DESCRIPTION:DP COUPLE 8;
#METER:8;
#NOTES:
1000010000
0000000000
0000000000
0000000000
;
"""
        result = parse_ssc(data, source="couple.ssc")
        chart = result.charts[0]
        self.assertEqual(int(chart.document.columns.value), 10)
        self.assertTrue(any("ssc.style.projection" in d for d in chart.diagnostics))

    def test_dispatch_loads_ssc_through_authoring_import_path(self) -> None:
        data = _ssc(
            steps_type="pump-single",
            description="S4",
            notes="\n".join(("10000", "00000", "00000", "00000")),
            meter=4,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.ssc"
            path.write_bytes(data)
            result = load_importable(path)
        self.assertIsInstance(result, AndamiroImportResult)
        self.assertEqual(result.charts[0].source_format, "ssc")
        self.assertEqual(result.charts[0].default_filename, "S4.NX")


if __name__ == "__main__":
    unittest.main()
