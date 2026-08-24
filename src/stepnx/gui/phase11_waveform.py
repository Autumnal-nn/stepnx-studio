from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QPen
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat
from PySide6.QtWidgets import QFileDialog, QMessageBox

import stepnx.workspace as workspace_package
import stepnx.workspace.folder as folder_module
from stepnx.authoring.audio import WaveformEnvelope


_TARGET_PEAKS_PER_SECOND = 200
_MAX_WAVEFORM_POINTS = 120_000
_MAX_SAMPLES_PER_BUCKET = 32
_WAVEFORM_GAIN = 1.9


def _reduce_peaks(
    peaks: list[float], maximum: int = _MAX_WAVEFORM_POINTS
) -> tuple[float, ...]:
    if not peaks:
        return ()
    if len(peaks) <= maximum:
        return tuple(peaks)
    width = len(peaks) / maximum
    reduced: list[float] = []
    for bucket in range(maximum):
        start = int(bucket * width)
        end = max(start + 1, int((bucket + 1) * width))
        values = peaks[start : min(len(peaks), end)]
        reduced.append(sum(values) / len(values))
    return tuple(reduced)


def _decoded_samples(buffer):
    audio_format = buffer.format()
    rate = int(audio_format.sampleRate())
    channels = int(audio_format.channelCount())
    sample_format = audio_format.sampleFormat()
    if rate <= 0 or channels <= 0:
        raise ValueError("decoded audio buffer has invalid sample rate/channel count")

    raw = bytes(buffer.constData())
    if sample_format == QAudioFormat.SampleFormat.UInt8:
        samples = memoryview(raw).cast("B")
        zero = 128.0
        scale = 1.0 / 128.0
    elif sample_format == QAudioFormat.SampleFormat.Int16:
        samples = memoryview(raw).cast("h")
        zero = 0.0
        scale = 1.0 / 32768.0
    elif sample_format == QAudioFormat.SampleFormat.Int32:
        samples = memoryview(raw).cast("i")
        zero = 0.0
        scale = 1.0 / 2147483648.0
    elif sample_format == QAudioFormat.SampleFormat.Float:
        samples = memoryview(raw).cast("f")
        zero = 0.0
        scale = 1.0
    else:
        raise ValueError(f"unsupported decoded sample format: {sample_format}")
    return samples, rate, channels, zero, scale


def _buffer_channel_levels(buffer) -> tuple[list[float], ...]:
    """Project native decoded PCM to compact per-channel mean-absolute levels.

    SMEditor-style waveform rendering is better served by average energy than by
    the single largest transient in every interval. The decoder stays at the
    source's native format and samples at most a small fixed number of frames
    per visual bucket, so long 48 kHz songs do not block the GUI thread.
    """

    samples, rate, channels, zero, scale = _decoded_samples(buffer)
    frame_count = len(samples) // channels
    if frame_count <= 0:
        return ()

    visible_channels = min(channels, 2)
    frames_per_bucket = max(1, round(rate / _TARGET_PEAKS_PER_SECOND))
    result = [[] for _ in range(visible_channels)]

    for first in range(0, frame_count, frames_per_bucket):
        last = min(frame_count, first + frames_per_bucket)
        stride = max(1, math.ceil((last - first) / _MAX_SAMPLES_PER_BUCKET))
        for channel in range(visible_channels):
            total = 0.0
            count = 0
            for frame in range(first, last, stride):
                value = float(samples[frame * channels + channel])
                total += abs(value - zero) * scale
                count += 1
            result[channel].append(
                min(1.0, total / count) if count else 0.0
            )
    return tuple(result)


def _buffer_peaks(buffer) -> list[float]:
    """Backward-compatible aggregate used by older tests/helpers."""

    channels = _buffer_channel_levels(buffer)
    if not channels:
        return []
    count = min(len(channel) for channel in channels)
    return [
        sum(channel[index] for channel in channels) / len(channels)
        for index in range(count)
    ]


@dataclass(frozen=True, slots=True)
class WaveformRenderData:
    """Aggregate timing envelope plus channel-separated visual data."""

    envelope: WaveformEnvelope
    channels: tuple[tuple[float, ...], ...]

    @property
    def duration_ms(self) -> float:
        return self.envelope.duration_ms

    @property
    def peaks(self) -> tuple[float, ...]:
        return self.envelope.peaks

    def amplitude_at(self, time_ms: float) -> float:
        return self.envelope.amplitude_at(time_ms)

    def channel_amplitude_at(self, channel: int, time_ms: float) -> float:
        if (
            not 0 <= channel < len(self.channels)
            or not self.channels[channel]
            or self.duration_ms <= 0
            or time_ms < 0
        ):
            return 0.0
        series = self.channels[channel]
        fraction = min(1.0, time_ms / self.duration_ms)
        index = min(len(series) - 1, int(fraction * len(series)))
        return series[index]


class QtWaveformDecoder(QObject):
    """Asynchronously derive waveform data from Qt-supported audio.

    The decoder intentionally consumes the exact local file handed to
    QMediaPlayer. For ENC2 AUD/A this is AudioTransport's staged decoded MP3, so
    playback and waveform cannot diverge through two independent decrypt paths.
    Native decoder output is retained instead of requesting a forced resample;
    this avoids backend-specific conversion failures and preserves stereo.
    """

    waveformReady = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.decoder = QAudioDecoder(self)
        self.decoder.bufferReady.connect(self._buffer_ready)
        self.decoder.finished.connect(self._finished)
        self.decoder.isDecodingChanged.connect(self._decoding_changed)
        self._channels: list[list[float]] = []
        self._duration_us = 0
        self._active = False
        self._finished_successfully = False
        self._source: Path | None = None

    def start(self, path: str | Path) -> None:
        source = Path(path).resolve()
        self.decoder.stop()
        self._channels.clear()
        self._duration_us = 0
        self._active = False
        self._finished_successfully = False
        self._source = source

        if not source.is_file():
            self.failed.emit(f"waveform source does not exist: {source}")
            return
        if not self.decoder.isSupported():
            self.failed.emit(
                "Qt Multimedia audio decoding is not supported on this system"
            )
            return

        # Do not force mono/resampling here. Some FFmpeg-backed Qt builds accept
        # playback for a file but fail an explicit output conversion. Native PCM
        # is also required to retain the two channels used by the visual field.
        self.decoder.setAudioFormat(QAudioFormat())
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
            channels = _buffer_channel_levels(buffer)
        except (TypeError, ValueError) as exc:
            self._active = False
            self.decoder.stop()
            self.failed.emit(f"cannot analyze decoded audio buffer: {exc}")
            return
        if not channels:
            return

        if not self._channels:
            self._channels = [[] for _ in channels]
        if len(channels) != len(self._channels):
            self._active = False
            self.decoder.stop()
            self.failed.emit("decoded audio changed channel layout during waveform analysis")
            return
        for target, values in zip(self._channels, channels):
            target.extend(values)

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
        channel_series = tuple(_reduce_peaks(channel) for channel in self._channels)
        if (
            not channel_series
            or not all(channel_series)
            or not math.isfinite(duration_ms)
            or duration_ms <= 0.0
        ):
            self.failed.emit("decoded audio did not produce a usable waveform")
            return

        point_count = min(len(channel) for channel in channel_series)
        aggregate = tuple(
            sum(channel[index] for channel in channel_series) / len(channel_series)
            for index in range(point_count)
        )
        try:
            waveform = WaveformRenderData(
                WaveformEnvelope(duration_ms, aggregate),
                tuple(channel[:point_count] for channel in channel_series),
            )
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


def _publish_waveform(window, waveform) -> None:
    window.waveform = waveform
    for index in range(window.tabs.count()):
        widget = window.tabs.widget(index)
        if hasattr(widget, "set_waveform"):
            widget.set_waveform(window.waveform, window.audio_alignment)
    channel_count = len(getattr(waveform, "channels", ())) or 1
    window.statusBar().showMessage(
        f"Waveform ready: {len(waveform.peaks)} buckets · {channel_count} ch",
        5000,
    )


def _case_insensitive_file(directory: Path, name: str) -> Path | None:
    """Return a regular file matching *name* with Windows-like case handling."""

    exact = directory / name
    if exact.is_file() and not exact.is_symlink():
        return exact.resolve()
    wanted = name.casefold()
    try:
        candidates = sorted(
            (
                item
                for item in directory.iterdir()
                if item.is_file()
                and not item.is_symlink()
                and item.name.casefold() == wanted
            ),
            key=lambda item: (item.name.casefold(), item.name),
        )
    except OSError:
        return None
    return candidates[0].resolve() if candidates else None


def _preferred_song_path(root: str | Path) -> Path | None:
    """Resolve the three canonical automatic MP3 conventions.

    Priority is deterministic: sibling ``<folderName>.mp3`` for NXA-era
    folders, sibling ``A.mp3`` for Fiesta and later, then in-folder KSF-era
    ``Song.mp3``. Matching is case-insensitive to reproduce the Windows
    authoring environments used by those formats.
    """

    folder = Path(root).resolve()
    candidates = (
        (folder.parent, f"{folder.name}.mp3"),
        (folder.parent, "A.mp3"),
        (folder, "Song.mp3"),
    )
    for directory, name in candidates:
        match = _case_insensitive_file(directory, name)
        if match is not None:
            return match
    return None


def _draw_waveform_field(widget, painter, visible, waveform) -> None:
    """Render a compact SMEditor-style waveform behind the active note lanes."""

    segment = visible.segment
    block = segment.block
    if (
        segment.row_height <= 0.0
        or block.bpm <= 0.0
        or block.beat_split <= 0
        or waveform.duration_ms <= 0.0
    ):
        return

    first_y = max(segment.rows_top, segment.y_for_row(visible.first_row))
    last_y = min(segment.bottom, segment.y_for_row(visible.last_row))
    if last_y <= first_y:
        return

    geometry = widget._geometry
    field_width = widget._layout.lane_area_width
    if field_width <= 0.0:
        return
    field_left = geometry.ruler_width
    row_duration = 60_000.0 / (block.bpm * block.beat_split)
    channel_series = getattr(waveform, "channels", ())

    if len(channel_series) >= 2:
        channel_count = 2
        slot_width = field_width / channel_count
        centres = tuple(
            field_left + slot_width * (index + 0.5)
            for index in range(channel_count)
        )
        maximum_half = max(4.0, slot_width * 0.28)
    else:
        channel_count = 1
        centres = (field_left + field_width / 2.0,)
        maximum_half = max(4.0, field_width * 0.18)

    painter.save()
    try:
        painter.setClipRect(
            QRectF(field_left, first_y, field_width, last_y - first_y)
        )
        painter.setPen(QPen(QColor(116, 124, 146, 108), 1.0))
        start = math.floor(first_y)
        stop = math.ceil(last_y)
        for y in range(start, stop):
            row = (y + 0.5 - segment.rows_top) / segment.row_height
            chart_time = block.start_time + row * row_duration
            audio_time = widget._audio_alignment.chart_to_audio(chart_time)
            for channel in range(channel_count):
                if channel_count == 1:
                    amplitude = waveform.amplitude_at(audio_time)
                else:
                    amplitude = waveform.channel_amplitude_at(channel, audio_time)
                if amplitude <= 0.0:
                    continue
                half = min(1.0, amplitude * _WAVEFORM_GAIN) * maximum_half
                painter.drawLine(
                    QPointF(centres[channel] - half, y + 0.5),
                    QPointF(centres[channel] + half, y + 0.5),
                )
    finally:
        painter.restore()


def _install_timeline_waveform_renderer() -> None:
    """Replace the old ruler-only waveform with a full notefield projection."""

    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_phase11_waveform_renderer_installed", False):
        return
    original_draw_segment = timeline_class._draw_segment

    def draw_segment_with_waveform(self, painter, visible) -> None:
        waveform = getattr(self, "_waveform", None)
        host = self.window()
        action = getattr(host, "phase11_waveform_action", None)
        enabled = action is None or action.isChecked()
        if waveform is not None and enabled:
            _draw_waveform_field(self, painter, visible, waveform)

        if waveform is None:
            original_draw_segment(self, painter, visible)
            return
        self._waveform = None
        try:
            original_draw_segment(self, painter, visible)
        finally:
            self._waveform = waveform

    timeline_class._phase11_waveform_renderer_installed = True
    timeline_class._phase11_original_draw_segment = original_draw_segment
    timeline_class._draw_segment = draw_segment_with_waveform


def _install_waveform_view_action(window) -> None:
    view_menu = None
    for menu_action in window.menuBar().actions():
        if menu_action.text().replace("&", "").casefold() == "view":
            view_menu = menu_action.menu()
            break
    if view_menu is None:
        view_menu = window.menuBar().addMenu("&View")

    action = QAction("Show waveform", window)
    action.setCheckable(True)
    action.setChecked(True)

    def refresh(_checked: bool) -> None:
        for index in range(window.tabs.count()):
            widget = window.tabs.widget(index)
            viewport = getattr(widget, "viewport", None)
            if callable(viewport):
                viewport().update()

    action.toggled.connect(refresh)
    view_menu.addAction(action)
    window.phase11_waveform_action = action


def _choose_audio_dialog(window) -> None:
    initial = str(window.workspace.root) if window.workspace is not None else ""
    selected, _ = QFileDialog.getOpenFileName(
        window,
        "Select chart audio",
        initial,
        "Audio (*.mp3 *.aud *.a *.wav *.flac *.ogg *.mp2);;All files (*)",
    )
    if selected:
        window._load_audio(Path(selected))


def _replace_audio_picker(window) -> None:
    action = next(
        (
            item
            for item in window.findChildren(QAction)
            if item.text() == "Select audio…"
        ),
        None,
    )
    if action is None:
        return
    try:
        action.triggered.disconnect()
    except (RuntimeError, TypeError):
        pass
    action.triggered.connect(lambda *_args: _choose_audio_dialog(window))


def _clear_audio(window) -> None:
    decoder = getattr(window, "phase11_waveform_decoder", None)
    if decoder is not None:
        decoder.stop()
    window.audio_transport.load(None)
    if window.workspace is not None:
        window.workspace = window.workspace.select_audio(None)
    window.waveform = None
    for index in range(window.tabs.count()):
        widget = window.tabs.widget(index)
        if hasattr(widget, "set_waveform"):
            widget.set_waveform(None, window.audio_alignment)


def _install_song_autoload(window) -> None:
    original_load_folder = window.load_folder

    def load_folder_with_song(path: Path, *, discard_changes: bool = False) -> None:
        previous_root = None if window.workspace is None else window.workspace.root
        previous_audio = (
            None if window.workspace is None else window.workspace.selected_audio
        )
        requested = Path(path).resolve()
        original_load_folder(path, discard_changes=discard_changes)
        if window.workspace is None or window.workspace.root.resolve() != requested:
            return

        preferred = _preferred_song_path(window.workspace.root)
        if preferred is not None:
            selected = window.workspace.selected_audio
            if selected is None or selected.resolve() != preferred.resolve():
                window._load_audio(preferred)
            return

        if window.workspace.selected_audio is not None:
            _clear_audio(window)

        # Save All reloads the same workspace. Preserve a manually selected
        # song for that internal refresh, but never carry it into another folder.
        if (
            previous_root is not None
            and previous_root.resolve() == window.workspace.root.resolve()
            and previous_audio is not None
            and previous_audio.is_file()
        ):
            window._load_audio(previous_audio)
            return
        if discard_changes:
            return

        answer = QMessageBox.question(
            window,
            "Song audio not found",
            "Do you want to load a song?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            _choose_audio_dialog(window)

    window.load_folder = load_folder_with_song


def install_phase11_waveform(window) -> None:
    if getattr(window, "_phase11_waveform_installed", False):
        return
    window._phase11_waveform_installed = True

    extended_suffixes = frozenset((*folder_module.AUDIO_SUFFIXES, ".A"))
    folder_module.AUDIO_SUFFIXES = extended_suffixes
    workspace_package.AUDIO_SUFFIXES = extended_suffixes

    _install_timeline_waveform_renderer()
    _install_waveform_view_action(window)

    decoder = QtWaveformDecoder(window)
    window.phase11_waveform_decoder = decoder
    decoder.waveformReady.connect(
        lambda waveform: _publish_waveform(window, waveform)
    )
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

        if source.suffix.casefold() == ".wav" and window.waveform is not None:
            decoder.stop()
            return

        decoder.start(source)
        window.statusBar().showMessage(
            f"Loaded audio: {Path(path).name} · decoding waveform…", 5000
        )

    window._load_audio = load_audio_with_waveform
    _install_song_autoload(window)
    _replace_audio_picker(window)
