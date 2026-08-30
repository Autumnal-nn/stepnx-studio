from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from math import trunc

from stepnx.preview.modifiers import EffectiveModifier


class HPBarType(IntEnum):
    SINGLE = 0
    HALF_DOUBLE = 1
    DOUBLE = 2


@dataclass(frozen=True, slots=True)
class GaugeFactorPreset:
    minimum: int
    maximum: int
    miss: int
    initial: int


GAUGE_DEFAULT = 500
GAUGE_LIMIT_DEFAULT = 1000
GAUGE_DISPLAY_MAX_DEFAULT = 1000
LEVEL_LIMIT = 50

_GAUGE_FACTORS = {
    HPBarType.SINGLE: GaugeFactorPreset(200, 1000, -700, 500),
    HPBarType.HALF_DOUBLE: GaugeFactorPreset(0, 800, -700, 100),
    HPBarType.DOUBLE: GaugeFactorPreset(100, 900, -700, 300),
}


@dataclass(slots=True)
class RuntimeGauge:
    """R!SE HPBar state used by PUMPPlayer.JudgeUnit.

    Header IDs 80/81/82 are applied after ResetHP and the level-derived Limit,
    exactly where ApplyStepParamToMod writes HPBar.Limit/DispMax/Life.
    """

    bar_type: HPBarType
    life: int
    limit: int
    display_max: int
    factor_min: int
    factor_max: int
    miss_factor: int
    factor: int
    accumulated_delta: int = 0

    @classmethod
    def from_modifier(
        cls,
        modifier: EffectiveModifier,
        *,
        columns: int,
    ) -> RuntimeGauge:
        # The preview only knows the resolved NX field width, not the original
        # PUMP.PlayType enum. These are the three native playable field widths.
        if columns == 5:
            bar_type = HPBarType.SINGLE
        elif columns == 10:
            bar_type = HPBarType.DOUBLE
        else:
            # Native ResetHP maps an invalid type to HalfDouble. Six-column HD
            # lands here directly; unusual widths keep that source fallback.
            bar_type = HPBarType.HALF_DOUBLE

        preset = _GAUGE_FACTORS[bar_type]
        level = 0 if modifier.level is None else int(modifier.level)
        capped_level = min(level, LEVEL_LIMIT)
        limit = GAUGE_LIMIT_DEFAULT + 3 * capped_level * capped_level
        display_max = GAUGE_DISPLAY_MAX_DEFAULT
        life = GAUGE_DEFAULT

        if modifier.gauge_max is not None:
            limit = int(modifier.gauge_max)
        if modifier.gauge_display_max is not None:
            display_max = int(modifier.gauge_display_max)
        if modifier.gauge_initial_value is not None:
            # ApplyStepParamToMod writes the field directly. Do not eagerly
            # clamp an authored override; HPBar.Add performs the later clamp.
            life = int(modifier.gauge_initial_value)

        return cls(
            bar_type=bar_type,
            life=life,
            limit=limit,
            display_max=display_max,
            factor_min=preset.minimum,
            factor_max=preset.maximum,
            miss_factor=preset.miss,
            factor=preset.initial,
        )

    def _clamp_factor(self) -> None:
        self.factor = min(self.factor_max, max(self.factor_min, self.factor))

    def add(self, delta: int) -> None:
        """Port normal-mode HPBar.Add and its [0, Limit] clamp."""

        self.life += int(delta)
        self.life = min(self.limit, max(0, self.life))
        self.accumulated_delta += int(delta)

    def delta_for_grade(self, grade: int) -> int:
        """Return JudgeUnit's HP delta and update the dynamic factor state."""

        if grade == 0:  # Perfect
            delta_float = (12 * self.factor) / 1000.0
            self.factor += 20
        elif grade == 1:  # Great
            delta_float = (10 * self.factor) / 1000.0
            self.factor += 16
        elif grade == 2:  # Good
            delta_float = 0.0
        elif grade == 3:  # Bad
            delta_float = -50.0
        elif grade == 4:  # Miss
            life_base = min(self.life, 1000)
            proportional = trunc((-500 * life_base) / 2000.0)
            delta_float = proportional - 20.0
            self.factor += self.miss_factor
        else:
            return 0

        self._clamp_factor()
        return trunc(delta_float)

    def apply_grade(self, grade: int) -> int:
        delta = self.delta_for_grade(grade)
        self.add(delta)
        return delta
