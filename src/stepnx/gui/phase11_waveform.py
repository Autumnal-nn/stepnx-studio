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


_SUMMARY_FRAMES = 64
_BPM_ENVELOPE_POINTS_PER_SECOND = 200
_MAX_BPM_ENVELOPE_POINTS = 120_000
_WAVEFORM_GAIN = 0.85


def _reduce_peaks(
    peaks: list[float], maximum: int = _MAX_BPM_ENVELOPE_POINTS
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
        reduced.append(max(values))
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


def _normalized_extrema(samples, first: int, last: int, channels: int, channel: int, zero: float, scale: float) -> tuple[float, float]:
    values = samples[
        first * channels + channel : last * channels + channel : channels
    ]
    if not values:
        return 0.0, 0.0
    low = (float(min(values)) - zero) * scale
    high = (float(max(values)) - zero) * scale
    return max(-1.0, min(1.0, low)), max(-1.0, min(1.0, high))


@dataclass(frozen=True, slots=True)
class WaveformChannelSummary:
    """High-resolution signed min/max summaries for one decoded channel."""

    minima: tuple[float, ...]
    maxima: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.minima) != len(self.maxima):
            raise ValueError("waveform min/max series must have the same length")
        if any(not -1.0 <= value <= 1.0 for value in self.minima):
            raise ValueError("waveform minima must be normalized")
        if any(not -1.0 <= value <= 1.0 for value in self.maxima):
            raise ValueError("waveform maxima must be normalized")
        if any(low > high for low, high in zip(self.minima, self.maxima)):
            raise ValueError("waveform minimum cannot exceed maximum")

    def range_at(
        self, duration_ms: float, start_ms: float, end_ms: float
    ) -> tuple[float, float]:
        """Return signed extrema over the summaries touched by a time interval."""

        count = len(self.minima)
        if count == 0 or duration_ms <= 0.0:
            return 0.0, 0.0
        low_time = min(start_ms, end_ms)
        high_time = max(start_ms, end_ms)
        if high_time < 0.0 or low_time > duration_ms:
            return 0.0, 0.0
        low_time = max(0.0, low_time)
        high_time = min(duration_ms, high_time)
        if high_time <= low_time:
            high_time = min(duration_ms, low_time + duration_ms / count)

        first = min(count - 1, max(0, math.floor(low_time / duration_ms * count)))
        last = min(count, max(first + 1, math.ceil(high_time / duration_ms * count)))
        return min(self.minima[first:last]), max(self.maxima[first:last])


class _WaveformSummaryBuilder:
    """Accumulate fixed-size min/max blocks across QAudioBuffer boundaries."""

    def __init__(self, frames_per_summary: int = _SUMMARY_FRAMES) -> None:
        self.frames_per_summary = frames_per_summary
        self.sample_rate = 0
        self.source_channels = 0
        self.visible_channels = 0
        self.minima: list[list[float]] = []
        self.maxima: list[list[float]] = []
        self.pending_minima: list[float] = []
        self.pending_maxima: list[float] = []
        self.pending_frames = 0

    def clear(self) -> None:
        self.sample_rate = 0
        self.source_channels = 0
        self.visible_channels = 0
        self.minima.clear()
        self.maxima.clear()
        self.pending_minima.clear()
        self.pending_maxima.clear()
        self.pending_frames = 0

    def _ensure_layout(self, sample_rate: int, channels: int) -> None:
        visible = min(2, channels)
        if self.sample_rate == 0:
            self.sample_rate = sample_rate
            self.source_channels = channels
            self.visible_channels = visible
            self.minima = [[] for _ in range(visible)]
            self.maxima = [[] for _ in range(visible)]
            self.pending_minima = [1.0] * visible
            self.pending_maxima = [-1.0] * visible
            return
        if sample_rate != self.sample_rate or channels != self.source_channels:
            raise ValueError("decoded audio changed format during waveform analysis")

    def _merge_pending(self, channel: int, low: float, high: float) -> None:
        self.pending_minima[channel] = min(self.pending_minima[channel], low)
        self.pending_maxima[channel] = max(self.pending_maxima[channel], high)

    def _flush_pending(self) -> None:
        if self.pending_frames <= 0:
            return
        for channel in range(self.visible_channels):
            self.minima[channel].append(self.pending_minima[channel])
            self.maxima[channel].append(self.pending_maxima[channel])
            self.pending_minima[channel] = 1.0
            self.pending_maxima[channel] = -1.0
        self.pending_frames = 0

    def append(self, buffer) -> None:
        samples, rate, channels, zero, scale = _decoded_samples(buffer)
        frame_count = len(samples) // channels
        if frame_count <= 0:
            return
        self._ensure_layout(rate, channels)

        first = 0
        if self.pending_frames:
            take = min(self.frames_per_summary - self.pending_frames, frame_count)
            last = first + take
            for channel in range(self.visible_channels):
                low, high = _normalized_extrema(
                    samples, first, last, channels, channel, zero, scale
                )
                self._merge_pending(channel, low, high)
            self.pending_frames += take
            first = last
            if self.pending_frames == self.frames_per_summary:
                self._flush_pending()

        while first + self.frames_per_summary <= frame_count:
            last = first + self.frames_per_summary
            for channel in range(self.visible_channels):
                low, high = _normalized_extrema(
                    samples, first, last, channels, channel, zero, scale
                )
                self.minima[channel].append(low)
                self.maxima[channel].append(high)
            first = last

        if first < frame_count:
            for channel in range(self.visible_channels):
                low, high = _normalized_extrema(
                    samples, first, frame_count, channels, channel, zero, scale
                )
                self._merge_pending(channel, low, high)
            self.pending_frames = frame_count - first

    def finish(self) -> tuple[WaveformChannelSummary, ...]:
        self._flush_pending()
        return tuple(
            WaveformChannelSummary(tuple(minima), tuple(maxima))
            for minima, maxima in zip(self.minima, self.maxima)
        )


def _buffer_peaks(buffer) -> list[float]:
    """Compatibility helper: signed summaries collapsed to absolute peaks."""

    builder = _WaveformSummaryBuilder()
    builder.append(buffer)
    channels = builder.finish()
    if not channels:
        return []
    count = min(len(channel.minima) for channel in channels)
    return [
        sum(
            max(abs(channel.minima[index]), abs(channel.maxima[index]))
            for channel in channels
        )
        / len(channels)
        for index in range(count)
    ]


@dataclass(frozen=True, slots=True)
class WaveformRenderData:
    """BPM envelope plus high-resolution signed per-channel summaries."""

    envelope: WaveformEnvelope
    channels: tuple[WaveformChannelSummary, ...]

    @property
    def duration_ms(self) -> float:
        return self.envelope.duration_ms

    @property
    def peaks(self) -> tuple[float, ...]:
        return self.envelope.peaks

    @property
    def visual_point_count(self) -> int:
        return max((len(channel.minima) for channel in self.channels), default=0)

    def amplitude_at(self, time_ms: float) -> float:
        return self.envelope.amplitude_at(time_ms)

    def channel_range_at(
        self, channel: int, start_ms: float, end_ms: float
    ) -> tuple[float, float]:
        if not 0 <= channel < len(self.channels):
            return 0.0, 0.0
        return self.channels[channel].range_at(
            self.duration_ms, start_ms, end_ms
        )

    def channel_amplitude_at(self, channel: int, time_ms: float) -> float:
        if not 0 <= channel < len(self.channels):
            return 0.0
        count = len(self.channels[channel].minima)
        if count == 0 or self.duration_ms <= 0.0:
            return 0.0
        interval = self.duration_ms / count
        low, high = self.channel_range_at(channel, time_ms, time_ms + interval)
        return max(abs(low), abs(high))


class QtWaveformDecoder(QObject):
    """Asynchronously derive waveform data from Qt-supported audio.

    The decoder consumes the exact local file handed to QMediaPlayer. ENC2
    AUD/A therefore reuses AudioTransport's staged decoded MP3. Native PCM is
    summarized in fixed 64-frame signed min/max blocks, retaining enough detail
    for sub-millisecond-ish viewport projection without storing the full audio.
    """

    waveformReady = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.decoder = QAudioDecoder(self)
        self.decoder.bufferReady.connect(self._buffer_ready)
        self.decoder.finished.connect(self._finished)
        self.decoder.isDecodingChanged.connect(self._decoding_changed)
        self._summaries = _WaveformSummaryBuilder()
        self._duration_us = 0
        self._active = False
        self._finished_successfully = False
        self._source: Path | None = None

    def start(self, path: str | Path) -> None:
        source = Path(path).resolve()
        self.decoder.stop()
        self._summaries.clear()
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

        # Leave decoding in the backend's native PCM format. This is both more
        # compatible with FFmpeg-backed Qt and lets the visual summaries retain
        # the original stereo channels.
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
            self._summaries.append(buffer)
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
        channel_summaries = self._summaries.finish()
        if (
            not channel_summaries
            or not all(channel.minima for channel in channel_summaries)
            or not math.isfinite(duration_ms)
            or duration_ms <= 0.0
        ):
            self.failed.emit("decoded audio did not produce a usable waveform")
            return

        point_count = min(len(channel.minima) for channel in channel_summaries)
        visual_peaks = [
            sum(
                max(abs(channel.minima[index]), abs(channel.maxima[index]))
                for channel in channel_summaries
            )
            / len(channel_summaries)
            for index in range(point_count)
        ]
        bpm_points = min(
            _MAX_BPM_ENVELOPE_POINTS,
            max(1, math.ceil(duration_ms / 1000.0 * _BPM_ENVELOPE_POINTS_PER_SECOND)),
        )
        aggregate = _reduce_peaks(visual_peaks, bpm_points)
        try:
            waveform = WaveformRenderData(
                WaveformEnvelope(duration_ms, aggregate),
                tuple(
                    WaveformChannelSummary(
                        channel.minima[:point_count], channel.maxima[:point_count]
                    )
                    for channel in channel_summaries
                ),
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
    visual_points = getattr(waveform, "visual_point_count", len(waveform.peaks))
    window.statusBar().showMessage(
        f"Waveform ready: {visual_points} summaries · {channel_count} ch",
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
    """Draw signed min/max summaries for each vertical viewport pixel."""

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
        maximum_half = max(4.0, slot_width * 0.20)
    else:
        channel_count = 1
        centres = (field_left + field_width / 2.0,)
        maximum_half = max(4.0, field_width * 0.16)

    painter.save()
    try:
        painter.setClipRect(
            QRectF(field_left, first_y, field_width, last_y - first_y)
        )
        painter.setPen(QPen(QColor(116, 124, 146, 112), 1.0))
        start = math.floor(first_y)
        stop = math.ceil(last_y)
        for y in range(start, stop):
            row_a = (y - segment.rows_top) / segment.row_height
            row_b = (y + 1.0 - segment.rows_top) / segment.row_height
            chart_time_a = block.start_time + row_a * row_duration
            chart_time_b = block.start_time + row_b * row_duration
            audio_time_a = widget._audio_alignment.chart_to_audio(chart_time_a)
            audio_time_b = widget._audio_alignment.chart_to_audio(chart_time_b)

            for channel in range(channel_count):
                if hasattr(waveform, "channel_range_at"):
                    low, high = waveform.channel_range_at(
                        channel, audio_time_a, audio_time_b
                    )
                    if low == 0.0 and high == 0.0:
                        continue
                    left = centres[channel] + low * _WAVEFORM_GAIN * maximum_half
                    right = centres[channel] + high * _WAVEFORM_GAIN * maximum_half
                else:
                    middle = (audio_time_a + audio_time_b) / 2.0
                    amplitude = waveform.amplitude_at(middle)
                    if amplitude <= 0.0:
                        continue
                    half = min(1.0, amplitude * _WAVEFORM_GAIN) * maximum_half
                    left = centres[channel] - half
                    right = centres[channel] + half
                painter.drawLine(
                    QPointF(left, y + 0.5), QPointF(right, y + 0.5)
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

        # Always run the Phase 11 decoder, including for PCM WAV. The legacy
        # synchronous WAV envelope is useful as an immediate fallback, but its
        # fixed 4096 buckets are too coarse for zoomed waveform authoring.
        decoder.start(source)
        window.statusBar().showMessage(
            f"Loaded audio: {Path(path).name} · decoding waveform…", 5000
        )

    window._load_audio = load_audio_with_waveform
    _install_song_autoload(window)
    _replace_audio_picker(window)
