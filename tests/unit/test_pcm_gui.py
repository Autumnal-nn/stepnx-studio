from __future__ import annotations

import os
import struct
import unittest
from unittest.mock import patch
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtCore import QEventLoop, QTimer, QMetaObject, Qt
    from PySide6.QtMultimedia import QAudioSink
    try:
        from PySide6.QtMultimedia import QtAudio
    except ImportError:
        from PySide6.QtMultimedia import QAudio as QtAudio
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
        self.start_error = QtAudio.Error.NoError
        self.running = False
        self.starts = 0

    def processedUSecs(self):
        return self.processed

    def start(self, buffer):
        self.buffer = buffer
        self.running = True
        self.starts += 1

    def reset(self):
        self.processed = 0
        self.running = False

    def error(self):
        return self.start_error

    def state(self):
        return QtAudio.State.ActiveState if self.running else QtAudio.State.StoppedState


@unittest.skipIf(QApplication is None, QT_ERROR)
class PcmGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.pcm = decode_mp3_pcm(FIXTURE.read_bytes())

    def test_state_callback_is_a_zero_argument_qt_slot(self):
        playback = PcmPlayback(self.pcm)
        playback._sink = _Sink()
        try:
            meta = playback.metaObject()
            index = meta.indexOfSlot('_sink_state_changed()')
            self.assertGreaterEqual(index, 0)
            self.assertEqual(meta.method(index).parameterCount(), 0)
            with patch.object(playback, '_state_changed') as handler:
                self.assertTrue(QMetaObject.invokeMethod(
                    playback, '_sink_state_changed', Qt.ConnectionType.DirectConnection))
                handler.assert_called_once_with(QtAudio.State.StoppedState)
        finally:
            playback.close()

    def test_metronome_reenable_reuses_mix_but_changed_schedule_invalidates_it(self):
        from stepnx.authoring.pcm_metronome import mix_clicks

        playback = PcmPlayback(self.pcm)
        try:
            with patch('stepnx.authoring.pcm_metronome.mix_clicks', wraps=mix_clicks) as mixer:
                playback.set_clicks((100, -100), (3,))
                first = bytes(playback._buffer.data())
                playback.set_clicks((), ())
                self.assertEqual(bytes(playback._buffer.data()), self.pcm.samples)
                playback.set_clicks((100, -100), (3,))
                self.assertEqual(bytes(playback._buffer.data()), first)
                self.assertEqual(mixer.call_count, 1)
                playback.set_clicks((100, -100), (4,))
                self.assertEqual(mixer.call_count, 2)
                self.assertNotEqual(bytes(playback._buffer.data()), first)
        finally:
            playback.close()

    def test_simulated_sink_uses_enum_types_returned_by_real_qt(self):
        # No device or playback is required to inspect the real binding types.
        # QAudio and QtAudio coexist in newer PySide6, but their enums differ.
        probe = QAudioSink()
        try:
            self.assertIs(type(_Sink().error()), type(probe.error()))
            self.assertIs(QtAudio.State, type(probe.state()))
        finally:
            probe.deleteLater()

    def test_real_qt_state_type_drives_completion_and_device_failure(self):
        probe = QAudioSink()
        state_type, error_type = type(probe.state()), type(probe.error())
        probe.deleteLater()
        for end_of_file in (True, False):
            with self.subTest(end_of_file=end_of_file):
                playback = PcmPlayback(self.pcm)
                sink = _Sink()
                playback._sink = sink
                states, errors = [], []
                playback.playbackChanged.connect(states.append)
                playback.errorOccurred.connect(errors.append)
                try:
                    playback.play()
                    if end_of_file:
                        playback._buffer.seek(playback._buffer.size())
                        playback._state_changed(state_type.IdleState)
                        self.assertEqual(playback.position_frames, self.pcm.frame_count)
                        self.assertFalse(errors)
                    else:
                        sink.start_error = error_type.IOError
                        playback._state_changed(state_type.StoppedState)
                        self.assertEqual(len(errors), 1)
                    self.assertEqual(states, [True, False])
                    self.assertFalse(playback.playing)
                    self.assertFalse(sink.running)
                    self.assertFalse(playback._timer.isActive())
                finally:
                    playback.close()

    def test_startup_underrun_keeps_transport_clock_and_pause_connected(self):
        transport = AudioTransport()
        transport.nxa_timing_enabled = True
        states, positions, errors = [], [], []
        transport.playbackChanged.connect(states.append)
        transport.positionChanged.connect(positions.append)
        transport.errorOccurred.connect(errors.append)
        try:
            self.assertTrue(transport.load(FIXTURE))
            playback = transport._pcm_playback
            sink = _Sink()
            sink.start_error = QtAudio.Error.UnderrunError
            playback._sink = sink
            transport.toggle()
            self.assertTrue(sink.running)
            self.assertTrue(playback.playing)
            self.assertTrue(playback._timer.isActive())
            self.assertTrue(states[-1])
            sink.processed = 100_000
            playback._poll()
            self.assertEqual(positions[-1], 100)
            transport.toggle()
            self.assertFalse(sink.running)
            self.assertFalse(playback.playing)
            self.assertFalse(states[-1])
            self.assertEqual(sink.starts, 1)
            self.assertEqual(playback.position_frames, 4800)
            self.assertFalse(errors)
        finally:
            transport.cleanup_aud_staging()

    def test_failed_start_resets_output_instead_of_leaving_audio_running(self):
        for error in (QtAudio.Error.OpenError, QtAudio.Error.IOError, QtAudio.Error.FatalError):
            with self.subTest(error=error):
                playback = PcmPlayback(self.pcm)
                sink = _Sink()
                sink.start_error = error
                playback._sink = sink
                states, errors = [], []
                playback.playbackChanged.connect(states.append)
                playback.errorOccurred.connect(errors.append)
                try:
                    playback.play()
                    self.assertFalse(sink.running)
                    self.assertFalse(playback.playing)
                    self.assertFalse(playback._timer.isActive())
                    self.assertEqual(states, [False])
                    self.assertEqual(len(errors), 1)
                finally:
                    playback.close()

    def test_synchronous_start_failure_does_not_publish_playing_after_stop(self):
        playback = PcmPlayback(self.pcm)

        class FailingSink(_Sink):
            def start(self, buffer):
                super().start(buffer)
                playback._state_changed(QtAudio.State.StoppedState)

            def reset(self):
                super().reset()
                self.start_error = QtAudio.Error.NoError

        sink = FailingSink()
        sink.start_error = QtAudio.Error.OpenError
        playback._sink = sink
        states, errors = [], []
        playback.playbackChanged.connect(states.append)
        playback.errorOccurred.connect(errors.append)
        try:
            playback.play()
            self.assertFalse(playback.playing)
            self.assertFalse(sink.running)
            self.assertFalse(playback._timer.isActive())
            self.assertEqual(states, [False])
            self.assertEqual(len(errors), 1)
        finally:
            playback.close()

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
