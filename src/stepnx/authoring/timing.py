from __future__ import annotations

import math
from dataclasses import dataclass

from stepnx.authoring.snapshot import AuthoringSnapshot, BlockSnapshot
from stepnx.core.commands import SetBlockFields
from stepnx.core.model import Block, NX20Document
from stepnx.core.scalars import RawF32, RawU8


class TimingEditError(ValueError):
    """Raised when typed Block timing would be unusable or unrepresentable."""


@dataclass(frozen=True, slots=True)
class BlockTimingValues:
    start_time_ms: float
    bpm: float
    scroll_factor: float
    offset_or_delay_ms: float
    speed_or_freeze: float
    beat_split: int
    beat_measure: int
    smooth_speed: int
    raw_flag: int

    @classmethod
    def from_block(cls, block: Block) -> BlockTimingValues:
        return cls(
            float(block.start_time.value),
            float(block.bpm.value),
            float(block.scroll.value),
            float(block.offset_or_delay.value),
            float(block.speed_or_freeze.value),
            int(block.beat_split.value),
            int(block.beat_measure.value),
            int(block.smooth_speed.value),
            int(block.raw_flag.value),
        )

    @property
    def is_freeze(self) -> bool:
        return self.speed_or_freeze < 0.0

    @property
    def speed(self) -> float:
        return abs(self.speed_or_freeze)

    @property
    def real_scroll(self) -> float:
        return self.scroll_factor * self.beat_split

    def validated(self) -> BlockTimingValues:
        floats = {
            "Start Time": self.start_time_ms,
            "BPM": self.bpm,
            "Scroll Factor": self.scroll_factor,
            "Offset/Delay": self.offset_or_delay_ms,
            "Speed/Freeze": self.speed_or_freeze,
        }
        for label, value in floats.items():
            if not math.isfinite(value):
                raise TimingEditError(f"{label} must be finite")
        if self.bpm <= 0.0:
            raise TimingEditError("BPM must be greater than zero")
        if not 1 <= self.beat_split <= 0xFF:
            raise TimingEditError("Beat Split must be between 1 and 255")
        if not 1 <= self.beat_measure <= 0xFF:
            raise TimingEditError("Beat Measure must be between 1 and 255")
        for label, value in (
            ("Smooth Speed", self.smooth_speed),
            ("Raw Flag", self.raw_flag),
        ):
            if not 0 <= value <= 0xFF:
                raise TimingEditError(f"{label} must be between 0 and 255")
        return self

    def command(self, block_id: int) -> SetBlockFields:
        self.validated()
        return SetBlockFields(
            block_id,
            (
                ("start_time", RawF32.from_value(self.start_time_ms)),
                ("bpm", RawF32.from_value(self.bpm)),
                ("scroll", RawF32.from_value(self.scroll_factor)),
                ("offset_or_delay", RawF32.from_value(self.offset_or_delay_ms)),
                ("speed_or_freeze", RawF32.from_value(self.speed_or_freeze)),
                ("beat_split", RawU8.from_value(self.beat_split)),
                ("beat_measure", RawU8.from_value(self.beat_measure)),
                ("smooth_speed", RawU8.from_value(self.smooth_speed)),
                ("raw_flag", RawU8.from_value(self.raw_flag)),
            ),
        )


@dataclass(frozen=True, slots=True)
class TimingPoint:
    split_id: int
    block_id: int
    row_index: int
    beat: float
    time_ms: float


class TimingProjection:
    """Deterministic row/beat/time conversion for the active authoring route.

    NX20 stores an explicit Start Time for every Block.  We deliberately use
    that value as the Block anchor instead of trying to reconstruct it from
    neighboring Blocks; the latter would silently rewrite charts whose timing
    is intentionally discontinuous.
    """

    def __init__(self, snapshot: AuthoringSnapshot) -> None:
        self.snapshot = snapshot

    @staticmethod
    def row_duration_ms(block: BlockSnapshot) -> float:
        if block.bpm <= 0.0 or block.beat_split <= 0:
            raise TimingEditError(
                f"Block {block.stable_id} needs positive BPM and Beat Split"
            )
        return 60_000.0 / (block.bpm * block.beat_split)

    def point(self, split_id: int, block_id: int, row_index: int) -> TimingPoint:
        split = self.snapshot.split(split_id)
        block = split.block(block_id)
        if not 0 <= row_index <= block.row_count:
            raise IndexError(row_index)
        beat = row_index / block.beat_split
        return TimingPoint(
            split_id,
            block_id,
            row_index,
            beat,
            block.start_time + row_index * self.row_duration_ms(block),
        )

    def nearest_row(self, time_ms: float) -> TimingPoint | None:
        if not math.isfinite(time_ms):
            raise ValueError("time must be finite")
        candidates: list[TimingPoint] = []
        for split in self.snapshot.splits:
            if not split.blocks:
                continue
            block = self.snapshot.active_block(split.stable_id)
            duration = self.row_duration_ms(block)
            row = round((time_ms - block.start_time) / duration)
            row = min(block.row_count, max(0, row))
            candidates.append(self.point(split.stable_id, block.stable_id, row))
        if not candidates:
            return None
        return min(candidates, key=lambda point: abs(point.time_ms - time_ms))


@dataclass(frozen=True, slots=True)
class ShiftBlockStartTimes:
    """Shift every Block Start Time atomically while preserving float fields."""

    delta_ms: float

    def apply(self, document: NX20Document) -> NX20Document:
        if not math.isfinite(self.delta_ms):
            raise TimingEditError("Start Time shift must be finite")
        result = document
        for split in document.splits:
            for block in split.blocks:
                result = SetBlockFields(
                    block.stable_id,
                    (("start_time", RawF32.from_value(float(block.start_time.value) + self.delta_ms)),),
                ).apply(result)
        return result
