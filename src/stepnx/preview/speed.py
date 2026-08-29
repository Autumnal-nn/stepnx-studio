from __future__ import annotations

import struct
from dataclasses import dataclass
from math import trunc


# PUMPPlayer.SpeedProc / LineBase / ArrowMaker / NoteMaker constants recovered
# from the R!SE IL2CPP runtime.
SPEED_PROC_INTERVAL_SECONDS = 0.016666668
DRAW_STEP_INTERVAL_MS = SPEED_PROC_INTERVAL_SECONDS * 1000.0
SPEED_PROC_INCREMENT = 0.05
LINE_BASE_START_Y = 50.0
BASE_ARROW_Y = 608.0
LINE_BASE_START_GAP_TIME = 8.5
NOTE_RENDER_UNIT = 72.0
LINE_BASE_VELOCITY = (BASE_ARROW_Y - LINE_BASE_START_Y) / LINE_BASE_START_GAP_TIME
EARTHWORM_FAST_THRESHOLD = 333.3333435058594
RANDOM_VELOCITY_LINE_INTERVAL = 48


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _signed_remainder(value: int, divisor: int) -> int:
    """C#/native signed remainder with truncation toward zero."""

    quotient = trunc(int(value) / int(divisor))
    return int(value) - quotient * int(divisor)


def earthworm_user_speed(
    time_ms: float,
    loaded_bpm_slot: float,
    beat_split: int,
) -> float:
    """Port DrawStep's Earthworm _modeSpeedExt square-wave selection.

    ``Div_h_t._BPM`` and the ``msPerLine`` property share offset 0x14. The
    loader therefore replaces the serialized BPM in that slot with msPerLine
    before DrawStep runs. The native branch compares
    ``nBeatSplit * loaded _BPM`` against 333.33334, which is the milliseconds
    per beat for normal Divs and zero for Skip Divs.
    """

    current_ms = trunc(float(time_ms))
    density = _f32(_f32(loaded_bpm_slot) * float(int(beat_split)))
    if density >= _f32(EARTHWORM_FAST_THRESHOLD):
        phase = _signed_remainder(current_ms, 500)
        return 3.0 if float(phase) <= 250.0 else 2.0
    phase = _signed_remainder(current_ms, 360)
    return 2.0 if float(phase) <= 180.0 else 1.0


def random_velocity_triggers(line: int) -> bool:
    """Return DrawStep's exact RandomVelocity line gate."""

    return _signed_remainder(int(line), RANDOM_VELOCITY_LINE_INTERVAL) == 0


def random_velocity_user_speed(random_value: int) -> float:
    """Port DrawStep's signed %4 + 1 conversion after the native RNG call."""

    return float(_signed_remainder(int(random_value), 4) + 1)


def native_base_velocity_pixels(note_size: float) -> float:
    """Project LineBase._baseVelocity into the preview's note-size coordinate."""

    return float(note_size) * LINE_BASE_VELOCITY / NOTE_RENDER_UNIT


@dataclass(slots=True)
class RuntimeSpeedState:
    """Mutable projection of PUMPPlayer's user/block/high-speed fields."""

    mode_speed_ext: float
    block_speed: float
    mode_speed: float
    high_speed: float
    previous_block_speed: float = 1.0
    target_block_speed: float = 1.0
    speed_proc_timer: float = 0.0
    speed_force: bool = False

    @classmethod
    def initialized(
        cls,
        user_speed: float,
        block_speed: float = 1.0,
    ) -> RuntimeSpeedState:
        user = _f32(user_speed)
        block = _f32(block_speed)
        mode = _f32(user * block)
        return cls(
            mode_speed_ext=user,
            block_speed=block,
            mode_speed=mode,
            high_speed=mode,
            previous_block_speed=1.0,
            target_block_speed=block,
        )

    def set_speed(self, high_speed: float, *, is_force: bool = False) -> None:
        if is_force:
            self.speed_force = True
        self.mode_speed_ext = _f32(high_speed)
        self.mode_speed = _f32(self.mode_speed_ext * self.block_speed)

    def set_default_high_speed(self, speed: float) -> None:
        """Port SetDefaultHighSpeed's non-forced initialization path."""

        if self.speed_force:
            return
        self.mode_speed_ext = _f32(speed)
        self.mode_speed = _f32(self.mode_speed_ext * self.block_speed)
        self.high_speed = self.mode_speed

    def set_block_speed(self, speed: float, *, snap: bool = False) -> None:
        value = _f32(speed)
        if value != self.block_speed:
            self.previous_block_speed = self.block_speed
        self.target_block_speed = value
        self.block_speed = value
        self.mode_speed = _f32(self.mode_speed_ext * value)
        if snap:
            self.high_speed = self.mode_speed

    def advance(self, delta_ms: float, *, suppressed: bool = False) -> None:
        """Run SpeedProc's fixed 60-Hz easing for ``delta_ms``.

        GameplaySession now invokes modifier target selection on that same
        DrawStep cadence. This class remains responsible only for the easing
        state itself.
        """

        if delta_ms <= 0.0 or suppressed:
            return
        self.speed_proc_timer = _f32(
            self.speed_proc_timer + float(delta_ms) / 1000.0
        )
        interval = _f32(SPEED_PROC_INTERVAL_SECONDS)
        increment = _f32(SPEED_PROC_INCREMENT)
        while self.speed_proc_timer >= interval:
            self.speed_proc_timer = _f32(self.speed_proc_timer - interval)
            difference = _f32(self.mode_speed - self.high_speed)
            if abs(difference) <= increment:
                self.high_speed = self.mode_speed
                continue
            if difference > 0.0:
                self.high_speed = _f32(self.high_speed + increment)
            else:
                self.high_speed = _f32(self.high_speed - increment)
