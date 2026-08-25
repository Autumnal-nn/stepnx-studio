from __future__ import annotations

import os
import unittest
from array import array

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    from stepnx.authoring.timeline import TimelineGeometry
    from stepnx.gui.phase11_waveform_precision import (
        BASE_SUMMARY_FRAMES,
        AdaptiveWaveformChannelSummary,
        AdaptiveWaveformSummaryBuilder,
        _install_timing_line_note_alignment,
    )
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class Phase11WaveformPrecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_precision_builder_uses_sixteen_frame_base(self) -> None:
        builder = AdaptiveWaveformSummaryBuilder()
        self.assertEqual(builder.frames_per_summary, BASE_SUMMARY_FRAMES)
        self.assertEqual(BASE_SUMMARY_FRAMES, 16)

    def test_adaptive_summary_keeps_float32_storage(self) -> None:
        summary = AdaptiveWaveformChannelSummary(
            array("f", [-0.1, -0.8, -0.2, -0.6]),
            array("f", [0.2, 0.1, 0.9, 0.3]),
        )
        self.assertIsInstance(summary.minima, array)
        self.assertIsInstance(summary.maxima, array)
        self.assertEqual(summary.minima.typecode, "f")
        self.assertEqual(summary.maxima.typecode, "f")

    def test_adaptive_range_query_is_exact_across_pyramid_levels(self) -> None:
        summary = AdaptiveWaveformChannelSummary(
            array("f", [-0.1, -0.8, -0.2, -0.6, -0.3, -0.4, -0.7, -0.05]),
            array("f", [0.2, 0.1, 0.9, 0.3, 0.4, 0.6, 0.2, 0.8]),
        )
        low, high = summary.range_at(8.0, 1.0, 7.0)
        self.assertAlmostEqual(low, -0.8, places=5)
        self.assertAlmostEqual(high, 0.9, places=5)

    def test_note_centre_is_the_row_timing_line(self) -> None:
        _install_timing_line_note_alignment()
        geometry = TimelineGeometry(row_height=192.0)
        _x, y, _width, height = geometry.note_rect(2, 350.0, 192.0)
        self.assertAlmostEqual(y + height / 2.0, 350.0)


if __name__ == "__main__":
    unittest.main()
