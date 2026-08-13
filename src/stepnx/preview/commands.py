from __future__ import annotations

import random
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class GameplayCommand:
    raw: str
    speed: float
    vanish: bool = False
    nonstep: bool = False
    flash: bool = False
    freedom: bool = False
    mirror: bool = False
    randomize: bool = False
    upside_down: bool = False
    judge_reverse: bool = False
    deceleration: bool = False
    acceleration: bool = False
    exceed_mode: bool = False
    random_velocity: bool = False
    earthworm: bool = False
    unknown: tuple[str, ...] = ()

    @property
    def approximate_effects(self) -> tuple[str, ...]:
        """Return effects whose curves still need engine-capture calibration."""

        enabled = (
            ("V", self.vanish),
            ("D", self.deceleration),
            ("A", self.acceleration),
            ("X", self.exceed_mode),
            ("S", self.random_velocity),
            ("E", self.earthworm),
        )
        return tuple(flag for flag, active in enabled if active)

    @property
    def pending_effects(self) -> tuple[str, ...]:
        """Return parsed flags that are not yet projected by the simulator."""

        enabled = (
            ("U", self.upside_down),
        )
        return tuple(flag for flag, active in enabled if active)

    def with_speed(self, speed: int) -> GameplayCommand:
        if not 1 <= speed <= 9:
            raise ValueError("gameplay speed must be between 1x and 9x")
        return replace(self, speed=float(speed))

    def lane_map(self, columns: int, *, seed: int = 0) -> tuple[int, ...]:
        lanes = list(range(columns))
        if self.mirror:
            lanes.reverse()
        if self.upside_down:
            if columns == 5:
                lanes = [lanes[index] for index in (1, 0, 2, 4, 3)]
            else:
                lanes.reverse()
        if self.randomize:
            random.Random(seed).shuffle(lanes)
        return tuple(lanes)

    def note_opacity(
        self,
        visibility: int,
        *,
        distance: float,
        fade_distance: float,
        time_ms: float,
    ) -> float:
        """Combine chart visibility with proven global display commands."""

        if self.nonstep or visibility == 0:
            return 0.0
        span = max(1.0, float(fade_distance))
        normalized = max(0.0, float(distance)) / span
        if visibility == 1:  # Appear
            opacity = 1.0 - normalized
        elif visibility == 2:  # Vanish
            opacity = normalized
        else:  # Visible and unknown high-bit combinations
            opacity = 1.0
        if self.vanish:
            opacity = min(opacity, normalized)
        if self.flash and int(float(time_ms) // 100.0) % 2:
            opacity = 0.0
        return min(1.0, max(0.0, opacity))


_FLAGS = {
    "v": "vanish",
    "n": "nonstep",
    "w": "flash",
    "f": "freedom",
    "m": "mirror",
    "r": "randomize",
    "u": "upside_down",
    "j": "judge_reverse",
    "d": "deceleration",
    "a": "acceleration",
    "x": "exceed_mode",
    "s": "random_velocity",
    "e": "earthworm",
}


def parse_gameplay_command(value: str) -> GameplayCommand:
    """Parse PIUTESTER-style cumulative auxiliary commands.

    Every digit 1..9 contributes digit/4 to the resulting speed. A command
    without digits uses 1x so an empty startup field remains playable.
    """

    raw = value.strip().casefold()
    flags = {name: False for name in _FLAGS.values()}
    unknown: list[str] = []
    speed = 0.0
    for character in raw:
        if character in _FLAGS:
            flags[_FLAGS[character]] = True
        elif "1" <= character <= "9":
            speed += int(character) / 4.0
        elif not character.isspace():
            unknown.append(character)
    return GameplayCommand(
        raw=raw,
        speed=speed if speed > 0.0 else 1.0,
        unknown=tuple(unknown),
        **flags,
    )
