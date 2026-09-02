from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from stepnx.authoring.snapshot import create_authoring_snapshot
from stepnx.authoring.timeline import TimelineGeometry, TimelineLayout
from stepnx.codecs.nx20 import parse_bytes
from stepnx.gui.editor_field_zoom import (
    EDITOR_ZOOM_PRESETS,
    scale_editor_geometry,
    set_timeline_editor_zoom,
)
from stepnx.gui.lightmap_visual_polish import lightmap_rect
from stepnx.gui.timeline_widget import TimelineWidget
from tests.fixture_factory import make_normal_nx20


class EditorFieldZoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        document = parse_bytes(make_normal_nx20(), row_storage="compact")
        cls.snapshot = create_authoring_snapshot(document)

    def test_presets_cover_100_through_300_in_25_percent_steps(self) -> None:
        self.assertEqual(
            EDITOR_ZOOM_PRESETS,
            (100, 125, 150, 175, 200, 225, 250, 275, 300),
        )

    def test_all_eight_new_presets_scale_only_timeline_geometry(self) -> None:
        baseline = TimelineGeometry()
        for percent in EDITOR_ZOOM_PRESETS[1:]:
            with self.subTest(percent=percent):
                scaled = scale_editor_geometry(baseline, 100, percent)
                factor = percent / 100.0
                self.assertAlmostEqual(scaled.row_height, 48.0 * factor)
                self.assertAlmostEqual(scaled.lane_width, 48.0 * factor)
                self.assertAlmostEqual(scaled.ruler_width, 92.0 * factor)
                self.assertAlmostEqual(scaled.block_info_width, 300.0 * factor)
                self.assertAlmostEqual(scaled.footer_height, 24.0 * factor)

    def test_editor_scale_preserves_existing_vertical_zoom_factor(self) -> None:
        vertical = TimelineGeometry().zoomed(1.15).zoomed(1.15)
        expected_ratio = vertical.row_height / vertical.lane_width
        scaled = scale_editor_geometry(vertical, 100, 300)
        self.assertAlmostEqual(scaled.row_height / scaled.lane_width, expected_ratio)
        restored = scale_editor_geometry(scaled, 300, 100)
        self.assertAlmostEqual(restored.row_height, vertical.row_height)
        self.assertAlmostEqual(restored.lane_width, vertical.lane_width)

    def test_layout_hit_testing_agrees_at_every_new_preset(self) -> None:
        baseline = TimelineGeometry()
        for percent in EDITOR_ZOOM_PRESETS[1:]:
            with self.subTest(percent=percent):
                geometry = scale_editor_geometry(baseline, 100, percent)
                layout = TimelineLayout(self.snapshot, geometry)
                segment = layout.segments[0]
                row_index = min(3, segment.block.row_count - 1)
                lane = min(2, self.snapshot.columns - 1)
                x = geometry.ruler_width + lane * geometry.lane_width + geometry.lane_width / 2
                y = segment.rows_top + row_index * segment.row_height + segment.row_height / 2
                hit = layout.cell_at(x, y)
                self.assertIsNotNone(hit)
                self.assertEqual(hit[1:], (row_index, lane))

    def test_widget_and_lightmap_geometry_follow_all_presets(self) -> None:
        widget = TimelineWidget(self.snapshot)
        try:
            baseline_widget_size = widget.size()
            previous_lane_width = widget._geometry.lane_width
            for percent in EDITOR_ZOOM_PRESETS[1:]:
                with self.subTest(percent=percent):
                    set_timeline_editor_zoom(widget, percent)
                    self.assertEqual(widget._stepnx_editor_zoom_percent, percent)
                    self.assertGreater(widget._geometry.lane_width, previous_lane_width)
                    rect = lightmap_rect(widget, 1, 0.0, widget._geometry.row_height)
                    self.assertAlmostEqual(rect.width(), widget._geometry.lane_width - 4.0)
                    self.assertEqual(widget.size(), baseline_widget_size)
                    previous_lane_width = widget._geometry.lane_width
        finally:
            widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
