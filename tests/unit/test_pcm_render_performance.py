from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    from stepnx.gui.pcm_playback import (
        _PCM_OUTPUT_BUFFER_MS,
        _PCM_UI_REFRESH_MS,
        _pcm_output_buffer_bytes,
    )
    from stepnx.gui.phase11_render_performance import (
        _playback_tile_ranges,
        _waveform_viewport_bounds,
    )
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


class _ScrollBar:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value


class _Viewport:
    def __init__(self, height: int) -> None:
        self._height = height

    def height(self) -> int:
        return self._height


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class PcmRenderPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_pcm_refresh_matches_display_scale_instead_of_100_hz(self) -> None:
        self.assertEqual(_PCM_UI_REFRESH_MS, 16)

    def test_pcm_ringbuffer_has_about_one_tenth_second_of_headroom(self) -> None:
        self.assertEqual(_PCM_OUTPUT_BUFFER_MS, 100)
        self.assertEqual(_pcm_output_buffer_bytes(48_000), 19_200)

    def test_waveform_bounds_clip_a_huge_row_to_the_real_viewport(self) -> None:
        segment = SimpleNamespace(
            rows_top=0.0,
            bottom=12_288.0,
            y_for_row=lambda row: row * 6144.0,
        )
        visible = SimpleNamespace(segment=segment, first_row=0, last_row=1)
        widget = SimpleNamespace(
            verticalScrollBar=lambda: _ScrollBar(2_000),
            viewport=lambda: _Viewport(800),
        )
        self.assertEqual(_waveform_viewport_bounds(widget, visible), (2000.0, 2800.0))

    def test_subpixel_playback_uses_stable_row_tiles(self) -> None:
        segment = SimpleNamespace(
            row_height=0.5,
            block=SimpleNamespace(row_count=5000),
        )
        visible = SimpleNamespace(segment=segment, first_row=700, last_row=1900)
        self.assertEqual(
            _playback_tile_ranges(visible),
            ((512, 1024), (1024, 1536), (1536, 2048)),
        )


if __name__ == "__main__":
    unittest.main()
