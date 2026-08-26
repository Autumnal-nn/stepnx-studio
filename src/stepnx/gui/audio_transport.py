from __future__ import annotations

import struct
import sys
import wave
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QElapsedTimer,
    QObject,
    QTemporaryDir,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtMultimedia import (
    QAudioFormat,
    QAudioOutput,
    QAudioSink,
    QMediaDevices,
    QMediaPlayer,
    QSoundEffect,
)

from stepnx.authoring.audio import AudDecodeError, decode_enc2_aud


_METRONOME_VOICES = 8
_LINUX_MIXER_MAX_VOICES = 8
_LINUX_MIXER_BUFFER_MS = 20
_LINUX_MIXER_IDLE_QUEUE_MS = 4
_LINUX_MIXER_ACTIVE_QUEUE_MS = 8
_LINUX_MIXER_PUMP_MS = 2


def _uses_linux_metronome_sink(platform: str | None = None) -> bool:
    selected = sys.platform if platform is None else platform
    return selected.startswith("linux")


def _metronome_voice_count(platform: str | None = None) -> int:
    """QSoundEffect voice count for platforms that use that backend.

    Linux deliberately returns zero: Qt's QSoundEffect path can underrun the
    simultaneous QMediaPlayer stream even with only two voices on PulseAudio.
    Linux therefore uses one persistent QAudioSink and mixes click overlap in
    software instead of creating independent sound-effect streams.
    """

    return 0 if _uses_linux_metronome_sink(platform) else _METRONOME_VOICES


def _pcm_sample_to_int16(payload: bytes, offset: int, width: int) -> int:
    if width == 1:
        return (payload[offset] - 128) << 8
    if width == 2:
        return int.from_bytes(payload[offset : offset + 2], "little", signed=True)
    if width == 3:
        value = int.from_bytes(payload[offset : offset + 3], "little", signed=False)
        if value & 0x800000:
            value -= 0x1000000
        return value >> 8
    if width == 4:
        value = int.from_bytes(payload[offset : offset + 4], "little", signed=True)
        return value >> 16
    raise ValueError(f"unsupported metronome PCM sample width: {width}")


def _load_metronome_pcm(
    path: str | Path,
    *,
    target_rate: int,
    target_channels: int,
) -> tuple[int, ...]:
    """Load a short PCM WAV and convert it to interleaved signed 16-bit PCM."""

    if target_rate <= 0 or target_channels not in (1, 2):
        raise ValueError("invalid metronome output format")
    try:
        with wave.open(str(path), "rb") as source:
            source_channels = source.getnchannels()
            width = source.getsampwidth()
            source_rate = source.getframerate()
            frame_count = source.getnframes()
            compression = source.getcomptype()
            if compression != "NONE":
                raise ValueError(f"compressed metronome WAV is unsupported: {compression}")
            if source_channels <= 0 or source_rate <= 0:
                raise ValueError("metronome WAV has invalid channel or sample-rate metadata")
            payload = source.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as exc:
        raise ValueError(f"cannot read metronome WAV: {exc}") from exc

    frame_width = source_channels * width
    if width not in (1, 2, 3, 4) or frame_width <= 0:
        raise ValueError(f"unsupported metronome PCM sample width: {width}")
    if len(payload) < frame_count * frame_width:
        raise ValueError("metronome WAV payload is truncated")

    frames: list[tuple[int, ...]] = []
    for frame_index in range(frame_count):
        base = frame_index * frame_width
        source_values = tuple(
            _pcm_sample_to_int16(payload, base + channel * width, width)
            for channel in range(source_channels)
        )
        if target_channels == 1:
            frames.append((round(sum(source_values) / len(source_values)),))
        elif source_channels == 1:
            frames.append((source_values[0], source_values[0]))
        else:
            frames.append((source_values[0], source_values[1]))

    if not frames:
        raise ValueError("metronome WAV is empty")

    if source_rate == target_rate:
        converted = frames
    else:
        target_count = max(1, round(len(frames) * target_rate / source_rate))
        converted: list[tuple[int, ...]] = []
        for target_index in range(target_count):
            source_position = target_index * source_rate / target_rate
            first = min(len(frames) - 1, int(source_position))
            second = min(len(frames) - 1, first + 1)
            fraction = source_position - first
            converted.append(
                tuple(
                    round(
                        frames[first][channel] * (1.0 - fraction)
                        + frames[second][channel] * fraction
                    )
                    for channel in range(target_channels)
                )
            )

    return tuple(value for frame in converted for value in frame)


def _mix_metronome_chunk(
    sample: tuple[int, ...],
    positions: tuple[int, ...],
    *,
    channels: int,
    frames: int,
) -> tuple[bytes, tuple[int, ...]]:
    """Mix active click instances into one little-endian Int16 PCM chunk."""

    if channels <= 0 or frames <= 0:
        return b"", positions
    sample_frames = len(sample) // channels
    if sample_frames <= 0 or not positions:
        return b"\x00" * (frames * channels * 2), ()

    mixed = [0] * (frames * channels)
    remaining: list[int] = []
    for position in positions:
        if position >= sample_frames:
            continue
        count = min(frames, sample_frames - position)
        source = position * channels
        limit = count * channels
        for index in range(limit):
            mixed[index] += sample[source + index]
        position += count
        if position < sample_frames:
            remaining.append(position)

    clipped = (
        max(-32768, min(32767, value))
        for value in mixed
    )
    return struct.pack(f"<{frames * channels}h", *clipped), tuple(remaining)


def _metronome_frames_to_write(
    *,
    buffer_bytes: int,
    free_bytes: int,
    frame_bytes: int,
    sample_rate: int,
    active: bool,
) -> int:
    """Return enough frames to maintain a short latency-oriented sink queue.

    The QAudioSink may expose a larger physical buffer for underrun tolerance,
    but continuously filling that buffer with silence delays a newly triggered
    click behind all already-queued silence. Keep only a small idle lead and a
    slightly larger lead while a click is active.
    """

    if frame_bytes <= 0 or sample_rate <= 0:
        return 0
    free_bytes = max(0, int(free_bytes))
    buffer_bytes = max(0, int(buffer_bytes))
    if buffer_bytes > 0:
        free_bytes = min(free_bytes, buffer_bytes)
        queued_bytes = max(0, buffer_bytes - free_bytes)
    else:
        queued_bytes = 0

    target_ms = (
        _LINUX_MIXER_ACTIVE_QUEUE_MS if active else _LINUX_MIXER_IDLE_QUEUE_MS
    )
    target_frames = max(1, round(sample_rate * target_ms / 1000.0))
    target_bytes = target_frames * frame_bytes
    missing_bytes = max(0, target_bytes - queued_bytes)
    writable_bytes = min(free_bytes, missing_bytes)
    return writable_bytes // frame_bytes


class _LinuxMetronomeSink(QObject):
    """One persistent Qt audio stream with software-mixed metronome clicks."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._sink: QAudioSink | None = None
        self._writer = None
        self._sample: tuple[int, ...] = ()
        self._voices: tuple[int, ...] = ()
        self._channels = 2
        self._rate = 48_000
        self._loaded_path: Path | None = None
        self.last_error = ""
        self._pump_timer = QTimer(self)
        self._pump_timer.setInterval(_LINUX_MIXER_PUMP_MS)
        self._pump_timer.timeout.connect(self._pump)

    @property
    def loaded_path(self) -> Path | None:
        return self._loaded_path

    def load(self, path: str | Path | None) -> bool:
        self.stop()
        self.last_error = ""
        if path is None:
            return True

        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            self.last_error = "no default audio output is available for the metronome"
            return False

        selected_format = None
        for rate, channels in ((48_000, 2), (44_100, 2), (48_000, 1), (44_100, 1)):
            candidate = QAudioFormat()
            candidate.setSampleRate(rate)
            candidate.setChannelCount(channels)
            candidate.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if device.isFormatSupported(candidate):
                selected_format = candidate
                break
        if selected_format is None:
            self.last_error = (
                "default audio output does not support a standard Int16 metronome format"
            )
            return False

        source = Path(path).resolve()
        try:
            sample = _load_metronome_pcm(
                source,
                target_rate=selected_format.sampleRate(),
                target_channels=selected_format.channelCount(),
            )
        except ValueError as exc:
            self.last_error = str(exc)
            return False

        sink = QAudioSink(device, selected_format, self)
        frame_bytes = selected_format.channelCount() * 2
        buffer_frames = max(
            1,
            round(selected_format.sampleRate() * _LINUX_MIXER_BUFFER_MS / 1000.0),
        )
        sink.setBufferSize(buffer_frames * frame_bytes)
        writer = sink.start()
        if writer is None:
            self.last_error = "cannot start Linux metronome audio sink"
            sink.deleteLater()
            return False

        self._sink = sink
        self._writer = writer
        self._sample = sample
        self._voices = ()
        self._channels = selected_format.channelCount()
        self._rate = selected_format.sampleRate()
        self._loaded_path = source
        self._pump_timer.start()
        self._pump()
        return True

    def stop(self) -> None:
        self._pump_timer.stop()
        self._voices = ()
        self._sample = ()
        self._loaded_path = None
        self._writer = None
        if self._sink is not None:
            self._sink.stop()
            self._sink.deleteLater()
            self._sink = None

    def trigger(self) -> bool:
        if self._sink is None or self._writer is None or not self._sample:
            return False
        voices = list(self._voices)
        if len(voices) >= _LINUX_MIXER_MAX_VOICES:
            voices.pop(0)
        voices.append(0)
        self._voices = tuple(voices)
        self._pump()
        return True

    def _pump(self) -> None:
        sink = self._sink
        writer = self._writer
        if sink is None or writer is None:
            return
        frame_bytes = self._channels * 2
        free_bytes = max(0, int(sink.bytesFree()))
        frames = _metronome_frames_to_write(
            buffer_bytes=int(sink.bufferSize()),
            free_bytes=free_bytes,
            frame_bytes=frame_bytes,
            sample_rate=self._rate,
            active=bool(self._voices),
        )
        if frames <= 0:
            return
        payload, self._voices = _mix_metronome_chunk(
            self._sample,
            self._voices,
            channels=self._channels,
            frames=frames,
        )
        if payload:
            writer.write(payload)


def _accept_transport_position(
    previous: int,
    candidate: int,
    *,
    playing: bool,
    explicit: bool = False,
) -> bool:
    """Reject backend jitter that would make live transport run backwards.

    QMediaPlayer positionChanged updates can lag the 16 ms monotonic poll used by
    the editor. Without this gate a sequence such as 1008 -> 995 -> 1012 ms can
    make the note metronome observe event N, event N-1, then event N again.
    Explicit seeks are allowed to move in either direction.
    """

    if explicit or previous < 0 or not playing:
        return True
    return candidate >= previous


class AudioTransport(QObject):
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    playbackChanged = Signal(bool)
    errorOccurred = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.output = QAudioOutput(self)
        self.output.setVolume(0.8)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.output)

        self._linux_metronome: _LinuxMetronomeSink | None = None
        if _uses_linux_metronome_sink():
            self._linux_metronome = _LinuxMetronomeSink(self)
            self._metronome_voices = ()
            self.metronome = self._linux_metronome
        else:
            # Non-Linux keeps the established QSoundEffect voice pool. Multiple
            # voices prevent one tick from truncating another in dense charts.
            self._metronome_voices = tuple(
                QSoundEffect(self) for _ in range(_metronome_voice_count())
            )
            for voice in self._metronome_voices:
                voice.setLoopCount(1)
                voice.setVolume(0.9)
            self.metronome = self._metronome_voices[0]

        self._aud_directory: QTemporaryDir | None = None
        self._playback_source: Path | None = None
        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self.cleanup_aud_staging)
        self._aud_serial = 0
        self._position_anchor = 0
        self._last_emitted_position = -1
        self._position_clock = QElapsedTimer()
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(16)
        self._position_timer.timeout.connect(self._poll_position)
        # QMediaPlayer exposes both values as qlonglong. PySide 6.11 refuses
        # to connect those signals directly to our Python ``Signal(int)``;
        # route them through callables so the values are normalized before
        # they are re-emitted.
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state)
        self.player.errorOccurred.connect(
            lambda error, message: self.errorOccurred.emit(message or str(error))
        )

    @property
    def playback_source(self) -> Path | None:
        """Exact local file currently handed to QMediaPlayer.

        For ordinary formats this is the selected source. ENC1/ENC2 AUD/A is
        decoded and staged as MP3 first, so waveform decoding can consume
        precisely the same bytes as playback instead of independently repeating
        that pipeline.
        """

        return self._playback_source

    def load(self, path: str | Path | None) -> bool:
        self.player.stop()
        self.player.setSource(QUrl())
        self._playback_source = None
        self._position_timer.stop()
        self._position_clock.invalidate()
        self._position_anchor = 0
        self._last_emitted_position = -1
        if path is None:
            if self._aud_directory is not None:
                self.cleanup_aud_staging()
            return True
        source = Path(path)
        if source.suffix.casefold() in {".aud", ".a"}:
            try:
                payload = decode_enc2_aud(source)
            except AudDecodeError as exc:
                self.errorOccurred.emit(str(exc))
                return False
            directory = self._ensure_aud_directory()
            if directory is None:
                return False
            self._aud_serial += 1
            source = Path(directory.path()) / f"decoded-{self._aud_serial}.mp3"
            try:
                source.write_bytes(payload)
            except OSError as exc:
                self.errorOccurred.emit(f"cannot stage decoded AUD audio: {exc}")
                return False
        source = source.resolve()
        self._playback_source = source
        self.player.setSource(QUrl.fromLocalFile(str(source)))
        return True

    def toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek(self, milliseconds: int) -> None:
        position = max(0, milliseconds)
        # Publish an explicit seek immediately, including backwards seeks, then
        # let subsequent backend callbacks pass through the monotonic live gate.
        self._position_anchor = position
        self._position_clock.restart()
        self._emit_position(position, explicit=True)
        self.player.setPosition(position)

    def _ensure_aud_directory(self) -> QTemporaryDir | None:
        if self._aud_directory is not None and self._aud_directory.isValid():
            return self._aud_directory
        directory = QTemporaryDir("stepnx-audio-XXXXXX")
        if not directory.isValid():
            self.errorOccurred.emit(
                "cannot create temporary directory for decoded AUD audio"
            )
            return None
        directory.setAutoRemove(True)
        self._aud_directory = directory
        return directory

    def cleanup_aud_staging(self) -> bool:
        directory = self._aud_directory
        if directory is None:
            return True
        self.player.stop()
        self.player.setSource(QUrl())
        self._playback_source = None
        self._position_timer.stop()
        self._position_clock.invalidate()
        self._aud_directory = None
        return bool(directory.remove())

    def load_metronome(self, path: str | Path | None) -> None:
        if self._linux_metronome is not None:
            if not self._linux_metronome.load(path):
                self.errorOccurred.emit(
                    self._linux_metronome.last_error or "cannot load Linux metronome"
                )
            return

        source = (
            QUrl()
            if path is None
            else QUrl.fromLocalFile(str(Path(path).resolve()))
        )
        for voice in self._metronome_voices:
            voice.stop()
            voice.setSource(source)

    def play_metronome(self) -> bool:
        if self._linux_metronome is not None:
            return self._linux_metronome.trigger()

        loaded = False
        for voice in self._metronome_voices:
            if voice.source().isEmpty() or not voice.isLoaded():
                continue
            loaded = True
            if not voice.isPlaying():
                voice.play()
                return True
        # Do not cut/restart an existing voice just to force another tick. If
        # every loaded voice is busy, silently drop a pathological ultra-dense
        # event instead of introducing a discontinuity. Returning True means
        # the sample is ready, so callers do not misreport saturation as an
        # unloaded BEAT.WAV.
        return loaded

    def _position_changed(self, milliseconds: int) -> None:
        candidate = int(milliseconds)
        playing = (
            self.player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        )
        if not _accept_transport_position(
            self._last_emitted_position,
            candidate,
            playing=playing,
        ):
            # Keep both the visible position and the extrapolation anchor
            # monotonic. Re-anchoring to an old backend timestamp would replace
            # the duplicate tick with a short 10-20 ms transport stall.
            return
        self._position_anchor = candidate
        self._position_clock.restart()
        self._emit_position(candidate)

    def _emit_position(self, milliseconds: int, *, explicit: bool = False) -> None:
        milliseconds = int(milliseconds)
        playing = (
            self.player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        )
        if not _accept_transport_position(
            self._last_emitted_position,
            milliseconds,
            playing=playing,
            explicit=explicit,
        ):
            return
        if milliseconds != self._last_emitted_position:
            self._last_emitted_position = milliseconds
            self.positionChanged.emit(milliseconds)

    def _poll_position(self) -> None:
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        estimate = self._position_anchor
        if self._position_clock.isValid():
            estimate += self._position_clock.elapsed()
        duration = self.player.duration()
        if duration > 0:
            estimate = min(estimate, duration)
        self._emit_position(estimate)

    def _duration_changed(self, milliseconds: int) -> None:
        self.durationChanged.emit(int(milliseconds))

    def _playback_state(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        if playing:
            self._position_anchor = int(self.player.position())
            self._position_clock.restart()
            self._position_timer.start()
        else:
            self._position_timer.stop()
            self._position_changed(int(self.player.position()))
        self.playbackChanged.emit(playing)
