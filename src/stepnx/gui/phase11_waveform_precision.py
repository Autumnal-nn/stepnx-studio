from __future__ import annotations

import math
from array import array
from time import perf_counter

import stepnx.gui.phase11_waveform as waveform_module
from stepnx.authoring.timeline import TimelineGeometry


BASE_SUMMARY_FRAMES = 16


class _RawChannelSummary:
    __slots__ = ("minima", "maxima")

    def __init__(self, minima, maxima) -> None:
        self.minima = minima
        self.maxima = maxima


class AdaptiveWaveformChannelSummary:
    """Exact min/max range queries backed by a multiresolution pyramid.

    Level zero stores 16-frame summaries as float32 arrays. Each following
    level combines adjacent pairs, so zoomed-out viewport pixels can query large
    time intervals without scanning thousands of fine summaries. Zoomed-in
    pixels retain the full 16-frame base resolution.
    """

    __slots__ = ("minima", "maxima", "_levels")

    def __init__(self, minima, maxima) -> None:
        if len(minima) != len(maxima):
            raise ValueError("waveform min/max series must have the same length")
        self.minima = minima if isinstance(minima, array) and minima.typecode == "f" else array("f", minima)
        self.maxima = maxima if isinstance(maxima, array) and maxima.typecode == "f" else array("f", maxima)

        levels: list[tuple[array, array]] = [(self.minima, self.maxima)]
        current_min = self.minima
        current_max = self.maxima
        while len(current_min) > 1:
            next_min = array("f")
            next_max = array("f")
            for index in range(0, len(current_min), 2):
                if index + 1 < len(current_min):
                    next_min.append(min(current_min[index], current_min[index + 1]))
                    next_max.append(max(current_max[index], current_max[index + 1]))
                else:
                    next_min.append(current_min[index])
                    next_max.append(current_max[index])
            levels.append((next_min, next_max))
            current_min = next_min
            current_max = next_max
        self._levels = tuple(levels)

    def _range_indices(self, first: int, last: int) -> tuple[float, float]:
        if first >= last:
            return 0.0, 0.0
        low = 1.0
        high = -1.0
        position = first
        maximum_level = len(self._levels) - 1
        while position < last:
            remaining = last - position
            size_level = remaining.bit_length() - 1
            if position == 0:
                level = min(size_level, maximum_level)
            else:
                alignment_level = (position & -position).bit_length() - 1
                level = min(size_level, alignment_level, maximum_level)
            block_size = 1 << level
            minima, maxima = self._levels[level]
            block_index = position >> level
            low = min(low, minima[block_index])
            high = max(high, maxima[block_index])
            position += block_size
        return low, high

    def range_at(
        self, duration_ms: float, start_ms: float, end_ms: float
    ) -> tuple[float, float]:
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
        return self._range_indices(first, last)


class AdaptiveWaveformSummaryBuilder(waveform_module._WaveformSummaryBuilder):
    """Store the 16-frame base cache in compact float32 arrays."""

    def __init__(self, frames_per_summary: int = BASE_SUMMARY_FRAMES) -> None:
        super().__init__(frames_per_summary)

    def _ensure_layout(self, sample_rate: int, channels: int) -> None:
        visible = min(2, channels)
        if self.sample_rate == 0:
            self.sample_rate = sample_rate
            self.source_channels = channels
            self.visible_channels = visible
            self.minima = [array("f") for _ in range(visible)]
            self.maxima = [array("f") for _ in range(visible)]
            self.pending_minima = [1.0] * visible
            self.pending_maxima = [-1.0] * visible
            return
        if sample_rate != self.sample_rate or channels != self.source_channels:
            raise ValueError("decoded audio changed format during waveform analysis")

    def finish(self) -> tuple[_RawChannelSummary, ...]:
        self._flush_pending()
        return tuple(
            _RawChannelSummary(minima, maxima)
            for minima, maxima in zip(self.minima, self.maxima)
        )


def _install_timing_line_note_alignment() -> None:
    """Make the encoded row line the visual timing anchor for note artwork."""

    if getattr(TimelineGeometry, "_phase11_timing_line_notes", False):
        return

    def note_rect(
        self: TimelineGeometry,
        lane: int,
        row_y: float,
        row_height: float | None = None,
    ) -> tuple[float, float, float, float]:
        if lane < 0:
            raise ValueError("lane must be non-negative")
        size = max(1.0, self.lane_width - 4.0)
        x = self.ruler_width + lane * self.lane_width + (self.lane_width - size) / 2
        # The line at row_y is the exact chart time. Center note artwork on that
        # line so arrows, beat markers, and waveform all share one timing anchor.
        y = row_y - size / 2.0
        return x, y, size, size

    TimelineGeometry.note_rect = note_rect
    TimelineGeometry._phase11_timing_line_notes = True


def install_phase11_waveform_precision(window) -> None:
    if getattr(window, "_phase11_waveform_precision_installed", False):
        return
    window._phase11_waveform_precision_installed = True

    # Replace the visual summary type used by QtWaveformDecoder._finished().
    waveform_module.WaveformChannelSummary = AdaptiveWaveformChannelSummary
    waveform_module._WaveformSummaryBuilder = AdaptiveWaveformSummaryBuilder

    decoder = getattr(window, "phase11_waveform_decoder", None)
    if decoder is not None:
        # install_phase11_waveform() has already constructed this decoder, so
        # replace its 64-frame builder explicitly for the current window.
        decoder._summaries = AdaptiveWaveformSummaryBuilder()

        original_start = decoder.start

        def timed_start(path) -> None:
            decoder._phase11_precision_started = perf_counter()
            original_start(path)

        decoder.start = timed_start

        def report_cost(waveform) -> None:
            started = getattr(decoder, "_phase11_precision_started", None)
            elapsed_ms = 0.0 if started is None else (perf_counter() - started) * 1000.0
            rate = decoder._summaries.sample_rate
            resolution_ms = (
                0.0 if rate <= 0 else BASE_SUMMARY_FRAMES * 1000.0 / rate
            )
            channels = len(getattr(waveform, "channels", ())) or 1
            points = getattr(waveform, "visual_point_count", len(waveform.peaks))
            window.statusBar().showMessage(
                f"Waveform ready: {points} summaries · {channels} ch · "
                f"{BASE_SUMMARY_FRAMES} frames ({resolution_ms:.3f} ms) · "
                f"{elapsed_ms:.0f} ms build",
                8000,
            )

        decoder.waveformReady.connect(report_cost)

    _install_timing_line_note_alignment()
