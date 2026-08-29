from __future__ import annotations

import struct
from dataclasses import dataclass


# PUMPPlayer.SpeedProc / LineBase / ArrowMaker / NoteMaker constants recovered
# from the R!SE IL2CPP runtime.
SPEED_PROC_INTERVAL_SECONDS = 0.016666668
SPEED_PROC_INCREMENT = 0.05
LINE_BASE_START_Y = 50.0
BASE_ARROW_Y = 608.0
LINE_BASE_START_GAP_TIME = 8.5
NOTE_RENDER_UNIT = 72.0
LINE_BASE_VELOCITY = (BASE_ARROW_Y - LINE_BASE_START_Y) / LINE_BASE_START_GAP_TIME


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def native_base_velocity_pixels(note_size: float) -> float:
    """Project LineBase._baseVelocity into the preview's note-size coordinate.

    R!SE builds LineBase._baseVelocity from (608 - 50) / 8.5. NoteMaker's
    modern scale path uses 72 Unity units as one rendered note unit, so a
    viewport note of ``note_size`` pixels scales the native beat velocity by
    ``note_size / 72`` rather than treating lane spacing as _baseVelocity.
    """

    return float(note_size) * LINE_BASE_VELOCITY / NOTE_RENDER_UNIT


@dataclass(slots=True)
class RuntimeSpeedState:
    """Mutable projection of PUMPPlayer's user/block/high-speed fields.

    ``set_speed`` mirrors PUMPPlayer.SetSpeed: it updates _modeSpeedExt and the
    target _modeSpeed without snapping pHighSpeed. ``set_block_speed`` mirrors
    the DrawStep side of the state machine and may explicitly snap pHighSpeed
    when a Div transition/Smooth update does so. ``advance`` simulates the
    60-Hz SpeedProc ticks so preview updates remain deterministic even when the
    host advances by a larger wall-clock chunk.
    """

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
        """Run the SpeedProc easing that would occur during ``delta_ms``.

        The native method consumes one 1/60-second step per Unity update. The
        preview may receive coarser time jumps, so this loops over the elapsed
        60-Hz ticks to reproduce the state reached by normal frame-by-frame
        updates instead of making the result depend on the Qt timer cadence.
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
