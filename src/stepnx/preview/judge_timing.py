from __future__ import annotations

from dataclasses import dataclass
from math import trunc

from stepnx.preview.modifiers import EffectiveModifier


JUDGE_FRAME_MS = 16.66666603088379
DEFAULT_JUDGE_DELAY_FRAMES = 2.5
DEFAULT_JUDGE_GRADES = 4


@dataclass(frozen=True, slots=True)
class NativeJudgeTiming:
    """R!SE Step.Judge timing projected from PUMPPlayer.SetJudgeTiming.

    The native engine does not use one symmetric absolute-error table. Early
    input is measured directly from the note time, while late input first
    consumes ``Delay`` before Step.GetGrade sees the remaining error.
    """

    perfect_ms: float
    interval_ms: float
    delay_ms: float
    n_grade: int = DEFAULT_JUDGE_GRADES

    @classmethod
    def from_modifier(
        cls,
        modifier: EffectiveModifier,
        *,
        delay_frames: float = DEFAULT_JUDGE_DELAY_FRAMES,
    ) -> NativeJudgeTiming:
        frame_ms = JUDGE_FRAME_MS
        if modifier.speed_boost > 0.0:
            # PUMPPlayer.SetJudgeTiming scales the whole frame unit when a
            # CommonModifier.SpeedBoost producer has already populated it.
            frame_ms *= modifier.speed_boost
        return cls(
            perfect_ms=frame_ms * modifier.perfect_frame,
            interval_ms=frame_ms * modifier.interval_frame,
            delay_ms=frame_ms * delay_frames,
            n_grade=DEFAULT_JUDGE_GRADES,
        )

    @property
    def start_ms(self) -> float:
        """Step.JudgeTiming.Start, relative to the note time."""

        return -(
            self.perfect_ms
            + (self.n_grade - 1) * self.interval_ms
            + self.delay_ms
        )

    @property
    def end_ms(self) -> float:
        """Step.JudgeTiming.End before late Delay is consumed."""

        return self.perfect_ms + (self.n_grade - 1) * self.interval_ms

    @property
    def early_limit_ms(self) -> float:
        return self.end_ms

    @property
    def late_limit_ms(self) -> float:
        return self.end_ms + self.delay_ms

    # Compatibility names retained for callers that used the old preview
    # JudgmentWindows object as an early/symmetric boundary table.
    @property
    def great_ms(self) -> float:
        return self.perfect_ms + self.interval_ms

    @property
    def good_ms(self) -> float:
        return self.perfect_ms + 2.0 * self.interval_ms

    @property
    def bad_ms(self) -> float:
        return self.end_ms

    def can_judge(self, error_ms: float) -> bool:
        """Return whether Step.Judge still considers this note for input."""

        error = float(error_ms)
        return -self.early_limit_ms <= error <= self.late_limit_ms

    def transformed_ms(self, error_ms: float) -> float:
        """Port Step.Judge's asymmetric time passed into Step.GetGrade."""

        error = float(error_ms)
        if error <= 0.0:
            return -error
        return max(0.0, error - self.delay_ms)

    def grade_for_error(self, error_ms: float) -> int | None:
        """Return Perfect=0 .. Bad=3, or None once the note is out of range."""

        if not self.can_judge(error_ms):
            return None
        value = self.transformed_ms(error_ms) - self.perfect_ms
        if value <= 0.0:
            return 0
        # Step.GetGrade uses cvttss2si semantics here. All normal timing values
        # are positive, so Python truncation matches native truncation-to-zero.
        grade = trunc(value / self.interval_ms + 1.0)
        if grade >= self.n_grade:
            grade = self.n_grade - 1
        return grade
