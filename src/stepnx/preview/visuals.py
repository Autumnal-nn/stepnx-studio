from __future__ import annotations

from math import pow, sin

from stepnx.preview.modifiers import (
    AccDecMode,
    SequenceZoneTransform,
    VisibilityMode,
)
from stepnx.preview.speed import (
    BASE_ARROW_Y,
    LINE_BASE_VELOCITY,
    NOTE_RENDER_UNIT,
)


# LineBase source defaults recovered from R!SE LineBase..ctor RVA 0x63B280.
LINE_BASE_Y_MIN = 200.0
LINE_BASE_Y_MAX = 550.0
LINE_BASE_X_AMPLITUDE = 20.0
LINE_BASE_WAVE_RATE = 2.0
LINE_BASE_ACC_POW = 1.5
LINE_BASE_ACC_SCALE = 1.0
LINE_BASE_ACC_OFFSET = -200.0
LINE_BASE_PI = 3.1415927410125732

# Historical Prime 2 renderer constants recovered from the supplied `exec`.
# These deliberately remain separate from the modern R!SE LineBase constants:
# the two engines really do implement different Snake amplitudes.
PRIME2_PATH_UNIT = 60.0
PRIME2_PATH_PI = 3.1415927410125732
PRIME2_SNAKE_AMPLITUDE = 30.0
PRIME2_THROW_SPAN = 453.0
PRIME2_THROW_AMPLITUDE = 96.0  # 64 * 1.5, standard branch
PRIME2_THROW_ALT_AMPLITUDE = 300.0  # 200 * 1.5, external-state branch (OPEN)


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
    """Port R!SE LineBase.GetAccDecYOffset's scalar branch."""

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


def native_line_local_y(
    beat_distance: float,
    mode: AccDecMode = AccDecMode.LINEAR,
    *,
    base_arrow_y: float = BASE_ARROW_Y,
    base_velocity: float = LINE_BASE_VELOCITY,
    y_min: float = LINE_BASE_Y_MIN,
    y_max: float = LINE_BASE_Y_MAX,
    acc_pow: float = LINE_BASE_ACC_POW,
    acc_scale: float = LINE_BASE_ACC_SCALE,
) -> float:
    """Return R!SE LineBase local Y before NoteMaker applies ``pHighSpeed``."""

    base_y = float(base_arrow_y) - float(beat_distance) * float(base_velocity)
    return base_y + native_acc_dec_offset(
        base_y,
        mode,
        y_min=y_min,
        y_max=y_max,
        acc_pow=acc_pow,
        acc_scale=acc_scale,
    )


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
    """Return R!SE's speed-scaled effective native Y.

    Ordering is source-significant: LineBase placement/AccDec happens first and
    NoteMaker's pHighSpeed parent scale is applied afterward around the receptor.
    """

    local_y = native_line_local_y(
        beat_distance,
        mode,
        base_arrow_y=base_arrow_y,
        base_velocity=base_velocity,
        y_min=y_min,
        y_max=y_max,
        acc_pow=acc_pow,
        acc_scale=acc_scale,
    )
    return float(base_arrow_y) - (
        (float(base_arrow_y) - local_y) * float(high_speed)
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
    """Port modern R!SE LineBase.PlaySnakeAnim (20-unit amplitude)."""

    if y_max <= y_min or y >= y_max:
        return 0.0
    t = _clamp01((float(y) - float(y_min)) / (float(y_max) - float(y_min)))
    native_x = sin(t * LINE_BASE_PI * float(wave_rate)) * float(amplitude)
    return native_x * (float(note_size) / NOTE_RENDER_UNIT)


def prime2_snake_x_offset(beat_distance: float, note_size: float) -> float:
    """Port Prime 2's historical Snake path.

    In the supplied Prime 2 executable the dedicated Snake branch computes
    ``sinf(pi * phase) * 60 * 0.5``. The resulting amplitude is therefore 30,
    not R!SE's later 20. ``phase`` is the renderer's pre-speed beat-distance
    value, so speed changes do not alter the horizontal wave frequency.
    """

    native_x = sin(PRIME2_PATH_PI * float(beat_distance)) * PRIME2_SNAKE_AMPLITUDE
    return native_x * (float(note_size) / PRIME2_PATH_UNIT)


def prime2_throw_y_offset(
    beat_distance: float,
    high_speed: float,
    note_size: float,
    *,
    rise: bool,
    alternate_amplitude: bool = False,
) -> float:
    """Port Prime 2's standard Sink/Rise sine path.

    The renderer first forms ``d = beat_distance * 60 * speed`` and then applies
    ``sin(pi*d/453) * amplitude``. Standard Sink uses +96 and Rise uses -96.
    Prime 2 also contains an external-state branch selecting +/-300; the state
    producer is still unidentified, so StepNX never enables it implicitly.
    """

    displacement = float(beat_distance) * PRIME2_PATH_UNIT * float(high_speed)
    amplitude = (
        PRIME2_THROW_ALT_AMPLITUDE
        if alternate_amplitude
        else PRIME2_THROW_AMPLITUDE
    )
    if rise:
        amplitude = -amplitude
    native_y = sin(PRIME2_PATH_PI * displacement / PRIME2_THROW_SPAN) * amplitude
    return native_y * (float(note_size) / PRIME2_PATH_UNIT)


def legacy_exceed_x_offset(
    vertical_pixels: float,
    field_width: float,
    *,
    from_right: bool,
    travel_height: float,
) -> float:
    """Approximate the historical Exceed diagonal path.

    Prime 2 and Andamiro's own modifier documentation confirm the semantic path:
    notes approach the receptors diagonally from the opposite player's side.
    The exact legacy affine coefficient has not yet been recovered from either
    Prime 2 or PIUTESTER. Keep the approximation isolated here so it cannot be
    mistaken for the source-exact Snake/Sink/Rise formulas.
    """

    span = max(1.0, abs(float(travel_height)))
    progress_from_receptor = _clamp01(abs(float(vertical_pixels)) / span)
    shift = float(field_width) * 0.5 * progress_from_receptor
    return shift if from_right else -shift


def sequence_zone_affine(
    transform: SequenceZoneTransform,
    width: float,
    height: float,
    *,
    normal_receptor_y: float,
) -> tuple[float, float, float, float]:
    """Return ``(sx, sy, tx, ty)`` for UA/Drop/Mid composition."""

    flags = SequenceZoneTransform(transform)
    under_attack = bool(flags & SequenceZoneTransform.UNDER_ATTACK)
    drop = bool(flags & SequenceZoneTransform.DROP)
    mid = bool(flags & SequenceZoneTransform.MID)

    sx = -1.0 if under_attack else 1.0
    # UA flips Y; Drop also flips Y. Together the two reflections cancel on Y.
    sy = -1.0 if under_attack ^ drop else 1.0
    tx = float(width) if sx < 0.0 else 0.0
    ty = float(height) if sy < 0.0 else 0.0

    if mid:
        local_mid_translation = float(height) / 2.0 - float(normal_receptor_y)
        ty += sy * local_mid_translation

    return sx, sy, tx, ty


def transform_sequence_zone_point(
    x: float,
    y: float,
    transform: SequenceZoneTransform,
    width: float,
    height: float,
    *,
    normal_receptor_y: float,
) -> tuple[float, float]:
    """Apply the affine composition returned by ``sequence_zone_affine``."""

    sx, sy, tx, ty = sequence_zone_affine(
        transform,
        width,
        height,
        normal_receptor_y=normal_receptor_y,
    )
    return sx * float(x) + tx, sy * float(y) + ty


def apply_global_visibility_effect(effect: int, mode: VisibilityMode) -> int:
    """Port R!SE PlayBase.InitData's Header Visibility Step.Change mask."""

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
