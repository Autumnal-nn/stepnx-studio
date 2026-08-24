from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QPen
from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat
from PySide6.QtWidgets import QFileDialog, QMessageBox

import stepnx.workspace as workspace_package
import stepnx.workspace.folder as folder_module
from stepnx.authoring.audio import WaveformEnvelope


_TARGET_PEAKS_PER_SECOND = 100
_MAX_WAVEFORM_POINTS = 120_000


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
        reduced.append(max(peaks[start : min(len(peaks), end)]))
    return tuple(reduced)


def _chunk_peak(samples, sample_format) -> float:
    if not samples:
        return 0.0
    low = min(samples)
    high = max(samples)
    if sample_format == QAudioFormat.SampleFormat.UInt8:
        return min(
            1.0,
            max(abs(float(low) - 128.0), abs(float(high) - 128.0)) / 128.0,
        )
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

    samples_per_bucket = max(
        1, round(rate * channels / _TARGET_PEAKS_PER_SECOND)
    )
    result: list[float] = []
    for start in range(0, len(samples), samples_per_bucket):
        result.append(
            _chunk_peak(samples[start : start + samples_per_bucket], sample_format)
        )
    return result


class QtWaveformDecoder(QObject):
    """Asynchronously derive a WaveformEnvelope from Qt-supported audio.

    The decoder intentionally consumes the exact local file handed to
    QMediaPlayer. For ENC2 AUD/A this is AudioTransport's staged decoded MP3, so
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
            self.failed.emit(
                "Qt Multimedia audio decoding is not supported on this system"
            )
            return

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
    """Resolve the three canonical MP3 conventions inside a chart folder.

    Priority is deterministic: ``<folderName>.mp3`` for NXA-era folders,
    ``A.mp3`` for Fiesta and later, then KSF-era ``Song.mp3``. Matching is
    case-insensitive to reproduce the Windows authoring environments used by
    those formats.
    """

    folder = Path(root).resolve()
    candidates = (
        f"{folder.name}.mp3",
        "A.mp3",
        "Song.mp3",
    )
    for name in candidates:
        match = _case_insensitive_file(folder, name)
        if match is not None:
            return match
    return None


def _draw_waveform_field(widget, painter, visible, waveform: WaveformEnvelope) -> None:
    """Render an SMEditor-style amplitude field behind the active note lanes."""

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
    lane_width = widget._layout.lane_area_width
    if lane_width <= 0.0:
        return
    lane_left = geometry.ruler_width
    centre = lane_left + lane_width / 2.0
    maximum_half = max(1.0, lane_width / 2.0 - 4.0)
    row_duration = 60_000.0 / (block.bpm * block.beat_split)

    painter.save()
    try:
        painter.setClipRect(
            QRectF(lane_left, first_y, lane_width, last_y - first_y)
        )
        painter.setPen(QPen(QColor(96, 150, 190, 82), 1.0))
        start = math.floor(first_y)
        stop = math.ceil(last_y)
        for y in range(start, stop):
            row = (y + 0.5 - segment.rows_top) / segment.row_height
            chart_time = block.start_time + row * row_duration
            audio_time = widget._audio_alignment.chart_to_audio(chart_time)
            amplitude = waveform.amplitude_at(audio_time)
            if amplitude <= 0.0:
                continue
            half = amplitude * maximum_half
            painter.drawLine(
                QPointF(centre - half, y + 0.5),
                QPointF(centre + half, y + 0.5),
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

        # The base Phase 8 loader historically auto-loaded a sibling
        # <folderName>.mp3. Phase 11 owns song discovery now, so discard that
        # legacy selection when none of the three in-folder conventions match.
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
