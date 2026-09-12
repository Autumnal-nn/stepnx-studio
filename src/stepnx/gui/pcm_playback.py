from __future__ import annotations

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QTimer, Signal, Slot
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

try:
    from PySide6.QtMultimedia import QtAudio
except ImportError:  # Older supported PySide6 releases expose only QAudio.
    from PySide6.QtMultimedia import QAudio as QtAudio

from stepnx.authoring.pcm import CanonicalPcm


_PCM_UI_REFRESH_MS = 16
_PCM_OUTPUT_BUFFER_MS = 100
_PCM_CHANNELS = 2
_PCM_BYTES_PER_SAMPLE = 2


def _pcm_output_buffer_bytes(sample_rate: int) -> int:
    """Return a playback ringbuffer large enough to survive ordinary GUI stalls."""

    if sample_rate <= 0:
        raise ValueError("PCM sample rate must be positive")
    frames = max(1, round(sample_rate * _PCM_OUTPUT_BUFFER_MS / 1000.0))
    return frames * _PCM_CHANNELS * _PCM_BYTES_PER_SAMPLE


class PcmPlayback(QObject):
    """Play the analysis PCM, with a device-processed sample clock.

    No wall-clock extrapolation or compressed-file seeks. Device/driver latency
    remains a separate calibration quantity; processedUSecs is not advertised
    as an external measurement of the DAC.
    """

    positionChanged = Signal(int)
    playbackChanged = Signal(bool)
    errorOccurred = Signal(str)

    def __init__(self, pcm: CanonicalPcm, parent=None) -> None:
        super().__init__(parent)
        self.pcm = pcm
        self._buffer = QBuffer(self)
        self._source_data = QByteArray(pcm.samples)
        self._buffer.setData(self._source_data)
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink = None
        self._base_frame = 0
        self._last_frame = 0
        self._playing = False
        self._resetting = False
        self._click_configuration = None
        self._mixed_configuration = None
        self._mixed_data = None
        self._timer = QTimer(self)
        # Canonical PCM used to refresh at 100 Hz while the ordinary transport
        # refreshes around 60 Hz. The extra UI traffic buys no clock precision:
        # position_frames still reads QAudioSink.processedUSecs() on demand.
        self._timer.setInterval(_PCM_UI_REFRESH_MS)
        self._timer.timeout.connect(self._poll)

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def position_frames(self) -> int:
        if self._sink is not None and self._playing:
            processed = max(0, self._sink.processedUSecs())
            frame = self._base_frame + processed * self.pcm.sample_rate // 1_000_000
            self._last_frame = min(self.pcm.frame_count, max(self._last_frame, frame))
        return self._last_frame

    def _publish(self) -> None:
        self.positionChanged.emit(self.position_frames * 1000 // self.pcm.sample_rate)

    def set_clicks(self, click: tuple[int, ...], frames: tuple[int, ...]) -> None:
        from stepnx.authoring.pcm_metronome import mix_clicks

        configuration = (click, frames)
        if configuration == self._click_configuration:
            return
        if not click or not frames:
            data = self._source_data
        elif configuration == self._mixed_configuration:
            data = self._mixed_data
        else:
            data = QByteArray(mix_clicks(self.pcm.samples, click, frames))
            self._mixed_configuration = configuration
            self._mixed_data = data
        playing = self._playing
        self.pause()
        self._buffer.close()
        self._buffer.setData(data)
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._buffer.seek(self._last_frame * 4)
        self._click_configuration = configuration
        if playing:
            self.play()

    def _ensure_sink(self) -> bool:
        if self._sink is not None:
            return True
        device = QMediaDevices.defaultAudioOutput()
        audio_format = QAudioFormat()
        audio_format.setSampleRate(self.pcm.sample_rate)
        audio_format.setChannelCount(_PCM_CHANNELS)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if device.isNull() or not device.isFormatSupported(audio_format):
            self.errorOccurred.emit("PCM playback requires a 48 kHz stereo output device; waveform analysis remains available.")
            return False
        self._sink = QAudioSink(device, audio_format, self)
        self._sink.setVolume(0.8)
        # 4096 bytes at 48 kHz stereo S16 is only ~21 ms. Qt's QIODevice mode
        # feeds the audio thread through a ringbuffer, so a single expensive
        # timeline paint could exhaust that queue and inject silence. Keep a
        # deterministic but still modest 100 ms queue. This does not change
        # the transport clock, which remains processedUSecs().
        self._sink.setBufferSize(_pcm_output_buffer_bytes(self.pcm.sample_rate))
        self._sink.stateChanged.connect(self._sink_state_changed)
        return True

    @Slot()
    def _sink_state_changed(self) -> None:
        # Some PySide6 bindings retain QAudio::State in the signal metadata
        # while returning QtAudio.State from state(). Drop the signal argument
        # in Qt and read the correctly typed value directly from the sink.
        if self._sink is not None:
            self._state_changed(self._sink.state())

    def toggle(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        if self._playing or not self._ensure_sink():
            return
        if self._last_frame >= self.pcm.frame_count:
            self.seek_frame(0)
        self._base_frame = self._last_frame
        self._buffer.seek(self._base_frame * 4)
        self._playing = True
        self._sink.start(self._buffer)
        # start() can synchronously report a stop/end through stateChanged.
        # Do not resurrect playback after that handler has already paused it.
        if not self._playing:
            return
        error = self._sink.error()
        # Older Qt backends report a recoverable buffering shortage here.
        # The sink can continue playing: keep its clock and UI state attached.
        if error not in (QtAudio.Error.NoError, QtAudio.Error.UnderrunError):
            self.pause()
            self.errorOccurred.emit(f"PCM output failed: {error}")
            return
        self._timer.start()
        self.playbackChanged.emit(True)

    def _reset_sink(self) -> None:
        self._resetting = True
        try:
            if self._sink is not None:
                self._sink.reset()
        finally:
            self._resetting = False

    def pause(self) -> None:
        self._last_frame = self.position_frames
        self._playing = False
        self._timer.stop()
        self._reset_sink()
        self._publish()
        self.playbackChanged.emit(False)

    def seek_frame(self, frame: int) -> None:
        if not 0 <= frame <= self.pcm.frame_count:
            raise ValueError("PCM seek is outside the decoded stream")
        playing = self._playing
        self._playing = False
        self._timer.stop()
        self._reset_sink()
        self._base_frame = self._last_frame = int(frame)
        self._buffer.seek(frame * 4)
        self._publish()
        if playing and frame < self.pcm.frame_count:
            self.play()
        elif playing:
            self.playbackChanged.emit(False)

    def seek(self, milliseconds: int) -> None:
        self.seek_frame(self.pcm.frame_at_ms(milliseconds))

    def _poll(self) -> None:
        self._publish()

    def _state_changed(self, state) -> None:
        if self._resetting or self._sink is None:
            return
        if state == QtAudio.State.IdleState and self._buffer.atEnd():
            self._last_frame = self.pcm.frame_count
            self.pause()
        elif state == QtAudio.State.StoppedState and self._sink.error() != QtAudio.Error.NoError:
            error = self._sink.error()
            self.pause()
            self.errorOccurred.emit(f"PCM output stopped: {error}")

    def close(self) -> None:
        self.pause()
        self._buffer.close()
        self.deleteLater()
