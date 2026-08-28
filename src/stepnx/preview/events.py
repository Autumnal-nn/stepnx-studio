from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from math import isfinite

from stepnx.core.model import NoteRow, PackedNoteRow
from stepnx.core.validation import Severity
from stepnx.preview.routes import ResolvedRoute
from stepnx.preview.snapshot import PreviewSnapshot


DIV_FLAG_SMOOTH = 0x01
DIV_FLAG_SKIP = 0x02


class PreviewNoteFunction(str, Enum):
    NORMAL = "normal"
    BONUS = "bonus"
    GHOST = "ghost"
    UNKNOWN = "unknown"


class PreviewNoteVisibility(IntEnum):
    INVISIBLE = 0
    APPEAR = 1
    VANISH = 2
    VISIBLE = 3


@dataclass(frozen=True, slots=True)
class PreviewEvent:
    time_ms: float
    beat: float
    split_id: int
    block_id: int
    row_index: int
    lane: int
    raw: bytes
    scroll: float
    position: float

    @property
    def note_type(self) -> int:
        return self.raw[0] & 0x0F

    @property
    def function(self) -> PreviewNoteFunction:
        return {
            0x00: PreviewNoteFunction.NORMAL,
            0x40: PreviewNoteFunction.NORMAL,
            0x60: PreviewNoteFunction.BONUS,
            0x20: PreviewNoteFunction.GHOST,
        }.get(self.raw[0] & 0x60, PreviewNoteFunction.UNKNOWN)

    @property
    def visibility(self) -> PreviewNoteVisibility:
        return PreviewNoteVisibility(self.raw[1] & 0x03)

    @property
    def registers(self) -> bool:
        return self.function is not PreviewNoteFunction.GHOST

    @property
    def effective_scroll(self) -> float:
        """Return a safe visual multiplier without rewriting the raw value."""
        return self.scroll if isfinite(self.scroll) else 1.0


@dataclass(frozen=True, slots=True)
class RuntimeEventStream:
    source_name: str | None
    profile: str
    route: ResolvedRoute
    events: tuple[PreviewEvent, ...]
    timing: tuple[PreviewTimingSegment, ...]
    warnings: tuple[str, ...]

    @property
    def duration_ms(self) -> float:
        return max((event.time_ms for event in self.events), default=0.0)

    def position_at(self, time_ms: float) -> float:
        if not self.timing:
            return 0.0
        if time_ms < self.timing[0].start_time_ms:
            return self.timing[0].start_position
        selected = self.timing[0]
        for segment in self.timing:
            if time_ms < segment.start_time_ms:
                break
            selected = segment
        return selected.position_at(time_ms)

    def speed_factor_at(self, time_ms: float) -> float:
        """Return the engine scroll factor active at ``time_ms``.

        The fifth Block float is the visual speed factor (negative values also
        mark freezes). The Block flag byte is a bitfield: bit 0 requests a
        smooth transition and bit 1 is the native Skip/warp flag.
        """

        if not self.timing:
            return 1.0
        if time_ms < self.timing[0].start_time_ms:
            return self.timing[0].start_speed_factor
        selected = self.timing[0]
        for segment in self.timing:
            if time_ms < segment.start_time_ms:
                break
            selected = segment
        return selected.speed_factor_at(time_ms)


@dataclass(frozen=True, slots=True)
class PreviewTimingSegment:
    split_id: int
    block_id: int
    start_time_ms: float
    end_time_ms: float
    start_position: float
    end_position: float
    bpm: float
    beat_split: int
    scroll: float
    freeze_delay_ms: float
    start_speed_factor: float
    end_speed_factor: float
    speed_transition_end_ms: float

    def position_at(self, time_ms: float) -> float:
        if time_ms <= self.start_time_ms or self.end_time_ms <= self.start_time_ms:
            return self.start_position
        ratio = (time_ms - self.start_time_ms) / (self.end_time_ms - self.start_time_ms)
        return self.start_position + min(1.0, max(0.0, ratio)) * (
            self.end_position - self.start_position
        )

    def speed_factor_at(self, time_ms: float) -> float:
        if (
            time_ms <= self.start_time_ms
            or self.speed_transition_end_ms <= self.start_time_ms
        ):
            return self.start_speed_factor
        ratio = (time_ms - self.start_time_ms) / (
            self.speed_transition_end_ms - self.start_time_ms
        )
        ratio = min(1.0, max(0.0, ratio))
        return self.start_speed_factor + ratio * (
            self.end_speed_factor - self.start_speed_factor
        )


def build_event_stream(
    snapshot: PreviewSnapshot, route: ResolvedRoute
) -> RuntimeEventStream:
    if any(
        diagnostic.severity is Severity.ERROR for diagnostic in snapshot.diagnostics
    ):
        raise ValueError("cannot build events from a non-playable preview snapshot")
    if not route.is_executable:
        raise ValueError("cannot build events from an unresolved route")
    events: list[PreviewEvent] = []
    timing: list[PreviewTimingSegment] = []
    warnings: list[str] = []
    position = 0.0
    previous_speed_factor = 1.0
    selected_blocks = [
        (split, split.block(route.block_id(split.stable_id)))
        for split in snapshot.splits
    ]
    for selected_index, (split, block) in enumerate(selected_blocks):
        if block.bpm <= 0.0 or block.beat_split <= 0:
            warnings.append(f"Block {block.stable_id} has invalid BPM or Beat Split")
            continue
        flags = block.smooth_speed
        is_skip = bool(flags & DIV_FLAG_SKIP)
        freeze_delay = (
            max(0.0, block.offset_or_delay_ms)
            if block.speed_or_freeze < 0.0 and not is_skip
            else 0.0
        )
        if not isfinite(block.scroll):
            warnings.append(
                f"Block {block.stable_id} has no finite Scroll; "
                "renderer uses one row fraction"
            )
        safe_scroll = (
            block.scroll
            if isfinite(block.scroll)
            else 1.0 / block.beat_split
        )
        row_ms = 60_000.0 / (block.bpm * block.beat_split)
        motion_start = block.start_time_ms + freeze_delay
        motion_end = motion_start + len(block.rows) * row_ms
        end_position = position + len(block.rows) * safe_scroll
        if not isfinite(block.speed_or_freeze):
            warnings.append(
                f"Block {block.stable_id} has a non-finite Speed/Freeze factor; "
                "renderer uses 1x"
            )
            target_speed_factor = 1.0
        else:
            target_speed_factor = abs(block.speed_or_freeze)
        smooth_transition = bool(flags & DIV_FLAG_SMOOTH)
        start_speed_factor = (
            previous_speed_factor if smooth_transition else target_speed_factor
        )
        if selected_index + 1 < len(selected_blocks):
            next_block = selected_blocks[selected_index + 1][1]
            transition_end = max(motion_start, next_block.start_time_ms)
        else:
            transition_end = motion_end
        if not smooth_transition or transition_end <= motion_start:
            start_speed_factor = target_speed_factor
            transition_end = motion_start
        timing.append(
            PreviewTimingSegment(
                split.stable_id,
                block.stable_id,
                motion_start,
                motion_end,
                position,
                end_position,
                block.bpm,
                block.beat_split,
                safe_scroll,
                freeze_delay,
                start_speed_factor,
                target_speed_factor,
                transition_end,
            )
        )
        for row_index, row in enumerate(block.rows):
            if not isinstance(row, (NoteRow, PackedNoteRow)):
                continue
            time_ms = motion_start + row_index * row_ms
            beat = row_index / block.beat_split
            for lane, cell in enumerate(row.cells):
                if cell.raw == b"\x00\x00\x00\x00":
                    continue
                events.append(
                    PreviewEvent(
                        time_ms,
                        beat,
                        split.stable_id,
                        block.stable_id,
                        row_index,
                        lane,
                        cell.raw,
                        block.scroll,
                        position + row_index * safe_scroll,
                    )
                )
        position = end_position
        previous_speed_factor = target_speed_factor
    timing.sort(key=lambda item: (item.start_time_ms, item.split_id, item.block_id))
    events.sort(
        key=lambda item: (item.time_ms, item.split_id, item.row_index, item.lane)
    )
    return RuntimeEventStream(
        snapshot.source_name,
        snapshot.profile,
        route,
        tuple(events),
        tuple(timing),
        tuple(warnings),
    )
