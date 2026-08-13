from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass

from stepnx.authoring.snapshot import AuthoringSnapshot, BlockSnapshot


@dataclass(frozen=True, slots=True)
class TimelineGeometry:
    # StepEdit uses a fixed 24 px for both a lane and every encoded row. StepNX
    # renders lanes at 2x that size, so 48 px preserves the same square grid.
    row_height: float = 48.0
    block_header_height: float = 0.0
    lane_width: float = 48.0
    ruler_width: float = 92.0
    block_info_width: float = 300.0
    footer_height: float = 24.0
    minimum_row_height: float = 4.0
    # Dense NX20 divisions need substantially more headroom than a conventional
    # step editor.  At the old 96 px/beat ceiling, split-128 rows were still
    # sub-pixel even at maximum zoom.  Keep the minimum unchanged, but allow a
    # further 64x magnification for precise work and playback inspection.
    maximum_row_height: float = 6144.0

    def __post_init__(self) -> None:
        if not self.minimum_row_height <= self.row_height <= self.maximum_row_height:
            raise ValueError("row height is outside the supported zoom range")
        if self.block_header_height < 0 or min(
            self.lane_width, self.ruler_width, self.block_info_width
        ) <= 0:
            raise ValueError("timeline dimensions must be positive")

    def zoomed(self, factor: float) -> TimelineGeometry:
        if not math.isfinite(factor) or factor <= 0:
            raise ValueError("zoom factor must be finite and positive")
        height = min(self.maximum_row_height, max(self.minimum_row_height, self.row_height * factor))
        return TimelineGeometry(
            row_height=height,
            block_header_height=self.block_header_height,
            lane_width=self.lane_width,
            ruler_width=self.ruler_width,
            block_info_width=self.block_info_width,
            footer_height=self.footer_height,
            minimum_row_height=self.minimum_row_height,
            maximum_row_height=self.maximum_row_height,
        )

    def note_rect(
        self, lane: int, row_y: float, row_height: float | None = None
    ) -> tuple[float, float, float, float]:
        """Return a square note target centred on the row's timing position.

        Vertical zoom changes the distance between timing positions.  It must
        not distort note artwork to the row height, especially in high beat
        splits where rows can be only a few pixels apart.
        """
        if lane < 0:
            raise ValueError("lane must be non-negative")
        size = max(1.0, self.lane_width - 4.0)
        x = self.ruler_width + lane * self.lane_width + (self.lane_width - size) / 2
        effective_height = self.row_height if row_height is None else row_height
        y = row_y + (effective_height - size) / 2
        return x, y, size, size

@dataclass(frozen=True, slots=True)
class TimelineSegment:
    split_id: int
    split_index: int
    block: BlockSnapshot
    top: float
    rows_top: float
    bottom: float
    row_height: float

    def y_for_row(self, row_index: int) -> float:
        if not 0 <= row_index <= self.block.row_count:
            raise IndexError(row_index)
        return self.rows_top + row_index * self.row_height


@dataclass(frozen=True, slots=True)
class VisibleSegment:
    segment: TimelineSegment
    first_row: int
    last_row: int

    @property
    def row_count(self) -> int:
        return self.last_row - self.first_row


@dataclass(frozen=True, slots=True)
class BeatMarker:
    row_index: int
    y: float
    beat: float
    is_measure: bool


class TimelineLayout:
    """Pure geometry and culling for the active read-only branch."""

    __slots__ = (
        "_bottoms",
        "content_height",
        "geometry",
        "segments",
        "snapshot",
    )

    def __init__(
        self,
        snapshot: AuthoringSnapshot,
        geometry: TimelineGeometry | None = None,
        *,
        playback: bool = False,
    ) -> None:
        self.snapshot = snapshot
        self.geometry = geometry or TimelineGeometry()
        segments: list[TimelineSegment] = []
        top = 0.0
        for split in snapshot.splits:
            if not split.blocks:
                continue
            block = snapshot.active_block(split.stable_id)
            # Paused authoring keeps every encoded row editable at a constant
            # height.  During transport, match gameplay's spatial projection:
            # Scroll is expressed per encoded row, while Beat Split supplies
            # the rows per beat.  Their product keeps ordinary combinations
            # such as .25/4 and .125/8 at the chosen zoom and collapses a real
            # zero-Scroll timing block to zero visual height.
            playback_scale = block.scroll * block.beat_split
            if not math.isfinite(playback_scale):
                playback_scale = 1.0
            row_height = self.geometry.row_height * (
                max(0.0, playback_scale) if playback else 1.0
            )
            rows_top = top + self.geometry.block_header_height
            bottom = rows_top + block.row_count * row_height
            segments.append(
                TimelineSegment(
                    split_id=split.stable_id,
                    split_index=split.index,
                    block=block,
                    top=top,
                    rows_top=rows_top,
                    bottom=bottom,
                    row_height=row_height,
                )
            )
            top = bottom
        self.segments = tuple(segments)
        self._bottoms = tuple(segment.bottom for segment in self.segments)
        self.content_height = top + self.geometry.footer_height

    @property
    def lane_area_width(self) -> float:
        return self.snapshot.columns * self.geometry.lane_width

    @property
    def content_width(self) -> float:
        return (
            self.geometry.ruler_width
            + self.lane_area_width
            + self.geometry.block_info_width
        )

    @property
    def chart_width(self) -> float:
        return self.geometry.ruler_width + self.lane_area_width

    def visible_segments(self, viewport_top: float, viewport_height: float, *, overscan_rows: int = 2) -> tuple[VisibleSegment, ...]:
        if not math.isfinite(viewport_top) or not math.isfinite(viewport_height):
            raise ValueError("viewport coordinates must be finite")
        if viewport_height < 0 or overscan_rows < 0:
            raise ValueError("viewport height and overscan must be non-negative")
        if not self.segments or viewport_height == 0:
            return ()
        padding = overscan_rows * self.geometry.row_height
        top = max(0.0, viewport_top - padding)
        bottom = viewport_top + viewport_height + padding
        index = bisect_right(self._bottoms, top)
        visible: list[VisibleSegment] = []
        for segment in self.segments[index:]:
            if segment.top >= bottom:
                break
            if segment.row_height <= 0:
                continue
            first = max(0, math.floor((top - segment.rows_top) / segment.row_height))
            last = min(
                segment.block.row_count,
                math.ceil((bottom - segment.rows_top) / segment.row_height),
            )
            first = min(segment.block.row_count, first)
            last = max(first, last)
            visible.append(VisibleSegment(segment, first, last))
        return tuple(visible)

    def segment_at_y(self, y: float) -> TimelineSegment | None:
        if not self.segments or y < 0 or y >= self.content_height:
            return None
        index = bisect_right(self._bottoms, y)
        return self.segments[index] if index < len(self.segments) else None

    def row_at_y(self, y: float) -> tuple[TimelineSegment, int] | None:
        segment = self.segment_at_y(y)
        if segment is None or y < segment.rows_top:
            return None
        if segment.row_height <= 0:
            return None
        index = int((y - segment.rows_top) // segment.row_height)
        if index >= segment.block.row_count:
            return None
        return segment, index

    def cell_at(self, x: float, y: float) -> tuple[TimelineSegment, int, int] | None:
        row = self.row_at_y(y)
        if row is None or x < self.geometry.ruler_width:
            return None
        lane = int((x - self.geometry.ruler_width) // self.geometry.lane_width)
        if not 0 <= lane < self.snapshot.columns:
            return None
        return row[0], row[1], lane

    def pixels_for_beats_at_y(self, y: float, beats: float) -> float:
        """Convert a musical wheel step to pixels for the split under ``y``."""
        if not math.isfinite(beats):
            raise ValueError("beats must be finite")
        segment = self.segment_at_y(y)
        if segment is None:
            return 0.0
        return beats * max(1, segment.block.beat_split) * segment.row_height

    def y_for_chart_time(self, time_ms: float) -> float | None:
        """Project absolute chart time onto the closest active Block row.

        Blocks carry explicit time anchors, so gaps and discontinuities must
        not be reconstructed from neighboring geometry. When time is outside
        every Block, clamp to the closest endpoint.
        """
        if not math.isfinite(time_ms):
            raise ValueError("chart time must be finite")
        candidates: list[tuple[float, int, TimelineSegment]] = []
        for segment in self.segments:
            block = segment.block
            if block.bpm <= 0.0 or block.beat_split <= 0:
                continue
            candidates.append((block.start_time, segment.split_index, segment))
        if not candidates:
            return None
        started = [candidate for candidate in candidates if candidate[0] <= time_ms]
        if started:
            _, _, selected = max(started, key=lambda candidate: candidate[:2])
        else:
            _, _, selected = min(candidates, key=lambda candidate: candidate[:2])
        block = selected.block
        row_duration = 60_000.0 / (block.bpm * block.beat_split)
        row = (time_ms - block.start_time) / row_duration
        clamped = min(float(block.row_count), max(0.0, row))
        return selected.rows_top + clamped * selected.row_height

    @staticmethod
    def snap_row_index(
        segment: TimelineSegment, row_index: int, beat_interval: float
    ) -> int:
        """Snap a row to a musical interval without crossing Block bounds."""
        if not math.isfinite(beat_interval) or beat_interval < 0.0:
            raise ValueError("snap interval must be finite and non-negative")
        if not 0 <= row_index < segment.block.row_count:
            raise IndexError(row_index)
        if beat_interval == 0.0:
            return row_index
        rows_per_snap = max(1, round(segment.block.beat_split * beat_interval))
        # Use half-up rounding. Python's banker rounding makes exact midpoints
        # alternate between the earlier and later guide, which feels broken in
        # a mouse-driven grid even though it is mathematically defensible.
        snapped = math.floor(row_index / rows_per_snap + 0.5) * rows_per_snap
        return min(segment.block.row_count - 1, max(0, snapped))

    @staticmethod
    def rows_per_snap(segment: TimelineSegment, beat_interval: float) -> int:
        if not math.isfinite(beat_interval) or beat_interval < 0.0:
            raise ValueError("snap interval must be finite and non-negative")
        if beat_interval == 0.0:
            return 1
        return max(1, round(segment.block.beat_split * beat_interval))

    def beat_markers(self, visible: VisibleSegment) -> tuple[BeatMarker, ...]:
        split = visible.segment.block.beat_split
        measure = visible.segment.block.beat_measure
        if split <= 0:
            return ()
        first = visible.first_row - (visible.first_row % split)
        markers = []
        for row_index in range(first, visible.last_row + 1, split):
            beat_index = row_index // split
            markers.append(
                BeatMarker(
                    row_index=row_index,
                    y=visible.segment.y_for_row(row_index),
                    beat=float(beat_index),
                    is_measure=measure > 0 and beat_index % measure == 0,
                )
            )
        return tuple(markers)
