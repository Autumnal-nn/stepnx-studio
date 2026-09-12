from __future__ import annotations

import unittest

from stepnx.authoring.timeline import TimelineGeometry


class TimelineZoomFloorTests(unittest.TestCase):
    def test_interactive_zoom_clamps_before_pathological_four_pixel_view(self) -> None:
        geometry = TimelineGeometry()

        zoomed = geometry.zoomed(0.000001)

        self.assertEqual(zoomed.row_height, 12.0)
        self.assertEqual(zoomed.minimum_row_height, 4.0)

    def test_explicit_four_pixel_geometry_remains_representable(self) -> None:
        geometry = TimelineGeometry(row_height=4.0)

        self.assertEqual(geometry.row_height, 4.0)

    def test_stricter_custom_minimum_is_preserved(self) -> None:
        geometry = TimelineGeometry(row_height=48.0, minimum_row_height=20.0)

        self.assertEqual(geometry.zoomed(0.01).row_height, 20.0)


if __name__ == "__main__":
    unittest.main()
