from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from math import isfinite

from stepnx.core.model import NoteRow, PackedNoteRow
from stepnx.core.validation import Severity
from stepnx.preview.modifiers import EffectiveModifier, StepParam, apply_step_params
from stepnx.preview.native_timing import (
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
        """Historical low-nibble note type used by preview drawing."""
        return self.raw[0] & 0x0F

    @property
    def attribute(self) -> int:
        return self.raw[0]

    @property
    def visual_effect(self) -> int:
        return self.raw[1]

    @property
    def bank_param(self) -> int:
        return self.raw[2] | (self.raw[3] << 8)

    @property
    def base_note_type(self) -> int:
        """PIUMobileStepDLL.Attributes.TypeMask (low two bits)."""
        return self.attribute & 0x03

    @property
    def judge_mask(self) -> int:
        return self.attribute & 0xE0

    @property
    def no_judge(self) -> bool:
        return self.judge_mask == 0x20

    @property
    def no_rush(self) -> bool:
        return bool(self.attribute & 0x10)

    @property
    def long_kind(self) -> int:
        return self.attribute & 0x0C

    @property
    def long_flags(self) -> int:
        return self.attribute & 0x1C

    @property
    def y_table(self) -> int:
        return self.visual_effect & 0x0F

    @property
    def param(self) -> int:
        return self.bank_param & 0x3FFF

    @property
    def bank(self) -> int:
        return self.bank_param >> 14

    @property
    def visible_for_judge(self) -> bool:
        return bool(self.visual_effect & 0x01)

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
    effective_modifier: EffectiveModifier | None = None
    header_step_params: tuple[StepParam, ...] = ()
    start_column: int = 0
    columns: int = 5

    @property
    def duration_ms(self) -> float:
        return max((event.time_ms for event in self.events), default=0.0)

    @property
    def uses_native_skip_projection(self) -> bool:
        return self.native_timing is not None and any(
            div.is_skip for div in self.native_timing.blocks
        )

    def position_at(self, time_ms: float) -> float:
        """Return the compatibility cumulative-row preview coordinate.

        Skip routes retain the native absolute coordinate because zero-duration
        Divs cannot be represented by the old monotonic segment interpolation.
        Runtime note placement never depends on this compatibility axis;
        ``beat_distance_at`` uses PlayBase.GetBlockBeat directly for every route.
        """

        if self.uses_native_skip_projection and self.native_timing is not None:
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
        """Return R!SE's active Div block speed, including Smooth handling."""

        if self.native_timing is None:
            return 1.0
        return self.native_timing.block_speed_at(time_ms)

    def current_gap_at(self, time_ms: float) -> float:
        """Return the active Step.currentGap() value in milliseconds."""

        if self.native_timing is None:
            return 0.0
        return self.native_timing.current_gap(time_ms)

    def modifier_for_launch_speed(self, speed: float) -> EffectiveModifier:
        """Apply Header StepParams after the user-selected launch speed.

        PlayBase stores the selected high-speed value into GameModifier.Speed
        before calling ApplyStepParamToMod. Header ID 0 may therefore replace
        it and Header 1111 may multiply the result. Keeping this order here is
        necessary for the runtime speed state used by GameplaySession.
        """

        base = EffectiveModifier(speed=float(speed))
        return apply_step_params(self.header_step_params, base)


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

    def position_at(self, time_ms: float) -> float:
        if time_ms <= self.start_time_ms or self.end_time_ms <= self.start_time_ms:
            return self.start_position
        ratio = (time_ms - self.start_time_ms) / (self.end_time_ms - self.start_time_ms)
        return self.start_position + min(1.0, max(0.0, ratio)) * (
            self.end_position - self.start_position
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
    events: list[PreviewEvent] = []
    timing: list[PreviewTimingSegment] = []
    warnings: list[str] = []
    authored_position = 0.0
    selected_blocks = [
        (split, split.block(route.block_id(split.stable_id)))
        for split in snapshot.splits
    ]

    for selected_index, (split, block) in enumerate(selected_blocks):
        if block.bpm <= 0.0 or block.beat_split <= 0:
            warnings.append(f"Block {block.stable_id} has invalid BPM or Beat Split")
            continue
        native_div = native_timing.blocks[selected_index]

        if not isfinite(block.scroll):
            warnings.append(
                f"Block {block.stable_id} has no finite Scroll; "
                "renderer uses one row fraction"
            )
        if not isfinite(block.speed_or_freeze):
            warnings.append(
                f"Block {block.stable_id} has a non-finite Speed/Freeze factor"
            )

        # Negative serialized Speed is not a local visual freeze in R!SE.
        # StepLoader uses the sign only while deciding whether to construct Gap,
        # then normalizes Speed positive. PreviewTimingSegment remains a stable
        # authored-coordinate compatibility/culling axis; runtime Y placement
        # uses native Block/Line state through beat_distance_at().
        start_position = authored_position
        end_position = authored_position + len(block.rows) * native_div.beat_per_line
        timing.append(
            PreviewTimingSegment(
                split.stable_id,
                block.stable_id,
                native_div.start_time_ms,
                native_div.end_time_ms,
                start_position,
                end_position,
                block.bpm,
                block.beat_split,
                native_div.beat_per_line,
                0.0,
            )
        )

        for row_index, row in enumerate(block.rows):
            if not isinstance(row, (NoteRow, PackedNoteRow)):
                continue
            # Step.Judge and LineBase.CreateSplits both use exactly
            # msStart + line * msPerLine. For bSkip msPerLine is zero, so all
            # encoded rows share the Div StartTime while remaining independent
            # spatial rows and fully judgeable according to note semantics.
            time_ms = native_timing.judgment_time(selected_index, row_index)
            beat = row_index / block.beat_split
            event_position = authored_position + row_index * native_div.beat_per_line
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
        authored_position = end_position

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
        snapshot.effective_modifier(),
        snapshot.header_step_params,
        int(snapshot.start_column),
        int(snapshot.columns),
    )
