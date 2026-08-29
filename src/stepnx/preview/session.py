from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, replace
from enum import Enum

from stepnx.preview.commands import GameplayCommand
from stepnx.preview.events import PreviewEvent, RuntimeEventStream
from stepnx.preview.gauge import RuntimeGauge
from stepnx.preview.judge_timing import NativeJudgeTiming
from stepnx.preview.judgment import (
    JudgeUnitProjection,
    judge_note_decision,
    project_judge_unit,
    summarize_judge_line,
)
from stepnx.preview.modifiers import SpeedMode
from stepnx.preview.scoring import add_score_floor_zero, native_score_delta
from stepnx.preview.speed import (
    DRAW_STEP_INTERVAL_MS,
    RuntimeSpeedState,
    earthworm_user_speed,
    random_velocity_triggers,
    random_velocity_user_speed,
)


class Judgment(str, Enum):
    PERFECT = "PERFECT"
    GREAT = "GREAT"
    GOOD = "GOOD"
    BAD = "BAD"
    MISS = "MISS"


# Public compatibility name. The previous preview exposed JudgmentWindows, but
# the runtime model is now the asymmetric Step.Judge timing structure.
JudgmentWindows = NativeJudgeTiming


@dataclass(frozen=True, slots=True)
class GameplayStats:
    perfect: int = 0
    great: int = 0
    good: int = 0
    bad: int = 0
    miss: int = 0
    combo: int = 0
    max_combo: int = 0
    score: int = 0
    gauge: int = 500


@dataclass(frozen=True, slots=True)
class StepEffect:
    time_ms: float
    lane: int
    bank_id: int


_JUDGMENT_RANK = {
    Judgment.PERFECT: 0,
    Judgment.GREAT: 1,
    Judgment.GOOD: 2,
    Judgment.BAD: 3,
    Judgment.MISS: 4,
}
_GRADE_JUDGMENT = {value: key for key, value in _JUDGMENT_RANK.items()}

EventKey = tuple[int, int, int, int]
GroupKey = tuple[int, int, int, int, int]


class GameplaySession:
    """Mutable R!SE gameplay state kept outside the canonical document.

    Judgment grouping follows JudgeLine/JudgeNote, timing follows Step.Judge,
    score follows JudgeStep_PostProcess/GetScore, gauge follows HPBar, and the
    high-speed state follows DrawStep/SpeedProc. The preview intentionally keeps
    these runtime projections separate from historical authoring registries.
    """

    def __init__(
        self,
        stream: RuntimeEventStream,
        command: GameplayCommand,
        *,
        autoplay: bool = True,
        windows: NativeJudgeTiming | None = None,
    ) -> None:
        self.stream = stream
        self.command = command
        self.autoplay = bool(autoplay)
        self.time_ms = 0.0
        self.runtime_modifier = stream.modifier_for_launch_speed(command.speed)
        self.windows = windows or NativeJudgeTiming.from_modifier(self.runtime_modifier)
        self._selected_speed = float(self.runtime_modifier.speed)
        self._speed_state = self._new_speed_state(0.0)
        self._speed_block_index = self._block_index_at(0.0)
        self._draw_step_accumulator_ms = 0.0
        self._random_velocity_seed = stream.route.seed or 0
        self._random_velocity_rng = random.Random(self._random_velocity_seed)
        self._gauge = RuntimeGauge.from_modifier(
            self.runtime_modifier,
            columns=stream.columns,
        )
        self._bank_combos = [0, 0, 0, 0]
        self._bank_max_combos = [0, 0, 0, 0]
        self.stats = GameplayStats(gauge=self._gauge.life)
        self.judgments: dict[EventKey, Judgment] = {}
        self.judged_at_ms: dict[EventKey, float] = {}
        self.judgment_history: list[tuple[float, PreviewEvent]] = []
        self.step_effect_history: list[StepEffect] = []
        self.last_judgment: Judgment | None = None
        self.last_error_ms: float | None = None
        self.pressed_lanes: set[int] = set()
        self._pressed_since: dict[int, float] = {}
        self._errors: dict[EventKey, float | None] = {}
        groups: dict[GroupKey, list[PreviewEvent]] = defaultdict(list)
        for event in stream.events:
            if self.is_judged_note(event):
                groups[self.group_key(event)].append(event)
        self._groups = {key: tuple(events) for key, events in groups.items()}
        self._resolved_groups: set[GroupKey] = set()
        self._event_cursor = 0
        self._miss_cursor = 0

    @property
    def selected_speed(self) -> float:
        """Current explicit user-selected speed, separate from speed modes."""
        return self._selected_speed

    @property
    def high_speed(self) -> float:
        """Current displayed pHighSpeed after block speed and SpeedProc."""
        return self._speed_state.high_speed

    @property
    def block_speed(self) -> float:
        return self._speed_state.block_speed

    @property
    def mode_speed(self) -> float:
        return self._speed_state.mode_speed

    @property
    def speed_mode(self) -> SpeedMode:
        """Resolve Header mode plus sequential COMMAND S/E overrides."""

        mode = self.runtime_modifier.speed_mode
        for character in self.command.raw:
            if character == "s":
                mode = SpeedMode.RANDOM_VELOCITY
            elif character == "e":
                mode = SpeedMode.EARTHWORM
        return mode

    @property
    def gauge_limit(self) -> int:
        return self._gauge.limit

    @property
    def gauge_display_max(self) -> int:
        return self._gauge.display_max

    @property
    def gauge_factor(self) -> int:
        return self._gauge.factor

    def _block_index_at(self, time_ms: float) -> int:
        timing = self.stream.native_timing
        if timing is None or not timing.blocks:
            return 0
        return timing.get_block(time_ms)

    def _block_speed_at(self, time_ms: float) -> float:
        return self.stream.speed_factor_at(time_ms)

    def _new_speed_state(self, time_ms: float) -> RuntimeSpeedState:
        return RuntimeSpeedState.initialized(
            self._selected_speed,
            self._block_speed_at(time_ms),
        )

    def _apply_speed_mode(self, time_ms: float, block_index: int) -> None:
        timing = self.stream.native_timing
        if timing is None or not timing.blocks:
            return
        mode = self.speed_mode
        div = timing.blocks[block_index]
        if mode is SpeedMode.EARTHWORM:
            self._speed_state.set_speed(
                earthworm_user_speed(time_ms, div.bpm, div.beat_split)
            )
            return
        if mode is not SpeedMode.RANDOM_VELOCITY:
            return

        state = timing.state_at(time_ms)
        if not random_velocity_triggers(state.line):
            return

        # DrawStep rerolls on every update while the current line satisfies the
        # exact Line % 48 gate. The cadence, gate and signed %4+1 conversion are
        # source-exact; only Unity's RNG stream remains approximated here.
        random_value = self._random_velocity_rng.randrange(0, 0x7FFFFFFF)
        self._speed_state.set_speed(random_velocity_user_speed(random_value))

    def _draw_step_speed_tick(self, time_ms: float) -> None:
        """Project one PUMPPlayer.DrawStep / SpeedProc cadence tick."""

        timing = self.stream.native_timing
        if timing is None or not timing.blocks:
            self._speed_state.advance(DRAW_STEP_INTERVAL_MS)
            return

        block_index = timing.get_block(time_ms)
        block_speed = timing.block_speed_at(time_ms)
        div = timing.blocks[block_index]
        block_changed = block_index != self._speed_block_index
        mode = self.speed_mode

        # Non-Smooth block-change snapping in DrawStep is gated to Static mode.
        # Smooth writes the interpolated block speed and pHighSpeed directly.
        if div.is_smooth:
            self._speed_state.set_block_speed(block_speed, snap=True)
        else:
            self._speed_state.set_block_speed(
                block_speed,
                snap=block_changed and mode is SpeedMode.STATIC,
            )

        self._apply_speed_mode(time_ms, block_index)
        if not div.is_smooth:
            self._speed_state.advance(DRAW_STEP_INTERVAL_MS)
        self._speed_block_index = block_index

    def _advance_speed(self, previous_time: float, time_ms: float) -> None:
        if time_ms <= previous_time:
            return
        timing = self.stream.native_timing
        if timing is None or not timing.blocks:
            self._speed_state.advance(time_ms - previous_time)
            return

        delta_ms = float(time_ms) - float(previous_time)
        interval = float(DRAW_STEP_INTERVAL_MS)
        accumulated = self._draw_step_accumulator_ms + delta_ms
        next_tick = float(previous_time) + (
            interval - self._draw_step_accumulator_ms
        )
        epsilon = 1e-9

        while accumulated + epsilon >= interval:
            self._draw_step_speed_tick(next_tick)
            accumulated -= interval
            next_tick += interval

        self._draw_step_accumulator_ms = max(0.0, accumulated)

    @staticmethod
    def event_key(event: PreviewEvent) -> EventKey:
        return event.split_id, event.block_id, event.row_index, event.lane

    def group_key(self, event: PreviewEvent) -> GroupKey:
        # JudgeByNote is one JudgeUnit per cell. Rush/roll longs are also routed
        # through JudgeNote rather than the aggregate JudgeLine path.
        judge_note_lane = self.runtime_modifier.judge_by_note or (
            bool(event.long_kind) and not event.no_rush
        )
        lane_key = event.lane if judge_note_lane else -1
        return (
            event.split_id,
            event.block_id,
            event.row_index,
            event.bank,
            lane_key,
        )

    @staticmethod
    def is_judged_note(event: PreviewEvent) -> bool:
        return event.base_note_type == 0x03 and not event.no_judge

    @staticmethod
    def starts_pad_press(event: PreviewEvent) -> bool:
        return (
            event.note_type in (0x3, 0x7)
            and event.base_note_type == 0x03
            and not event.no_judge
        )

    def reset(self, time_ms: float = 0.0) -> None:
        self.time_ms = float(time_ms)
        self._speed_state = self._new_speed_state(self.time_ms)
        self._speed_block_index = self._block_index_at(self.time_ms)
        self._draw_step_accumulator_ms = 0.0
        self._random_velocity_rng = random.Random(self._random_velocity_seed)
        self._gauge = RuntimeGauge.from_modifier(
            self.runtime_modifier,
            columns=self.stream.columns,
        )
        self._bank_combos[:] = (0, 0, 0, 0)
        self._bank_max_combos[:] = (0, 0, 0, 0)
        self.stats = GameplayStats(gauge=self._gauge.life)
        self.judgments.clear()
        self.judged_at_ms.clear()
        self.judgment_history.clear()
        self.step_effect_history.clear()
        self.last_judgment = None
        self.last_error_ms = None
        self.pressed_lanes.clear()
        self._pressed_since.clear()
        self._errors.clear()
        self._resolved_groups.clear()
        self._event_cursor = 0
        self._miss_cursor = 0

    def _emit_step_effect(self, event: PreviewEvent, time_ms: float) -> None:
        self.step_effect_history.append(
            StepEffect(float(time_ms), event.lane, event.raw[2])
        )
        cutoff = float(time_ms) - 300.0
        if len(self.step_effect_history) > 64:
            self.step_effect_history[:] = [
                effect
                for effect in self.step_effect_history
                if effect.time_ms >= cutoff
            ]

    def _project_group(
        self,
        events: tuple[PreviewEvent, ...],
        judgment: Judgment,
    ) -> JudgeUnitProjection | None:
        grade = _JUDGMENT_RANK[judgment]
        input_grade = -1 if judgment is Judgment.MISS else grade
        representative = events[0]

        is_rush = bool(representative.long_kind) and not representative.no_rush
        if self.runtime_modifier.judge_by_note or is_rush:
            decision = judge_note_decision(
                representative,
                input_grade,
                judge_by_note=self.runtime_modifier.judge_by_note,
            )
            if not decision.routed_to_judge_unit and not decision.forced_miss:
                return None
            return project_judge_unit(
                bank=representative.bank,
                grade=input_grade,
                visible=decision.visible,
                no_miss=decision.no_miss,
                note_count=decision.note_count,
                long_note_count=decision.long_note_count,
                alt_skin_count=decision.alt_skin_count,
                alt_skin_score_factor=self.runtime_modifier.alt_skin_score_factor,
            )

        summary = summarize_judge_line(events, representative.bank)
        if not summary.has_judge_unit:
            return None
        return project_judge_unit(
            bank=summary.bank,
            grade=input_grade,
            visible=summary.visible,
            no_miss=summary.no_miss,
            note_count=summary.note_count,
            long_note_count=summary.long_note_count,
            alt_skin_count=summary.alt_skin_count,
            alt_skin_score_factor=self.runtime_modifier.alt_skin_score_factor,
            play_sound=summary.play_sound,
        )

    def _increment_combo(self, bank: int) -> int:
        self._bank_combos[bank] += 1
        self._bank_max_combos[bank] = max(
            self._bank_max_combos[bank], self._bank_combos[bank]
        )
        if bank != 3:
            self._bank_combos[3] += 1
            self._bank_max_combos[3] = max(
                self._bank_max_combos[3], self._bank_combos[3]
            )
        return self._bank_combos[bank]

    def _clear_combo(self, bank: int) -> None:
        self._bank_combos[bank] = 0
        self._bank_combos[3] = 0

    def _apply_native_postprocess(
        self,
        projection: JudgeUnitProjection,
    ) -> None:
        """Apply JudgeStep_PostProcess/GetScore plus JudgeUnit's HPBar update."""

        total_count = projection.total_note_count
        if total_count <= 0:
            return
        grade = projection.judgment

        # JudgeUnit consumes a negative grade as Miss, but bNoMiss bypasses the
        # gauge and JudgeStep_PostProcess path entirely.
        if grade == 4 and projection.no_miss:
            return

        bank = projection.bank
        if grade <= 1:
            score_combo = self._increment_combo(bank)
        elif grade == 2:
            # Native Good neither increments nor clears combo.
            score_combo = self._bank_combos[bank]
        else:
            self._clear_combo(bank)
            score_combo = self._bank_combos[bank]

        score_delta = native_score_delta(
            grade,
            combo=score_combo,
            note_count=total_count,
            ordinary_note_miss=projection.note_count != 0,
            alt_skin_factor=projection.alt_skin_factor,
        )
        score = add_score_floor_zero(self.stats.score, score_delta)
        self._gauge.apply_grade(grade)

        current = self.stats
        self.stats = GameplayStats(
            perfect=current.perfect + (grade == 0),
            great=current.great + (grade == 1),
            good=current.good + (grade == 2),
            bad=current.bad + (grade == 3),
            miss=current.miss + (grade == 4),
            combo=self._bank_combos[3],
            max_combo=max(current.max_combo, self._bank_max_combos[3]),
            score=score,
            gauge=self._gauge.life,
        )

    def _finalize_group(self, group_key: GroupKey) -> None:
        if group_key in self._resolved_groups:
            return
        events = self._groups[group_key]
        if any(self.event_key(event) not in self.judgments for event in events):
            return
        judgment = max(
            (self.judgments[self.event_key(event)] for event in events),
            key=_JUDGMENT_RANK.__getitem__,
        )
        representative = events[0]
        judged_at = max(
            self.judged_at_ms[self.event_key(event)] for event in events
        )
        worst_errors = [
            self._errors[self.event_key(event)]
            for event in events
            if self.judgments[self.event_key(event)] is judgment
            and self._errors[self.event_key(event)] is not None
        ]
        self._resolved_groups.add(group_key)
        self.judgment_history.append((judged_at, representative))
        self.last_judgment = judgment
        self.last_error_ms = max(worst_errors, key=abs) if worst_errors else None
        projection = self._project_group(events, judgment)
        if projection is not None:
            self._apply_native_postprocess(projection)

    def _record_event(
        self,
        event: PreviewEvent,
        judgment: Judgment,
        error_ms: float | None,
        *,
        judged_at_ms: float | None = None,
    ) -> None:
        key = self.event_key(event)
        if key in self.judgments:
            return
        self.judgments[key] = judgment
        judged_at = self.time_ms if judged_at_ms is None else float(judged_at_ms)
        self.judged_at_ms[key] = judged_at
        self._errors[key] = error_ms
        self._finalize_group(self.group_key(event))

    def _held_at(self, event: PreviewEvent) -> bool:
        pressed_at = self._pressed_since.get(event.lane)
        return pressed_at is not None and pressed_at <= event.time_ms

    def advance(self, time_ms: float) -> None:
        time_ms = float(time_ms)
        if time_ms < self.time_ms:
            self.reset()
        previous_time = self.time_ms
        self._advance_speed(previous_time, time_ms)
        self.time_ms = time_ms
        events = self.stream.events

        while self._event_cursor < len(events):
            event = events[self._event_cursor]
            if event.time_ms > time_ms:
                break
            self._event_cursor += 1
            if not self.is_judged_note(event):
                continue
            if self.autoplay:
                self._record_event(
                    event,
                    Judgment.PERFECT,
                    0.0,
                    judged_at_ms=event.time_ms,
                )
                if (
                    self.starts_pad_press(event)
                    and event.time_ms > previous_time
                    and event.time_ms >= time_ms - 250.0
                ):
                    self._emit_step_effect(event, event.time_ms)
            elif event.note_type in (0xB, 0xF) and self._held_at(event):
                self._record_event(
                    event,
                    Judgment.PERFECT,
                    0.0,
                    judged_at_ms=event.time_ms,
                )

        miss_cutoff = time_ms - self.windows.late_limit_ms
        while self._miss_cursor < len(events):
            event = events[self._miss_cursor]
            if event.time_ms >= miss_cutoff:
                break
            self._miss_cursor += 1
            if self.is_judged_note(event):
                self._record_event(event, Judgment.MISS, None)

    def press(self, lane: int, time_ms: float | None = None) -> Judgment | None:
        moment = self.time_ms if time_ms is None else float(time_ms)
        self.advance(moment)
        self.pressed_lanes.add(lane)
        self._pressed_since[lane] = moment
        candidates = [
            event
            for event in self.stream.events
            if event.lane == lane
            and self.starts_pad_press(event)
            and self.event_key(event) not in self.judgments
            and self.windows.can_judge(moment - event.time_ms)
        ]
        if not candidates:
            self.step_effect_history.append(StepEffect(moment, lane, 0))
            return None
        event = min(candidates, key=lambda item: abs(item.time_ms - moment))
        self._emit_step_effect(event, moment)
        error = moment - event.time_ms
        grade = self.windows.grade_for_error(error)
        if grade is None:
            return None
        judgment = _GRADE_JUDGMENT[grade]
        self._record_event(event, judgment, error)
        return judgment

    def release(self, lane: int) -> None:
        self.pressed_lanes.discard(lane)
        self._pressed_since.pop(lane, None)

    def toggle_autoplay(self) -> bool:
        self.autoplay = not self.autoplay
        return self.autoplay

    def select_speed(self, digit: int) -> None:
        if not 1 <= digit <= 9:
            raise ValueError("speed digit must be between 1 and 9")
        self.command = self.command.with_speed(digit)
        self._selected_speed = float(digit)
        self.runtime_modifier = replace(self.runtime_modifier, speed=self._selected_speed)
        self._speed_state.set_speed(self._selected_speed)