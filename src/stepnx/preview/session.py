from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from enum import Enum

from stepnx.preview.commands import GameplayCommand
from stepnx.preview.events import PreviewEvent, RuntimeEventStream
from stepnx.preview.speed import RuntimeSpeedState


class Judgment(str, Enum):
    PERFECT = "PERFECT"
    GREAT = "GREAT"
    GOOD = "GOOD"
    BAD = "BAD"
    MISS = "MISS"


@dataclass(frozen=True, slots=True)
class JudgmentWindows:
    perfect_ms: float = 41.67
    great_ms: float = 83.33
    good_ms: float = 125.0
    bad_ms: float = 166.67

    def classify(self, error_ms: float) -> Judgment | None:
        error = abs(error_ms)
        if error <= self.perfect_ms:
            return Judgment.PERFECT
        if error <= self.great_ms:
            return Judgment.GREAT
        if error <= self.good_ms:
            return Judgment.GOOD
        if error <= self.bad_ms:
            return Judgment.BAD
        return None


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


_SCORES = {
    Judgment.PERFECT: 1000,
    Judgment.GREAT: 800,
    Judgment.GOOD: 500,
    Judgment.BAD: 200,
    Judgment.MISS: 0,
}
_GAUGE = {
    Judgment.PERFECT: 8,
    Judgment.GREAT: 4,
    Judgment.GOOD: 1,
    Judgment.BAD: -20,
    Judgment.MISS: -40,
}
_JUDGMENT_RANK = {
    Judgment.PERFECT: 0,
    Judgment.GREAT: 1,
    Judgment.GOOD: 2,
    Judgment.BAD: 3,
    Judgment.MISS: 4,
}

EventKey = tuple[int, int, int, int]
RowKey = tuple[int, int, int]


class GameplaySession:
    """Mutable runtime state kept strictly outside the canonical document.

    NXA normally resolves one judgment per encoded row. Individual cells are
    still tracked so manual chords can arrive on separate key events, but the
    score, combo, and visible judgment advance only after the complete row has
    resolved. STEPFX is deliberately independent: it represents a physical or
    autoplay pad press, not a judgment record.

    R!SE scroll speed is also stateful. The user/high-speed option, active Div
    block speed and displayed pHighSpeed are kept separately so SetSpeed and
    SpeedProc no longer collapse into one renderer multiplication.
    """

    def __init__(
        self,
        stream: RuntimeEventStream,
        command: GameplayCommand,
        *,
        autoplay: bool = True,
        windows: JudgmentWindows | None = None,
    ) -> None:
        self.stream = stream
        self.command = command
        self.autoplay = bool(autoplay)
        self.windows = windows or JudgmentWindows()
        self.time_ms = 0.0
        self.runtime_modifier = stream.modifier_for_launch_speed(command.speed)
        self._selected_speed = float(self.runtime_modifier.speed)
        self._speed_state = self._new_speed_state(0.0)
        self._speed_block_index = self._block_index_at(0.0)
        self.stats = GameplayStats()
        self.judgments: dict[EventKey, Judgment] = {}
        self.judged_at_ms: dict[EventKey, float] = {}
        self.judgment_history: list[tuple[float, PreviewEvent]] = []
        self.step_effect_history: list[StepEffect] = []
        self.last_judgment: Judgment | None = None
        self.last_error_ms: float | None = None
        self.pressed_lanes: set[int] = set()
        self._pressed_since: dict[int, float] = {}
        self._errors: dict[EventKey, float | None] = {}
        groups: dict[RowKey, list[PreviewEvent]] = defaultdict(list)
        for event in stream.events:
            if self.is_judged_note(event):
                groups[self.row_key(event)].append(event)
        self._groups = {key: tuple(events) for key, events in groups.items()}
        self._resolved_groups: set[RowKey] = set()
        self._event_cursor = 0
        self._miss_cursor = 0

    @property
    def selected_speed(self) -> float:
        """Current user/runtime speed target (_modeSpeedExt)."""

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

    def _advance_speed(self, previous_time: float, time_ms: float) -> None:
        if time_ms <= previous_time:
            return
        timing = self.stream.native_timing
        if timing is None or not timing.blocks:
            self._speed_state.advance(time_ms - previous_time)
            return

        block_index = timing.get_block(time_ms)
        block_speed = timing.block_speed_at(time_ms)
        div = timing.blocks[block_index]
        block_changed = block_index != self._speed_block_index

        # DrawStep owns Div speed changes. A block transition and every Smooth
        # update immediately recompute the displayed high speed from the active
        # block factor instead of feeding that change through SpeedProc.
        if block_changed or div.is_smooth:
            self._speed_state.set_block_speed(block_speed, snap=True)
        else:
            self._speed_state.set_block_speed(block_speed, snap=False)
            self._speed_state.advance(time_ms - previous_time)
        self._speed_block_index = block_index

    @staticmethod
    def event_key(event: PreviewEvent) -> EventKey:
        return event.split_id, event.block_id, event.row_index, event.lane

    @staticmethod
    def row_key(event: PreviewEvent) -> RowKey:
        return event.split_id, event.block_id, event.row_index

    @staticmethod
    def is_judged_note(event: PreviewEvent) -> bool:
        return event.note_type in (0x3, 0x7, 0xB, 0xF) and event.registers

    @staticmethod
    def starts_pad_press(event: PreviewEvent) -> bool:
        return event.note_type in (0x3, 0x7) and event.registers

    def reset(self, time_ms: float = 0.0) -> None:
        self.time_ms = float(time_ms)
        self._speed_state = self._new_speed_state(self.time_ms)
        self._speed_block_index = self._block_index_at(self.time_ms)
        self.stats = GameplayStats()
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

    def _update_stats(self, judgment: Judgment) -> None:
        current = self.stats
        combo = (
            current.combo + 1
            if judgment in (Judgment.PERFECT, Judgment.GREAT)
            else 0
        )
        self.stats = GameplayStats(
            perfect=current.perfect + (judgment is Judgment.PERFECT),
            great=current.great + (judgment is Judgment.GREAT),
            good=current.good + (judgment is Judgment.GOOD),
            bad=current.bad + (judgment is Judgment.BAD),
            miss=current.miss + (judgment is Judgment.MISS),
            combo=combo,
            max_combo=max(current.max_combo, combo),
            score=current.score + _SCORES[judgment],
            gauge=min(1000, max(0, current.gauge + _GAUGE[judgment])),
        )

    def _finalize_row(self, row_key: RowKey) -> None:
        if row_key in self._resolved_groups:
            return
        events = self._groups[row_key]
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
        self._resolved_groups.add(row_key)
        self.judgment_history.append((judged_at, representative))
        self._update_stats(judgment)
        self.last_judgment = judgment
        self.last_error_ms = max(worst_errors, key=abs) if worst_errors else None

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
        self._finalize_row(self.row_key(event))

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

        miss_cutoff = time_ms - self.windows.bad_ms
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
            and abs(event.time_ms - moment) <= self.windows.bad_ms
        ]
        if not candidates:
            self.step_effect_history.append(StepEffect(moment, lane, 0))
            return None
        event = min(candidates, key=lambda item: abs(item.time_ms - moment))
        self._emit_step_effect(event, moment)
        error = moment - event.time_ms
        judgment = self.windows.classify(error)
        if judgment is not None:
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
