from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable


@dataclass(frozen=True, slots=True)
class CommandFlag:
    """One selectable preview modifier.

    ``code`` is retained only as the PIUTESTER/NX2 compatibility key used by
    serialized preview launch options. The Studio UI displays ``label`` and does
    not expose the historical command alphabet as its primary vocabulary.
    """

    code: str
    field: str
    label: str


COMMAND_FLAGS = (
    CommandFlag("v", "vanish", "Vanish"),
    CommandFlag("p", "appear", "Appear"),
    CommandFlag("n", "nonstep", "Non-Step"),
    CommandFlag("w", "flash", "Flash"),
    CommandFlag("f", "freedom", "Freedom"),
    CommandFlag("m", "mirror", "Mirror"),
    CommandFlag("r", "randomize", "Random"),
    CommandFlag("u", "under_attack", "Under Attack"),
    CommandFlag("!", "drop", "Drop"),
    CommandFlag("j", "judge_reverse", "Judge Reverse"),
    CommandFlag("d", "deceleration", "Deceleration"),
    CommandFlag("a", "acceleration", "Acceleration"),
    CommandFlag("x", "exceed_mode", "Exceed"),
    CommandFlag("(", "sink", "Sink"),
    CommandFlag(")", "rise", "Rise"),
    CommandFlag("z", "snake", "Snake"),
    CommandFlag("s", "random_velocity", "Random Velocity"),
    CommandFlag("e", "earthworm", "Earthworm"),
)

_FLAGS = {flag.code: flag.field for flag in COMMAND_FLAGS}


def serialize_command_flags(codes: Iterable[str]) -> str:
    """Serialize selected auxiliary flags in one stable internal order."""

    selected = {str(code).strip().casefold() for code in codes}
    unknown = selected.difference(_FLAGS)
    if unknown:
        raise ValueError("unsupported COMMAND flag(s): " + ", ".join(sorted(unknown)))
    return "".join(flag.code for flag in COMMAND_FLAGS if flag.code in selected)


@dataclass(frozen=True, slots=True)
class GameplayCommand:
    raw: str
    speed: float
    vanish: bool = False
    appear: bool = False
    nonstep: bool = False
    flash: bool = False
    freedom: bool = False
    mirror: bool = False
    randomize: bool = False
    under_attack: bool = False
    drop: bool = False
    judge_reverse: bool = False
    deceleration: bool = False
    acceleration: bool = False
    exceed_mode: bool = False
    sink: bool = False
    rise: bool = False
    snake: bool = False
    random_velocity: bool = False
    earthworm: bool = False
    unknown: tuple[str, ...] = ()

    @property
    def upside_down(self) -> bool:
        """Compatibility alias for the old Studio name; semantically this is Drop."""

        return self.drop

    @property
    def approximate_effects(self) -> tuple[str, ...]:
        """Return compatibility codes for effects still not source-exact.

        The launch UI is semantic and displays full names. This compact status
        tuple deliberately retains the older debug/API contract used by tests
        and external preview tooling.
        """

        enabled = (
            ("V", self.vanish),
            ("P", self.appear),
            ("R", self.randomize),
            ("X", self.exceed_mode),
        )
        return tuple(flag for flag, active in enabled if active)

    @property
    def pending_effects(self) -> tuple[str, ...]:
        """Return parsed flags that still have no complete runtime projection."""

        return ()

    def with_speed(self, speed: int) -> GameplayCommand:
        if not 1 <= speed <= 9:
            raise ValueError("gameplay speed must be between 1x and 9x")
        return replace(self, speed=float(speed))

    def lane_map(self, columns: int, *, seed: int = 0) -> tuple[int, ...]:
        """Return only fixed lane permutations.

        Under Attack and Drop are sequence-zone geometry, not lane maps. Random
        is a chart/event transformation whose mapping evolves by row, so it is
        deliberately excluded here as well. ``seed`` remains accepted for API
        compatibility with older callers.
        """

        del seed
        lanes = list(range(columns))
        if self.mirror:
            lanes.reverse()
        return tuple(lanes)

    def note_opacity(
        self,
        visibility: int,
        *,
        screen_y: float,
        screen_midline: float,
        time_ms: float,
    ) -> float:
        """Render legacy display modes around the physical screen midline.

        Vanish is visible on the approach half and disappears after crossing the
        centre line. Appear is the inverse. Header Visibility has already
        rewritten the event's low VisualEffect bits before this function runs.
        """

        if self.nonstep or visibility == 0 or (self.vanish and self.appear):
            return 0.0
        below_midline = float(screen_y) >= float(screen_midline)
        if visibility == 1:  # Appear: visible only after crossing centre.
            opacity = 0.0 if below_midline else 1.0
        elif visibility == 2:  # Vanish: visible only before crossing centre.
            opacity = 1.0 if below_midline else 0.0
        else:
            opacity = 1.0
        if self.appear:
            opacity = min(opacity, 0.0 if below_midline else 1.0)
        if self.vanish:
            opacity = min(opacity, 1.0 if below_midline else 0.0)
        if self.flash and int(float(time_ms) // 100.0) % 2:
            opacity = 0.0
        return opacity


def parse_gameplay_command(value: str) -> GameplayCommand:
    """Parse PIUTESTER/NX2-style compatibility command characters.

    The launch UI exposes semantic named choices and keeps 1x..9x in a separate
    Speed control. Historical characters remain only for interoperability and
    reverse-engineering anchors. Digits keep the legacy cumulative quarter-speed
    rule for non-UI callers.
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
