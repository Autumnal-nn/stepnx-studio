from __future__ import annotations

import os
import struct
import unittest
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtMultimedia import QAudio
    from PySide6.QtWidgets import QApplication
    from stepnx.gui.audio_transport import AudioTransport
    from stepnx.gui.nxa_audio_alignment import effective_nxa_audio_offset_ms
    from stepnx.gui.pcm_playback import PcmPlayback
    from stepnx.gui.phase11_waveform import QtWaveformDecoder
    from stepnx.gui.phase11_waveform_precision import AdaptiveWaveformSummaryBuilder
except ImportError as exc:
    QApplication = None
    QT_ERROR = str(exc)
else:
    QT_ERROR = ""

from stepnx.authoring.pcm import decode_mp3_pcm
from stepnx.authoring.mp3_gapless import Mp3GaplessAnalysis
from tests.unit.test_pcm import FIXTURE


class _Sink:
    def __init__(self):
        self.processed = 0

    def processedUSecs(self):
        return self.processed

    def start(self, buffer):
        self.buffer = buffer

    def reset(self):
        self.processed = 0

    def error(self):
        return QAudio.Error.NoError


@unittest.skipIf(QApplication is None, QT_ERROR)
class PcmGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.pcm = decode_mp3_pcm(FIXTURE.read_bytes())

    def test_clock_uses_processed_frames_and_seek_discards_old_queue(self):
        playback = PcmPlayback(self.pcm)
        sink = _Sink()
        playback._sink = sink
        try:
            playback.play()
            sink.processed = 10_000
            playback._buffer.seek(9000)  # Simulate backend read-ahead.
            self.assertEqual(playback.position_frames, 480)
            playback.seek_frame(317)
            self.assertEqual(playback.position_frames, 317)
            self.assertEqual(playback._buffer.pos(), 317 * 4)
            sink.processed = 1000
            self.assertEqual(playback.position_frames, 365)
            playback.pause()
            self.assertEqual(playback.position_frames, 365)
            playback.seek_frame(1)
            self.assertEqual(playback.position_frames, 1)
            self.assertEqual(playback._buffer.read(4), self.pcm.samples[4:8])
        finally:
            playback.close()

    def test_pcm_path_never_reapplies_ffmpeg_gapless_trim(self):
        tagged = decode_mp3_pcm(b"synthetic metadata" + FIXTURE.read_bytes())
        gapless = Mp3GaplessAnalysis("LAME", 576, 1000, 1105, 48000)
        self.assertEqual(effective_nxa_audio_offset_ms(
            7, tagged.startup, gapless, nxa_profile=True, canonical_pcm=tagged
        ), -17)

    def test_mixed_click_seek_uses_same_sample_positions_as_music(self):
        playback = PcmPlayback(self.pcm)
        try:
            playback.set_clicks((1000, 1000, 2000, 2000), (317,))
            playback.seek_frame(318)
            original = struct.unpack("<hh", self.pcm.samples[318 * 4:319 * 4])
            self.assertEqual(struct.unpack("<hh", playback._buffer.read(4)),
                             tuple(max(-32768, min(32767, value + 2000)) for value in original))
            playback.set_clicks((), ())
            playback.seek_frame(318)
            self.assertEqual(playback._buffer.read(4), self.pcm.samples[318 * 4:319 * 4])
        finally:
            playback.close()

    def test_waveform_consumes_playback_pcm_without_stretching_partial_bucket(self):
        pcm = replace(self.pcm, samples=bytes(16 * 4) + struct.pack("<hh", 32000, -32000))
        decoder = QtWaveformDecoder()
        decoder._summaries = AdaptiveWaveformSummaryBuilder()
        results, errors = [], []
        loop = QEventLoop()
        decoder.waveformReady.connect(lambda value: (results.append(value), loop.quit()))
        decoder.failed.connect(lambda message: (errors.append(message), loop.quit()))
        QTimer.singleShot(3000, loop.quit)
        decoder.start_pcm(pcm)
        loop.exec()
        try:
            self.assertFalse(errors)
            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertEqual(result.duration_ms, 17 * 1000 / 48000)
            self.assertEqual(result.channels[0].range_at(result.duration_ms, 0.20, 0.30), (0.0, 0.0))
            self.assertGreater(result.channels[0].range_at(result.duration_ms, 16 / 48, 17 / 48)[1], 0.9)
            self.assertTrue(decoder.decoder.source().isEmpty())
        finally:
            decoder.stop()

    def test_source_switch_cancels_old_waveform_chunks(self):
        decoder = QtWaveformDecoder()
        results = []
        loop = QEventLoop()
        decoder.waveformReady.connect(lambda value: (results.append(value), loop.quit()))
        decoder.start_pcm(self.pcm)
        tiny = replace(self.pcm, samples=self.pcm.samples[:80])
        decoder.start_pcm(tiny)
        decoder.decoder.finished.emit()  # Late completion from the prior Qt source.
        self.assertFalse(results)
        QTimer.singleShot(3000, loop.quit)
        loop.exec()
        try:
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].duration_ms, 20 / 48)
        finally:
            decoder.stop()

    def test_transport_stages_exact_pcm_and_rejects_unreliable_replacement(self):
        transport = AudioTransport()
        transport.nxa_timing_enabled = True
        try:
            self.assertTrue(transport.load(FIXTURE))
            self.assertEqual(transport.canonical_pcm.samples, self.pcm.samples)
            self.assertEqual(transport.playback_source.suffix, ".wav")
            self.assertTrue(transport.player.source().isEmpty())
            self.assertFalse(transport.load(FIXTURE.with_name("missing.mp3")))
            self.assertIsNone(transport.canonical_pcm)
            self.assertIsNone(transport.playback_source)
        finally:
            transport.cleanup_aud_staging()


if __name__ == "__main__":
    unittest.main()
