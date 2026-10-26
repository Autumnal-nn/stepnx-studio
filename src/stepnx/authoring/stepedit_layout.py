"""STEPEdit 5.63-inspired *optional* geometry for a future Qt editor.

Pure projection: no NX20 mutation and no dependence on the legacy widget.
The row-pitch formula and x regions come from static REA/Ghidra inspection;
dense-grid rounding and resize interactions are conservative Studio policies,
not claims of byte-for-byte STEPEdit runtime fidelity.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from enum import IntEnum

from stepnx.authoring.snapshot import AuthoringSnapshot


STEPEDIT_VERTICAL_ZOOMS = (1, 2, 3, 4, 6, 8, 12, 16)


class StepEditRegion(IntEnum):
    BODY = 0
    INDICATOR = 1
    PROPERTIES = 2
    GROUND = 3
    RESIZE = 4


@dataclass(frozen=True, slots=True)
class StepEditGeometry:
    vertical_zoom: float = 1.0
    beat_height: float = 48.0
    lane_pitch: float = 24.0
    indicator_width: float = 31.0
    property_width: float = 300.0
    resize_band: float = 5.0

    def __post_init__(self) -> None:
        values = (
            self.vertical_zoom, self.beat_height, self.lane_pitch,
            self.indicator_width, self.property_width,
        )
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("STEPEdit geometry dimensions must be finite and positive")
        if not math.isfinite(self.resize_band) or self.resize_band < 0:
            raise ValueError("resize band must be finite and non-negative")

    def with_zoom(self, zoom: float) -> StepEditGeometry:
        return StepEditGeometry(
            vertical_zoom=zoom,
            beat_height=self.beat_height,
            lane_pitch=self.lane_pitch,
            indicator_width=self.indicator_width,
            property_width=self.property_width,
            resize_band=self.resize_band,
        )


@dataclass(frozen=True, slots=True)
class StepEditSegment:
    split_id: int
    block_id: int
    split_index: int
    block_index: int
    top: float
    bottom: float
    row_count: int
    beat_split: int
    row_pitch: float

    def y_for_row(self, row_index: int, *, center: bool = False) -> float:
        if not 0 <= row_index < self.row_count:
            raise IndexError(row_index)
        return self.top + (row_index + (0.5 if center else 0.0)) * self.row_pitch


@dataclass(frozen=True, slots=True)
class StepEditHit:
    region: StepEditRegion
    split_id: int | None = None
    block_id: int | None = None
    row_index: int | None = None
    lane: int | None = None
    source_lane: int | None = None


@dataclass(frozen=True, slots=True)
class StepEditVisibleSegment:
    segment: StepEditSegment
    first_row: int
    last_row: int

    @property
    def row_count(self) -> int:
        return self.last_row - self.first_row


class StepEditGridLayout:
    """Per-Block BeatSplit geometry for the currently selected Split route.

    x coordinates and scroll positions are logical CSS/Qt pixels, not device
    pixels. Device pixel ratio is a separate responsibility of the Qt view.
    """

    def __init__(
        self,
        snapshot: AuthoringSnapshot,
        geometry: StepEditGeometry | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.geometry = geometry or StepEditGeometry()
        segments: list[StepEditSegment] = []
        y = 0.0
        for split in snapshot.splits:
            if not split.blocks:
                continue
            block = snapshot.active_block(split.stable_id)
            if block.beat_split <= 0:
                raise ValueError(
                    f"Split {split.index} Block {block.index} has invalid BeatSplit "
                    f"{block.beat_split}"
                )
            pitch = self.geometry.beat_height * self.geometry.vertical_zoom / block.beat_split
            if not math.isfinite(pitch) or pitch <= 0:
                raise ValueError("row pitch is outside the supported geometric range")
            end = y + block.row_count * pitch
            if not math.isfinite(end):
                raise ValueError("chart height exceeds the geometric range")
            segments.append(
                StepEditSegment(
                    split_id=split.stable_id,
                    block_id=block.stable_id,
                    split_index=split.index,
                    block_index=block.index,
                    top=y,
                    bottom=end,
                    row_count=block.row_count,
                    beat_split=block.beat_split,
                    row_pitch=pitch,
                )
            )
            y = end
        self.segments = tuple(segments)
        self.content_height = y
        self._bottoms = tuple(segment.bottom for segment in segments)
        self._by_split = {segment.split_id: segment for segment in segments}

    @property
    def grid_left(self) -> float:
        return self.geometry.indicator_width

    @property
    def grid_right(self) -> float:
        return self.grid_left + self.snapshot.columns * self.geometry.lane_pitch

    @property
    def content_width(self) -> float:
        return self.grid_right + self.geometry.property_width

    def segment(self, split_id: int) -> StepEditSegment:
        return self._by_split[split_id]

    def y_for_row(self, split_id: int, row_index: int, *, center: bool = False) -> float:
        return self.segment(split_id).y_for_row(row_index, center=center)

    def x_for_lane(self, lane: int, *, center: bool = True) -> float:
        if not 0 <= lane < self.snapshot.columns:
            raise IndexError(lane)
        return self.grid_left + (lane + (0.5 if center else 0.0)) * self.geometry.lane_pitch

    def required_zoom_for_pixel_rows(self, split_id: int, *, minimum_pixels: float = 1.0) -> float:
        if not math.isfinite(minimum_pixels) or minimum_pixels <= 0:
            raise ValueError("minimum row pitch must be finite and positive")
        return minimum_pixels * self.segment(split_id).beat_split / self.geometry.beat_height

    def hit_test(self, client_x: float, client_y: float, *, scroll_y: float = 0.0) -> StepEditHit:
        if not all(math.isfinite(v) for v in (client_x, client_y, scroll_y)):
            return StepEditHit(StepEditRegion.GROUND)
        logical_y = client_y + scroll_y
        if (
            client_x < 0
            or client_x >= self.content_width
            or logical_y < 0
            or not self.segments
        ):
            return StepEditHit(StepEditRegion.GROUND)
        index = bisect_right(self._bottoms, logical_y)
        if index >= len(self.segments):
            return StepEditHit(StepEditRegion.GROUND)
        segment = self.segments[index]
        if logical_y < segment.top or logical_y >= segment.bottom:
            return StepEditHit(StepEditRegion.GROUND)
        base = dict(split_id=segment.split_id, block_id=segment.block_id)
        if client_x < self.grid_left:
            return StepEditHit(StepEditRegion.INDICATOR, **base)
        if client_x >= self.grid_right:
            return StepEditHit(StepEditRegion.PROPERTIES, **base)

        # Dense grids must remain hittable even when a whole row is < 5 px.
        # The terminal resize area must never swallow the last row's center.
        band = min(self.geometry.resize_band, segment.row_pitch * 0.25)
        if band > 0 and logical_y >= segment.bottom - band:
            return StepEditHit(StepEditRegion.RESIZE, **base)

        lane = int((client_x - self.grid_left) // self.geometry.lane_pitch)
        row = min(segment.row_count - 1, int((logical_y - segment.top) / segment.row_pitch))
        if not (0 <= lane < self.snapshot.columns and 0 <= row < segment.row_count):
            return StepEditHit(StepEditRegion.GROUND)
        return StepEditHit(
            StepEditRegion.BODY,
            row_index=row,
            lane=lane,
            source_lane=lane + self.snapshot.start_column,
            **base,
        )

    def scroll_for_anchor(
        self, old: StepEditGridLayout, split_id: int, row_index: int,
        viewport_y: float, *, clamp: bool = True,
    ) -> float:
        """Keep a specific logical row at the same client Y after zoom."""
        if not math.isfinite(viewport_y):
            raise ValueError("anchor client coordinate must be finite")
        # The old layout is supplied explicitly for consistency checks.
        old.segment(split_id).y_for_row(row_index, center=True)
        desired = self.y_for_row(split_id, row_index, center=True) - viewport_y
        return max(0.0, desired) if clamp else desired

    def visible_segments(
        self, scroll_y: float, viewport_height: float, *, overscan_rows: int = 2
    ) -> tuple[StepEditVisibleSegment, ...]:
        if not all(math.isfinite(v) for v in (scroll_y, viewport_height)):
            raise ValueError("viewport coordinates must be finite")
        if viewport_height < 0 or overscan_rows < 0:
            raise ValueError("viewport height and overscan must be non-negative")
        if viewport_height == 0 or not self.segments:
            return ()
        visible: list[StepEditVisibleSegment] = []
        start = max(0, bisect_right(self._bottoms, scroll_y))
        end_y = scroll_y + viewport_height
        for segment in self.segments[start:]:
            if segment.top > end_y:
                break
            first = max(
                0, int(math.floor((scroll_y - segment.top) / segment.row_pitch))
                - overscan_rows,
            )
            last = min(
                segment.row_count,
                int(math.ceil((end_y - segment.top) / segment.row_pitch))
                + overscan_rows,
            )
            if first < last:
                visible.append(StepEditVisibleSegment(segment, first, last))
        return tuple(visible)
