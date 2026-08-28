from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from math import isfinite

from stepnx.core.model import NoteRow, PackedNoteRow
from stepnx.core.validation import Severity
from stepnx.preview.native_timing import (
    DIV_FLAG_SKIP,
    DIV_FLAG_SMOOTH,
    NativeTimingProjection,
    NativeTimingState,
    build_native_timing,
)
from stepnx.preview.routes import ResolvedRoute
from stepnx.preview.snapshot import PreviewSnapshot


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
    native_block_index: int = -1

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
    native_timing: NativeTimingProjection | None = None

    @property
    def duration_ms(self) -> float:
        return max((event.time_ms for event in self.events), default=0.0)

    @property
    def uses_native_skip_projection(self) -> bool:
        return self.native_timing is not None and any(
            div.is_skip for div in self.native_timing.blocks
        )

    def position_at(self, time_ms: float) -> float:
        """Return the current gameplay scroll coordinate.

        Routes containing bSkip use the source-faithful Block/Line coordinate.
        Routes without bSkip retain the already-validated continuous preview
        projection in this hotfix; the full LineBase velocity audit is separate.
        """

        if self.uses_native_skip_projection:
            assert self.native_timing is not None
            return self.native_timing.current_position(time_ms)
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

    def native_state_at(self, time_ms: float) -> NativeTimingState | None:
        return None if self.native_timing is None else self.native_timing.state_at(time_ms)

    def beat_distance_at(
        self,
        event: PreviewEvent,
        time_ms: float,
        *,
        state: NativeTimingState | None = None,
    ) -> float:
        """Return the exact native GetBlockBeat distance for one event."""

        if self.native_timing is not None and event.native_block_index >= 0:
            if state is None:
                state = self.native_timing.state_at(time_ms)
            return self.native_timing.block_beat_from_state(
                event.native_block_index,
                event.row_index,
                state,
            )
        return event.position - self.position_at(time_ms)

    def speed_factor_at(self, time_ms: float) -> float:
        """Return the preview speed multiplier active at ``time_ms``.

        Speed interpolation remains the pre-hotfix approximation for now.  The
        source-faithful change in this patch is the Block/Line timing and
        geometry projection; LineBase velocity behavior is a separate audit.
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

    native_timing = build_native_timing(snapshot, route)
    use_native_skip = any(div.is_skip for div in native_timing.blocks)
    events: list[PreviewEvent] = []
    timing: list[PreviewTimingSegment] = []
    warnings: list[str] = []
    previous_speed_factor = 1.0
    legacy_position = 0.0
    selected_blocks = [
        (split, split.block(route.block_id(split.stable_id)))
        for split in snapshot.splits
    ]

    for selected_index, (split, block) in enumerate(selected_blocks):
        if block.bpm <= 0.0 or block.beat_split <= 0:
            warnings.append(f"Block {block.stable_id} has invalid BPM or Beat Split")
            continue
        native_div = native_timing.blocks[selected_index]
        is_skip = bool(block.smooth_speed & DIV_FLAG_SKIP)

        # Preserve the old speed-transition segment model until LineBase
        # velocity is audited independently.  It no longer controls judgment
        # times, and Skip routes no longer use it as their primary scroll axis.
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
        safe_scroll = native_div.beat_per_line
        legacy_row_ms = 60_000.0 / (block.bpm * block.beat_split)
        motion_start = block.start_time_ms + freeze_delay
        motion_end = motion_start + len(block.rows) * legacy_row_ms
        if use_native_skip:
            start_position = native_timing.line_position(selected_index, 0)
            end_position = native_timing.line_position(selected_index, len(block.rows))
        else:
            start_position = legacy_position
            end_position = legacy_position + len(block.rows) * safe_scroll

        if not isfinite(block.speed_or_freeze):
            warnings.append(
                f"Block {block.stable_id} has a non-finite Speed/Freeze factor; "
                "renderer uses 1x"
            )
            target_speed_factor = 1.0
        else:
            target_speed_factor = abs(block.speed_or_freeze)
        # R!SE DivFlags is a bitfield.  Only bSmooth (0x01) enables block-speed
        # interpolation; bSkip (0x02) by itself must not do so.
        smooth_transition = bool(block.smooth_speed & DIV_FLAG_SMOOTH)
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
                start_position,
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
            # Step.Judge and LineBase.CreateSplits both use exactly
            # msStart + line * msPerLine.  For bSkip msPerLine is zero, so all
            # encoded rows share the Div StartTime while remaining independent
            # spatial rows and fully judgeable according to note semantics.
            time_ms = native_timing.judgment_time(selected_index, row_index)
            beat = row_index / block.beat_split
            event_position = (
                native_timing.line_position(selected_index, row_index)
                if use_native_skip
                else legacy_position + row_index * safe_scroll
            )
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
                        event_position,
                        selected_index,
                    )
                )
        legacy_position = end_position if not use_native_skip else legacy_position
        previous_speed_factor = target_speed_factor

    timing.sort(key=lambda item: (item.start_time_ms, item.split_id, item.block_id))
    events.sort(
        key=lambda item: (item.time_ms, item.native_block_index, item.row_index, item.lane)
    )
    return RuntimeEventStream(
        snapshot.source_name,
        snapshot.profile,
        route,
        tuple(events),
        tuple(timing),
        tuple(warnings),
        native_timing,
    )
