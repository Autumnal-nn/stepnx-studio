from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat

from stepnx.authoring.audio import WaveformEnvelope


_TARGET_PEAKS_PER_SECOND = 100
_MAX_WAVEFORM_POINTS = 4096


def _reduce_peaks(peaks: list[float], maximum: int = _MAX_WAVEFORM_POINTS) -> tuple[float, ...]:
    if not peaks:
        return ()
    if len(peaks) <= maximum:
        return tuple(peaks)
    width = len(peaks) / maximum
    reduced: list[float] = []
    for bucket in range(maximum):
        start = int(bucket * width)
        end = max(start + 1, int((bucket + 1) * width))
        reduced.append(max(peaks[start:min(len(peaks), end)]))
    return tuple(reduced)


def _chunk_peak(samples, sample_format) -> float:
    if not samples:
        return 0.0
    low = min(samples)
    high = max(samples)
    if sample_format == QAudioFormat.SampleFormat.UInt8:
        return min(1.0, max(abs(float(low) - 128.0), abs(float(high) - 128.0)) / 128.0)
    if sample_format == QAudioFormat.SampleFormat.Int16:
        return min(1.0, max(abs(int(low)), abs(int(high))) / 32768.0)
    if sample_format == QAudioFormat.SampleFormat.Int32:
        return min(1.0, max(abs(int(low)), abs(int(high))) / 2147483648.0)
    if sample_format == QAudioFormat.SampleFormat.Float:
        return min(1.0, max(abs(float(low)), abs(float(high))))
    raise ValueError(f"unsupported decoded sample format: {sample_format}")


def _buffer_peaks(buffer) -> list[float]:
    """Collapse a decoded QAudioBuffer to roughly 100 amplitude peaks/second."""

    audio_format = buffer.format()
    rate = int(audio_format.sampleRate())
    channels = int(audio_format.channelCount())
    sample_format = audio_format.sampleFormat()
    if rate <= 0 or channels <= 0:
        raise ValueError("decoded audio buffer has invalid sample rate/channel count")

    raw = bytes(buffer.constData())
    if sample_format == QAudioFormat.SampleFormat.UInt8:
        samples = memoryview(raw).cast("B")
    elif sample_format == QAudioFormat.SampleFormat.Int16:
        samples = memoryview(raw).cast("h")
    elif sample_format == QAudioFormat.SampleFormat.Int32:
        samples = memoryview(raw).cast("i")
    elif sample_format == QAudioFormat.SampleFormat.Float:
        samples = memoryview(raw).cast("f")
    else:
        raise ValueError(f"unsupported decoded sample format: {sample_format}")

    samples_per_bucket = max(1, round(rate * channels / _TARGET_PEAKS_PER_SECOND))
    result: list[float] = []
    for start in range(0, len(samples), samples_per_bucket):
        result.append(_chunk_peak(samples[start : start + samples_per_bucket], sample_format))
    return result


class QtWaveformDecoder(QObject):
    """Asynchronously derive a WaveformEnvelope from Qt-supported audio.

    The decoder intentionally consumes the exact local file handed to
    QMediaPlayer. For ENC2 AUD this is AudioTransport's staged decoded MP3, so
    playback and waveform cannot diverge through two independent decrypt paths.
    """

    waveformReady = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.decoder = QAudioDecoder(self)
        self.decoder.bufferReady.connect(self._buffer_ready)
        self.decoder.finished.connect(self._finished)
        self.decoder.isDecodingChanged.connect(self._decoding_changed)
        self._peaks: list[float] = []
        self._duration_us = 0
        self._active = False
        self._finished_successfully = False
        self._source: Path | None = None

    def start(self, path: str | Path) -> None:
        source = Path(path).resolve()
        self.decoder.stop()
        self._peaks.clear()
        self._duration_us = 0
        self._active = False
        self._finished_successfully = False
        self._source = source

        if not source.is_file():
            self.failed.emit(f"waveform source does not exist: {source}")
            return
        if not self.decoder.isSupported():
            self.failed.emit("Qt Multimedia audio decoding is not supported on this system")
            return

        # A mono 11.025 kHz Int16 projection is ample for a visual amplitude
        # envelope and keeps Python-side analysis bounded for long songs. The
        # default Windows Qt backend performs this conversion while decoding.
        desired = QAudioFormat()
        desired.setSampleRate(11025)
        desired.setChannelCount(1)
        desired.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self.decoder.setAudioFormat(desired)
        self.decoder.setSource(QUrl.fromLocalFile(str(source)))
        self._active = True
        self.decoder.start()

    def stop(self) -> None:
        self._active = False
        self.decoder.stop()

    def _buffer_ready(self) -> None:
        if not self._active:
            return
        buffer = self.decoder.read()
        if not buffer.isValid():
            return
        try:
            self._peaks.extend(_buffer_peaks(buffer))
        except (TypeError, ValueError) as exc:
            self._active = False
            self.decoder.stop()
            self.failed.emit(f"cannot analyze decoded audio buffer: {exc}")
            return

        start_us = int(buffer.startTime())
        duration_us = max(0, int(buffer.duration()))
        if start_us >= 0:
            self._duration_us = max(self._duration_us, start_us + duration_us)
        else:
            self._duration_us += duration_us

    def _finished(self) -> None:
        if not self._active:
            return
        self._finished_successfully = True
        self._active = False
        decoder_duration = int(self.decoder.duration())
        duration_ms = max(
            0.0,
            self._duration_us / 1000.0,
            float(decoder_duration if decoder_duration > 0 else 0),
        )
        peaks = _reduce_peaks(self._peaks)
        if not peaks or not math.isfinite(duration_ms) or duration_ms <= 0.0:
            self.failed.emit("decoded audio did not produce a usable waveform")
            return
        try:
            waveform = WaveformEnvelope(duration_ms, peaks)
        except ValueError as exc:
            self.failed.emit(f"decoded waveform is invalid: {exc}")
            return
        self.waveformReady.emit(waveform)

    def _decoding_changed(self, decoding: bool) -> None:
        if decoding or not self._active or self._finished_successfully:
            return
        error = self.decoder.error()
        if error != QAudioDecoder.Error.NoError:
            self._active = False
            message = self.decoder.errorString() or str(error)
            self.failed.emit(f"waveform decoder error: {message}")


def _publish_waveform(window, waveform: WaveformEnvelope) -> None:
    window.waveform = waveform
    for index in range(window.tabs.count()):
        widget = window.tabs.widget(index)
        if hasattr(widget, "set_waveform"):
            widget.set_waveform(window.waveform, window.audio_alignment)
    window.statusBar().showMessage(
        f"Waveform ready: {len(waveform.peaks)} peak buckets", 5000
    )


def install_phase11_waveform(window) -> None:
    if getattr(window, "_phase11_waveform_installed", False):
        return
    window._phase11_waveform_installed = True

    decoder = QtWaveformDecoder(window)
    window.phase11_waveform_decoder = decoder
    decoder.waveformReady.connect(lambda waveform: _publish_waveform(window, waveform))
    decoder.failed.connect(
        lambda message: window.statusBar().showMessage(
            f"Waveform unavailable: {message}", 8000
        )
    )

    original_load_audio = window._load_audio

    def load_audio_with_waveform(path: Path) -> None:
        original_load_audio(path)
        source = window.audio_transport.playback_source
        if source is None:
            decoder.stop()
            return

        # Base Phase 8 already provides a synchronous PCM-WAV path. Reuse it
        # when successful; QAudioDecoder is the compressed/staged fallback.
        if source.suffix.casefold() == ".wav" and window.waveform is not None:
            decoder.stop()
            return

        decoder.start(source)
        window.statusBar().showMessage(
            f"Loaded audio: {Path(path).name} · decoding waveform…", 5000
        )

    window._load_audio = load_audio_with_waveform
