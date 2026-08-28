from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass

from stepnx.authoring.audio import MetronomeBeat, MetronomeNote
from stepnx.authoring.snapshot import AuthoringSnapshot, BlockSnapshot
from stepnx.core.commands import SetBlockFields
from stepnx.core.model import Block, EmptyRow, LightmapRow, NX20Document
from stepnx.core.scalars import RawF32, RawU8


DIV_FLAG_SKIP = 0x02


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


@dataclass(frozen=True, slots=True)
class TimingLocation:
    split_id: int
    block_id: int
    row: float


class TimingProjection:
    """NX20 row/time projection for the active authoring route.

    Normal Divs use their explicit Start Time plus msPerLine.  For bmFlags
    bSkip (raw smooth byte bit 0x02), the native NX20 loader sets msPerLine to
    zero.  Every encoded row therefore shares the Div Start Time while the Div
    still retains all rows spatially.  Step.GetBlock advances when
    DivEndTime <= current time, so a Skip Div is crossed instantaneously by the
    transport/playhead instead of being stretched across BPM-derived time.
    """

    def __init__(self, snapshot: AuthoringSnapshot) -> None:
        self.snapshot = snapshot
        self._active = tuple(
            (split, snapshot.active_block(split.stable_id))
            for split in snapshot.splits
            if split.blocks
        )

    @staticmethod
    def is_skip(block: BlockSnapshot) -> bool:
        return bool(block.smooth_speed & DIV_FLAG_SKIP)

    @staticmethod
    def encoded_row_duration_ms(block: BlockSnapshot) -> float:
        """Return the BPM-derived row duration before bSkip is applied."""
        if block.bpm <= 0.0 or block.beat_split <= 0:
            raise TimingEditError(
                f"Block {block.stable_id} needs positive BPM and Beat Split"
            )
        return 60_000.0 / (block.bpm * block.beat_split)

    @classmethod
    def row_duration_ms(cls, block: BlockSnapshot) -> float:
        """Return native msPerLine for an active NX20 Div."""
        duration = cls.encoded_row_duration_ms(block)
        return 0.0 if cls.is_skip(block) else duration

    @classmethod
    def end_time_ms(cls, block: BlockSnapshot) -> float:
        return block.start_time + block.row_count * cls.row_duration_ms(block)

    @classmethod
    def row_time_ms(cls, block: BlockSnapshot, row_index: int) -> float:
        if not 0 <= row_index <= block.row_count:
            raise IndexError(row_index)
        return block.start_time + row_index * cls.row_duration_ms(block)

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
            self.row_time_ms(block, row_index),
        )

    def locate(self, time_ms: float) -> TimingLocation | None:
        """Map chart time to the native active Block/Line position.

        This mirrors Step.GetBlock starting from block zero.  It intentionally
        uses Div end times rather than "latest Start Time", which is the key
        distinction for zero-duration bSkip Divs and overlapping snapshots.
        """
        if not math.isfinite(time_ms):
            raise ValueError("time must be finite")
        if not self._active:
            return None

        index = 0
        while index + 1 < len(self._active):
            block = self._active[index][1]
            if self.end_time_ms(block) > time_ms:
                break
            index += 1

        split, block = self._active[index]
        duration = self.row_duration_ms(block)
        if duration <= 0.0 or time_ms <= block.start_time:
            row = 0.0
        else:
            row = (time_ms - block.start_time) / duration
        row = min(float(block.row_count), max(0.0, row))
        return TimingLocation(split.stable_id, block.stable_id, row)

    def nearest_row(self, time_ms: float) -> TimingPoint | None:
        location = self.locate(time_ms)
        if location is None:
            return None
        split = self.snapshot.split(location.split_id)
        block = split.block(location.block_id)
        row = min(block.row_count, max(0, round(location.row)))
        return self.point(location.split_id, location.block_id, row)


class MetronomeClock:
    """Beat clock driven by the same active-Div selection as NX20 playback."""

    def __init__(self, snapshot: AuthoringSnapshot) -> None:
        self._projection = TimingProjection(snapshot)
        self._snapshot = snapshot

    def beat_at(self, chart_time_ms: float) -> MetronomeBeat | None:
        location = self._projection.locate(chart_time_ms)
        if location is None:
            return None
        block = self._snapshot.split(location.split_id).block(location.block_id)
        if block.bpm <= 0.0:
            return None
        beat_duration = 60_000.0 / block.bpm
        beat = max(0, int((chart_time_ms - block.start_time) // beat_duration))
        return MetronomeBeat(
            block.stable_id,
            beat,
            block.beat_measure > 0 and beat % block.beat_measure == 0,
        )


class NoteMetronomeClock:
    """Arrow clock using native per-row judgment time, including bSkip."""

    def __init__(self, snapshot: AuthoringSnapshot) -> None:
        projection = TimingProjection(snapshot)
        events: list[tuple[float, MetronomeNote]] = []
        for split in snapshot.splits:
            if not split.blocks:
                continue
            block = snapshot.active_block(split.stable_id)
            if block.bpm <= 0.0 or block.beat_split <= 0:
                continue
            for row_index, row in enumerate(block.rows):
                if isinstance(row, (EmptyRow, LightmapRow)):
                    continue
                cells = tuple(row.cell(lane) for lane in range(row.cell_count))
                if any(
                    cell.note_type in (0x3, 0x7) and cell.raw[0] & 0x40
                    for cell in cells
                ):
                    events.append(
                        (
                            projection.row_time_ms(block, row_index),
                            MetronomeNote(block.stable_id, row_index),
                        )
                    )
        events.sort(key=lambda item: item[0])
        self._times = tuple(item[0] for item in events)
        self._events = tuple(item[1] for item in events)

    def note_at(self, chart_time_ms: float) -> MetronomeNote | None:
        index = bisect_right(self._times, chart_time_ms) - 1
        return None if index < 0 else self._events[index]


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