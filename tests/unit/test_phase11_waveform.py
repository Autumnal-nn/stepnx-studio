from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from stepnx.authoring import WaveformEnvelope, create_authoring_snapshot
    from stepnx.codecs.nx20 import parse_bytes
    from stepnx.gui.phase11_waveform import (
        WaveformChannelSummary,
        WaveformRenderData,
        _draw_waveform_field,
        _preferred_song_path,
        _reduce_peaks,
    )
    from stepnx.gui.timeline_widget import TimelineWidget
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""

from tests.fixture_factory import make_large_lightmap


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class Phase11WaveformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_song_autoload_uses_historical_priority_and_windows_casefold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            folder = parent / "D123"
            folder.mkdir()
            nxa = parent / "d123.MP3"
            fiesta = parent / "a.Mp3"
            ksf = folder / "sOnG.Mp3"
            nxa.write_bytes(b"nxa")
            fiesta.write_bytes(b"fiesta")
            ksf.write_bytes(b"ksf")

            self.assertEqual(_preferred_song_path(folder), nxa.resolve())
            nxa.unlink()
            self.assertEqual(_preferred_song_path(folder), fiesta.resolve())
            fiesta.unlink()
            self.assertEqual(_preferred_song_path(folder), ksf.resolve())
            ksf.unlink()
            self.assertIsNone(_preferred_song_path(folder))

    def test_compressed_waveform_keeps_editor_scale_resolution(self) -> None:
        peaks = [0.25] * 30_000
        self.assertEqual(len(_reduce_peaks(peaks)), 30_000)

    def test_bpm_reduction_preserves_transient_maximum(self) -> None:
        self.assertEqual(_reduce_peaks([0.0, 1.0, 0.0, 0.0], 2), (1.0, 0.0))

    def test_channel_range_aggregates_every_summary_touched_by_pixel(self) -> None:
        channel = WaveformChannelSummary(
            (-0.1, -0.8, -0.2, -0.4),
            (0.2, 0.3, 0.9, 0.5),
        )
        self.assertEqual(channel.range_at(40.0, 9.0, 31.0), (-0.8, 0.9))

    def test_waveform_is_drawn_across_note_field_not_timing_ruler(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=8), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(500, 300)
            waveform = WaveformEnvelope(60_000.0, (1.0,) * 6000)
            widget.set_waveform(waveform)
            visible = widget._layout.visible_segments(0.0, 250.0, overscan_rows=0)[0]
            canvas = QImage(600, 400, QImage.Format.Format_ARGB32)
            canvas.fill(0)
            painter = QPainter(canvas)
            try:
                _draw_waveform_field(widget, painter, visible, waveform)
            finally:
                painter.end()

            centre_x = round(
                widget._geometry.ruler_width + widget._layout.lane_area_width / 2
            )
            self.assertGreater(canvas.pixelColor(centre_x, 10).alpha(), 0)
            self.assertEqual(canvas.pixelColor(10, 10).alpha(), 0)
        finally:
            widget.close()

    def test_stereo_waveform_draws_two_separate_signed_channel_traces(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=8), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(500, 300)
            aggregate = WaveformEnvelope(60_000.0, (0.3,) * 6000)
            channel = WaveformChannelSummary(
                (-0.3,) * 6000,
                (0.3,) * 6000,
            )
            waveform = WaveformRenderData(aggregate, (channel, channel))
            widget.set_waveform(waveform)
            visible = widget._layout.visible_segments(0.0, 250.0, overscan_rows=0)[0]
            canvas = QImage(600, 400, QImage.Format.Format_ARGB32)
            canvas.fill(0)
            painter = QPainter(canvas)
            try:
                _draw_waveform_field(widget, painter, visible, waveform)
            finally:
                painter.end()

            left = widget._geometry.ruler_width
            width = widget._layout.lane_area_width
            left_channel = round(left + width * 0.25)
            right_channel = round(left + width * 0.75)
            centre = round(left + width * 0.5)

            self.assertGreater(canvas.pixelColor(left_channel, 10).alpha(), 0)
            self.assertGreater(canvas.pixelColor(right_channel, 10).alpha(), 0)
            self.assertEqual(canvas.pixelColor(centre, 10).alpha(), 0)
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
