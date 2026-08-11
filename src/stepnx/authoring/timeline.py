from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass

from stepnx.authoring.snapshot import AuthoringSnapshot, BlockSnapshot


@dataclass(frozen=True, slots=True)
class TimelineGeometry:
    row_height: float = 24.0
    block_header_height: float = 42.0
    lane_width: float = 48.0
    ruler_width: float = 92.0
    footer_height: float = 24.0
    minimum_row_height: float = 4.0
    maximum_row_height: float = 96.0

    def __post_init__(self) -> None:
        if not self.minimum_row_height <= self.row_height <= self.maximum_row_height:
            raise ValueError("row height is outside the supported zoom range")
        if min(self.block_header_height, self.lane_width, self.ruler_width) <= 0:
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
            footer_height=self.footer_height,
            minimum_row_height=self.minimum_row_height,
            maximum_row_height=self.maximum_row_height,
        )


@dataclass(frozen=True, slots=True)
class TimelineSegment:
    split_id: int
    split_index: int
    block: BlockSnapshot
    top: float
    rows_top: float
    bottom: float

    def y_for_row(self, row_index: int, geometry: TimelineGeometry) -> float:
        if not 0 <= row_index <= self.block.row_count:
            raise IndexError(row_index)
        return self.rows_top + row_index * geometry.row_height


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

    __slots__ = ("_bottoms", "content_height", "geometry", "segments", "snapshot")

    def __init__(self, snapshot: AuthoringSnapshot, geometry: TimelineGeometry | None = None) -> None:
        self.snapshot = snapshot
        self.geometry = geometry or TimelineGeometry()
        segments: list[TimelineSegment] = []
        top = 0.0
        for split in snapshot.splits:
            if not split.blocks:
                continue
            block = snapshot.active_block(split.stable_id)
            rows_top = top + self.geometry.block_header_height
            bottom = rows_top + block.row_count * self.geometry.row_height
            segments.append(
                TimelineSegment(
                    split_id=split.stable_id,
                    split_index=split.index,
                    block=block,
                    top=top,
                    rows_top=rows_top,
                    bottom=bottom,
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
            first = max(0, math.floor((top - segment.rows_top) / self.geometry.row_height))
            last = min(
                segment.block.row_count,
                math.ceil((bottom - segment.rows_top) / self.geometry.row_height),
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
        index = int((y - segment.rows_top) // self.geometry.row_height)
        if index >= segment.block.row_count:
            return None
        return segment, index

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
                    y=visible.segment.y_for_row(row_index, self.geometry),
                    beat=float(beat_index),
                    is_measure=measure > 0 and beat_index % measure == 0,
                )
            )
        return tuple(markers)
