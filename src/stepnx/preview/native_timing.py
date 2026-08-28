from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from math import isfinite

from stepnx.preview.routes import ResolvedRoute
from stepnx.preview.snapshot import PreviewSnapshot


DIV_FLAG_SMOOTH = 0x01
DIV_FLAG_SKIP = 0x02


@dataclass(frozen=True, slots=True)
class NativeDivTiming:
    """Runtime timing values produced by the native NX20 StepLoader.

    Names intentionally mirror the R!SE IL2CPP types where useful.  In the
    loaded Div, the raw BPM slot is replaced by msPerLine.  bSkip therefore
    means msPerLine == 0 while BeatPerLine and nLine remain fully meaningful.
    """

    split_id: int
    block_id: int
    index: int
    start_time_ms: float
    beat_per_line: float
    ms_per_line: float
    gap_beats: float
    n_line: int
    raw_speed: float
    flags: int

    @property
    def end_time_ms(self) -> float:
        return self.start_time_ms + self.n_line * self.ms_per_line

    @property
    def length_beats(self) -> float:
        return self.n_line * self.beat_per_line

    @property
    def is_skip(self) -> bool:
        return bool(self.flags & DIV_FLAG_SKIP)

    @property
    def is_smooth(self) -> bool:
        return bool(self.flags & DIV_FLAG_SMOOTH)


@dataclass(frozen=True, slots=True)
class NativeTimingState:
    block_index: int
    line: int
    beat: float


@dataclass(frozen=True, slots=True)
class NativeTimingProjection:
    """Source-faithful projection of Step/PlayBase Block-Line timing.

    This ports the behavior recovered from R!SE's StepLoader, Step.GetBlock,
    Step.SetCurrentTime and PlayBase.GetBlockBeat.  It deliberately keeps
    judgment time and visual beat distance as separate axes.
    """

    blocks: tuple[NativeDivTiming, ...]
    sum_line_sec: tuple[float, ...]
    sum_line_gap: tuple[float, ...]
    end_times: tuple[float, ...]
    monotonic_end_times: bool

    def get_block(self, time_ms: float, guess: int = 0) -> int:
        """Port Step.GetBlock(ms, guess).

        The binary-search fast path is equivalent when Div end times are
        nondecreasing.  A literal walk is retained for unusual documents.
        """

        if not self.blocks:
            return 0
        if self.monotonic_end_times:
            return min(len(self.blocks) - 1, bisect_right(self.end_times, time_ms))

        count = len(self.blocks)
        index = guess if 0 <= guess < count else 0
        if self.blocks[index].end_time_ms <= time_ms:
            while True:
                index += 1
                if index >= count:
                    return count - 1
                if self.blocks[index].end_time_ms > time_ms:
                    return index
        while index > 0 and self.blocks[index - 1].end_time_ms > time_ms:
            index -= 1
        return index

    def get_line(self, time_ms: float, block_index: int) -> int:
        div = self.blocks[block_index]
        delta = time_ms - div.start_time_ms
        if delta < 0.0 or div.ms_per_line == 0.0:
            return 0
        return int(delta / div.ms_per_line)

    def state_at(self, time_ms: float) -> NativeTimingState:
        block_index = self.get_block(time_ms)
        div = self.blocks[block_index]
        line = self.get_line(time_ms, block_index)

        # PlayBase.Update after Step.SetCurrentTime.  This looks unusual for
        # gap-free Divs, but it is the native formula and must not be replaced
        # by a reconstructed continuous beat clock.
        beat = line * div.beat_per_line
        delta = time_ms - div.start_time_ms
        if div.ms_per_line != 0.0 and (delta <= 0.0 or div.gap_beats != 0.0):
            beat -= delta * div.beat_per_line / div.ms_per_line
        return NativeTimingState(block_index, line, beat)

    def judgment_time(self, block_index: int, line: int) -> float:
        div = self.blocks[block_index]
        # This is the exact per-line time used by Step.Judge and by
        # LineBase.CreateSplits.  Every row of bSkip shares msStart because
        # StepLoader sets msPerLine to zero.
        return div.start_time_ms + line * div.ms_per_line

    def block_start_position(self, block_index: int) -> float:
        """Absolute coordinate equivalent for current/future GetBlockBeat.

        The native private overload uses sumLineSec[target-1] plus the gaps
        through the target Div.  This coordinate makes the existing viewport's
        event.position - current_position calculation identical to
        GetBlockBeat for the current block and blocks ahead.
        """

        sec_before = self.sum_line_sec[block_index - 1] if block_index > 0 else 0.0
        return sec_before + self.sum_line_gap[block_index]

    def line_position(self, block_index: int, line: int) -> float:
        div = self.blocks[block_index]
        return self.block_start_position(block_index) + line * div.beat_per_line

    def current_position_from_state(self, state: NativeTimingState) -> float:
        div = self.blocks[state.block_index]
        return (
            self.block_start_position(state.block_index)
            + state.line * div.beat_per_line
            - state.beat
        )

    def current_position(self, time_ms: float) -> float:
        return self.current_position_from_state(self.state_at(time_ms))

    def block_beat_from_state(
        self,
        target_block: int,
        target_line: int,
        state: NativeTimingState,
    ) -> float:
        """Port PlayBase.GetBlockBeat(block, line, Player.Beat)."""

        current_block = state.block_index
        current_line = state.line
        current = self.blocks[current_block]
        target = self.blocks[target_block]

        # In the native control flow, equality jumps directly to this path
        # before the common current-line subtraction used by the < and > cases.
        if target_block == current_block:
            return (
                state.beat
                - current_line * current.beat_per_line
                + target_line * target.beat_per_line
            )

        value = state.beat - current_line * current.beat_per_line

        if target_block < current_block:
            current_prev_sec = (
                self.sum_line_sec[current_block - 1] if current_block > 0 else 0.0
            )
            if target_block > 0:
                target_prev_sec = self.sum_line_sec[target_block - 1]
                gap_diff = (
                    self.sum_line_gap[current_block - 1]
                    - self.sum_line_gap[target_block - 1]
                )
            else:
                # This zero-target special case is present in the native code.
                target_prev_sec = 0.0
                gap_diff = 0.0
            value -= current.gap_beats
            value -= current_prev_sec - target_prev_sec
            value -= gap_diff
            return value + target_line * target.beat_per_line

        # target_block > current_block.  sum_line_sec[current_block] includes
        # the complete current Div, so the subtraction below contains only the
        # intervening Divs.  sum_line_gap[target] - sum_line_gap[current]
        # contains the gaps from the next Div through the target Div.
        line_sec = (
            self.sum_line_sec[target_block - 1]
            - self.sum_line_sec[current_block]
        )
        gaps = self.sum_line_gap[target_block] - self.sum_line_gap[current_block]
        value += current.length_beats
        value += line_sec
        value += gaps
        return value + target_line * target.beat_per_line

    def block_beat(self, target_block: int, target_line: int, time_ms: float) -> float:
        return self.block_beat_from_state(
            target_block, target_line, self.state_at(time_ms)
        )


def build_native_timing(
    snapshot: PreviewSnapshot, route: ResolvedRoute
) -> NativeTimingProjection:
    blocks: list[NativeDivTiming] = []
    sum_line_sec: list[float] = []
    sum_line_gap: list[float] = []
    sec_total = 0.0
    gap_total = 0.0

    selected = [
        (split, split.block(route.block_id(split.stable_id)))
        for split in snapshot.splits
    ]
    for index, (split, block) in enumerate(selected):
        if block.bpm <= 0.0 or block.beat_split <= 0:
            raise ValueError(
                f"Block {block.stable_id} needs positive BPM and Beat Split"
            )
        flags = int(block.smooth_speed) & 0xFF
        is_skip = bool(flags & DIV_FLAG_SKIP)
        ms_per_line = (
            0.0
            if is_skip
            else 60_000.0 / (block.bpm * block.beat_split)
        )
        beat_per_line = (
            block.scroll
            if isfinite(block.scroll)
            else 1.0 / block.beat_split
        )

        # StepLoader computes Div.Gap only when msPerLine is positive and the
        # raw Speed field is positive.  Negative Speed and bSkip both yield 0.
        if (
            ms_per_line > 0.0
            and block.speed_or_freeze > 0.0
            and isfinite(block.offset_or_delay_ms)
        ):
            gap_beats = block.offset_or_delay_ms / (
                block.beat_split * ms_per_line
            )
        else:
            gap_beats = 0.0

        div = NativeDivTiming(
            split.stable_id,
            block.stable_id,
            index,
            block.start_time_ms,
            beat_per_line,
            ms_per_line,
            gap_beats,
            len(block.rows),
            block.speed_or_freeze,
            flags,
        )
        blocks.append(div)
        sec_total += div.length_beats
        gap_total += div.gap_beats
        sum_line_sec.append(sec_total)
        sum_line_gap.append(gap_total)

    end_times = tuple(div.end_time_ms for div in blocks)
    monotonic = all(
        end_times[index] <= end_times[index + 1]
        for index in range(len(end_times) - 1)
    )
    return NativeTimingProjection(
        tuple(blocks),
        tuple(sum_line_sec),
        tuple(sum_line_gap),
        end_times,
        monotonic,
    )
