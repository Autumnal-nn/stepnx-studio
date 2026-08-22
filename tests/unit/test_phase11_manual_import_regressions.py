from __future__ import annotations

import os
import struct
import unittest

from stepnx.importers.legacy import (
    LegacyBlock,
    LegacyChart,
    LegacyRow,
    parse_stf,
    project_nx20,
)


class ManualLegacyImportRegressionTests(unittest.TestCase):
    def test_stepedit_stf_grid_projects_as_beat_split_two(self) -> None:
        data = bytearray(280 + 1024 * 14)
        struct.pack_into("<f", data, 256, 120.0)
        data[280:] = b"0" * (1024 * 14)
        chart = parse_stf(bytes(data), source="legacy.STF")

        self.assertEqual(chart.blocks[0].beat_split, 2)
        projected = project_nx20(chart)
        self.assertEqual(int(projected.splits[0].blocks[0].beat_split.value), 2)


os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
try:
    from PySide6.QtWidgets import QApplication

    from stepnx.gui.phase10_preview import Phase10GameplayPreviewWidget
    from stepnx.preview import (
        RoutePolicy,
        build_event_stream,
        create_preview_snapshot,
        resolve_route,
    )
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class HalfDoublePreviewRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_half_double_uses_double_backing_with_two_lane_offset(self) -> None:
        chart = LegacyChart(
            "synthetic-hf",
            6,
            (
                LegacyBlock(
                    120.0,
                    4,
                    4,
                    0.0,
                    (LegacyRow((1, 0, 0, 0, 0, 1)),),
                ),
            ),
        )
        document = project_nx20(chart, start_column=2)
        snapshot = create_preview_snapshot(document)
        route = resolve_route(snapshot, RoutePolicy.MANUAL)
        widget = Phase10GameplayPreviewWidget(
            build_event_stream(snapshot, route),
            columns=snapshot.columns,
            start_column=snapshot.start_column,
        )
        try:
            widget.resize(1200, 480)
            geometry = widget._geometry()
            self.assertEqual((widget.columns, widget.start_column), (6, 2))
            self.assertEqual(geometry.columns, 10)
            self.assertEqual(widget.field_mode, "DOUBLE")
            self.assertAlmostEqual(widget.lane_center(0), geometry.lane_center(2))
            self.assertAlmostEqual(widget.lane_center(5), geometry.lane_center(7))
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
