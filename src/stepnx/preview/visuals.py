from __future__ import annotations

from math import pi, pow, sin

from stepnx.preview.modifiers import AccDecMode, VisibilityMode
from stepnx.preview.speed import (
    BASE_ARROW_Y,
    LINE_BASE_VELOCITY,
    NOTE_RENDER_UNIT,
)


# LineBase source defaults recovered from LineBase..ctor RVA 0x63B280.
LINE_BASE_Y_MIN = 200.0
LINE_BASE_Y_MAX = 550.0
LINE_BASE_X_AMPLITUDE = 20.0
LINE_BASE_WAVE_RATE = 2.0
LINE_BASE_ACC_POW = 1.5
LINE_BASE_ACC_SCALE = 1.0
LINE_BASE_ACC_OFFSET = -200.0


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def native_acc_dec_offset(
    y: float,
    mode: AccDecMode,
    *,
    y_min: float = LINE_BASE_Y_MIN,
    y_max: float = LINE_BASE_Y_MAX,
    acc_pow: float = LINE_BASE_ACC_POW,
    acc_scale: float = LINE_BASE_ACC_SCALE,
) -> float:
    """Port LineBase.GetAccDecYOffset's scalar branch.

    R!SE normalizes the current local Y into the serialized LineBase y-range,
    applies one of two power curves, then scales a separate -200-unit offset.
    The caller may pass prefab-overridden values; the defaults here are the
    exact constructor defaults from the IL2CPP binary.
    """

    if mode not in (AccDecMode.ACCELERATION, AccDecMode.DECELERATION):
        return 0.0
    if y_max <= y_min or y >= y_max:
        return 0.0

    t = _clamp01((float(y) - float(y_min)) / (float(y_max) - float(y_min)))
    if mode is AccDecMode.ACCELERATION:
        shape = 1.0 - pow(t, float(acc_pow))
    else:
        shape = pow(1.0 - t, float(acc_pow))
    return shape * LINE_BASE_ACC_OFFSET * float(acc_scale)


def native_line_y(
    beat_distance: float,
    high_speed: float,
    mode: AccDecMode = AccDecMode.LINEAR,
    *,
    base_arrow_y: float = BASE_ARROW_Y,
    base_velocity: float = LINE_BASE_VELOCITY,
    y_min: float = LINE_BASE_Y_MIN,
    y_max: float = LINE_BASE_Y_MAX,
    acc_pow: float = LINE_BASE_ACC_POW,
    acc_scale: float = LINE_BASE_ACC_SCALE,
) -> float:
    """Return LineBase's native local Y after RePos and Acc/Dec offset."""

    base_y = float(base_arrow_y) - (
        float(beat_distance) * float(base_velocity) * float(high_speed)
    )
    return base_y + native_acc_dec_offset(
        base_y,
        mode,
        y_min=y_min,
        y_max=y_max,
        acc_pow=acc_pow,
        acc_scale=acc_scale,
    )


def native_screen_y(
    native_y: float,
    receptor_y: float,
    note_size: float,
    *,
    upside_down: bool = False,
    base_arrow_y: float = BASE_ARROW_Y,
) -> float:
    """Project native LineBase Y into StepNX's scaled preview coordinate."""

    pixels = (float(base_arrow_y) - float(native_y)) * (
        float(note_size) / NOTE_RENDER_UNIT
    )
    return float(receptor_y) - pixels if upside_down else float(receptor_y) + pixels


def native_snake_x_offset(
    y: float,
    note_size: float,
    *,
    y_min: float = LINE_BASE_Y_MIN,
    y_max: float = LINE_BASE_Y_MAX,
    amplitude: float = LINE_BASE_X_AMPLITUDE,
    wave_rate: float = LINE_BASE_WAVE_RATE,
) -> float:
    """Port the scalar sine path from LineBase.PlaySnakeAnim.

    The runtime may substitute the maximum visible child Y for grouped split
    objects before reaching this formula. StepNX events are flattened, so this
    helper deliberately models the directly recovered scalar path only.
    """

    if y_max <= y_min or y >= y_max:
        return 0.0
    t = _clamp01((float(y) - float(y_min)) / (float(y_max) - float(y_min)))
    native_x = sin(t * pi * float(wave_rate)) * float(amplitude)
    return native_x * (float(note_size) / NOTE_RENDER_UNIT)


def apply_global_visibility_effect(effect: int, mode: VisibilityMode) -> int:
    """Port PlayBase.InitData's Header Visibility Step.Change mask.

    Visibility modes 1..3 clear only the low VisualEffect nibble and replace it
    with Disappear(2), Appear(1), or Hidden(0), preserving ZigZag/high bits.
    Visible(0) leaves the serialized effect byte untouched.
    """

    value = int(effect) & 0xFF
    if mode is VisibilityMode.VISIBLE:
        return value
    replacement = {
        VisibilityMode.VANISH: 0x02,
        VisibilityMode.APPEAR: 0x01,
        VisibilityMode.HIDDEN: 0x00,
    }.get(mode)
    if replacement is None:
        return value
    return (value & 0xF0) | replacement
