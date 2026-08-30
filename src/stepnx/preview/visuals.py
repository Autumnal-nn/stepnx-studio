from __future__ import annotations

from functools import lru_cache
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
PRIME2_THROW_ALT_AMPLITUDE = 300.0  # 200 * 1.5, NX Mode branch
PRIME2_THROW_CAMERA_FOV = 43.60300064086914
PRIME2_THROW_CAMERA_EYE_Z = 600.0

# Prime 1 and NXA use the same legacy Acceleration/Deceleration renderer.
# Prime uses SSE at 0x806D350..0x806D809; NXA uses x87 at
# 0x8093475..0x809377C. Their constants and mode mapping agree exactly.
LEGACY_ACCDEC_PATH_UNIT = 60.0
LEGACY_DECEL_DIVISOR = 1600.0
LEGACY_ACCEL_BIAS = 83.33333587646484
LEGACY_ACCEL_NUMERATOR = 50000.0
LEGACY_ACCEL_LIMIT = 600.0
LEGACY_ACCEL_RECEPTOR_Y = 413.0
LEGACY_ACCEL_SENTINEL_Y = 16384.0

# Prime 1 path_zigzag consumer at 0x806D6EF. Div 222 is the start,
# Div 221 the keyframe interval; both default to one. Nine permutation
# keyframes cover phase 0..8. The permutation builder uses this MSVC-style LCG.
PRIME2_ZIGZAG_PHASE_LIMIT = 8.0
PRIME2_ZIGZAG_KEYFRAME_COUNT = 9
PRIME2_ZIGZAG_LCG_MULTIPLIER = 0x0019660D
PRIME2_ZIGZAG_LCG_INCREMENT = 0x3C6EF35F


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


def prime2_throw_z_offset(
    beat_distance: float,
    high_speed: float,
    *,
    rise: bool,
    alternate_amplitude: bool = False,
) -> float:
    """Return Prime's native Sink/Rise Z coordinate.

    `piu_prime` writes the recovered sine term into the third coordinate of all
    four arrow vertices at 0x806DEAE/BD/CC/E1. It is therefore depth, not a Y
    offset. Standard amplitude is 96; NX Mode selects the 300-unit branch.
    """

    displacement = float(beat_distance) * PRIME2_PATH_UNIT * float(high_speed)
    amplitude = (
        PRIME2_THROW_ALT_AMPLITUDE
        if alternate_amplitude
        else PRIME2_THROW_AMPLITUDE
    )
    if rise:
        amplitude = -amplitude
    return sin(PRIME2_PATH_PI * displacement / PRIME2_THROW_SPAN) * amplitude


def prime2_throw_perspective_scale(
    z: float, *, eye_z: float = PRIME2_THROW_CAMERA_EYE_Z
) -> float:
    """Project Prime's uniform arrow Z into the 2-D preview scale.

    Prime sets `gluPerspective(43.603..., aspect, .1, 5000)` and uses a
    `gluLookAt` eye distance of 600 for the native 480-high gameplay viewport.
    A quad translated uniformly in Z therefore scales about screen centre by
    ``eye_z / (eye_z - z)``.
    """

    denominator = float(eye_z) - float(z)
    if denominator <= 1.0:
        return float(eye_z)
    return float(eye_z) / denominator


def prime2_throw_y_offset(
    beat_distance: float,
    high_speed: float,
    note_size: float,
    *,
    rise: bool,
    alternate_amplitude: bool = False,
) -> float:
    """Compatibility wrapper for the old, incorrectly named helper.

    This returns the historical scaled sine magnitude only. Rendering must use
    `prime2_throw_z_offset` plus perspective projection; the value is not Y.
    """

    return prime2_throw_z_offset(
        beat_distance,
        high_speed,
        rise=rise,
        alternate_amplitude=alternate_amplitude,
    ) * (float(note_size) / PRIME2_PATH_UNIT)


def legacy_acc_dec_distance(
    beat_distance: float,
    high_speed: float,
    note_size: float,
    mode: AccDecMode,
) -> float:
    """Return the historical Prime/NXA distance from the receptor in pixels.

    Both executables first form ``x = beat_distance * 60 * high_speed``.
    Mode 2 (Deceleration) uses ``x^3 / 1600``. Mode 1 (Acceleration) uses
    ``600 - 50000 / (x + 83.33333587646484)``. NXA's non-positive
    denominator branch writes the same 16384 sentinel used by Prime's renderer;
    converting that native Y back to receptor-relative distance preserves the
    off-screen behavior without inventing a clamp.
    """

    x = float(beat_distance) * LEGACY_ACCDEC_PATH_UNIT * float(high_speed)
    if mode is AccDecMode.DECELERATION:
        native_distance = (x * x * x) / LEGACY_DECEL_DIVISOR
    elif mode is AccDecMode.ACCELERATION:
        denominator = x + LEGACY_ACCEL_BIAS
        if denominator <= 0.0:
            native_distance = LEGACY_ACCEL_RECEPTOR_Y - LEGACY_ACCEL_SENTINEL_Y
        else:
            native_distance = (
                LEGACY_ACCEL_LIMIT - LEGACY_ACCEL_NUMERATOR / denominator
            )
    else:
        native_distance = x
    return native_distance * (float(note_size) / LEGACY_ACCDEC_PATH_UNIT)


@lru_cache(maxsize=256)
def prime2_zigzag_keyframes(
    columns: int, seed: int
) -> tuple[tuple[int, ...], ...]:
    """Build the nine deterministic legacy Snake Path keyframes.

    Keyframe zero is identity so phase zero joins the authored lane continuously
    at Div 222. Keyframes one through eight use the recovered permutation
    generator. The native seed also includes an engine-owned per-player contribution that
    is not available to the standalone preview. StepNX supplies the resolved
    route seed, while preserving the recovered 32-bit LCG and Fisher-Yates
    selection exactly. Geometry and interpolation are therefore native; only
    the initial random state is preview-local.
    """

    count = int(columns)
    if count <= 0:
        return ()
    state = int(seed) & 0xFFFFFFFF
    # Phase zero is the authored lane map. The previous implementation
    # randomized frame zero as well, which caused an observable snap when the
    # path crossed Div 222 into its straight zone.
    frames: list[tuple[int, ...]] = [tuple(range(count))]
    for _ in range(1, PRIME2_ZIGZAG_KEYFRAME_COUNT):
        candidates = list(range(count))
        output = [0] * count
        for remaining in range(count, 0, -1):
            state = (
                state * PRIME2_ZIGZAG_LCG_MULTIPLIER
                + PRIME2_ZIGZAG_LCG_INCREMENT
            ) & 0xFFFFFFFF
            pick = (state >> 8) % remaining
            output[remaining - 1] = candidates[pick]
            candidates[pick] = candidates[remaining - 1]
        frames.append(tuple(output))
    return tuple(frames)


def prime2_snake_path_lane_position(
    source_lane: int,
    beat_distance: float,
    columns: int,
    seed: int,
    *,
    start: float = 1.0,
    interval: float = 1.0,
) -> float:
    """Port the legacy NX20 per-note Snake Path interpolation.

    VisualEffect bit 0x10 selects this path independently of Header 34's global
    Snake modifier. Div 222 is the straight-zone/start threshold and Div 221 is
    the phase length/divisor. After the threshold the renderer interpolates
    between nine pseudo-random lane maps and clamps phase >= 8 to keyframe eight.
    """

    lane = int(source_lane)
    count = int(columns)
    if not 0 <= lane < count:
        return float(lane)
    distance = float(beat_distance)
    start_value = float(start)
    if distance <= start_value:
        return float(lane)

    frames = prime2_zigzag_keyframes(count, int(seed))
    if not frames:
        return float(lane)
    interval_value = float(interval)
    if interval_value <= 0.0:
        return float(frames[-1][lane])
    phase = (distance - start_value) / interval_value
    if phase >= PRIME2_ZIGZAG_PHASE_LIMIT:
        return float(frames[-1][lane])
    if phase <= 0.0:
        return float(lane)
    lower = int(phase)
    fraction = phase - float(lower)
    upper = min(lower + 1, PRIME2_ZIGZAG_KEYFRAME_COUNT - 1)
    return (
        float(frames[lower][lane]) * (1.0 - fraction)
        + float(frames[upper][lane]) * fraction
    )


# Compatibility alias for code written during the audit before the recovered
# path was correctly separated from Header 35 ZigZag. New code must use the
# Snake Path name; 221/222 do not describe Header 35.
prime2_zigzag_lane_position = prime2_snake_path_lane_position


def legacy_exceed_x_offset(
    beat_distance: float,
    high_speed: float,
    note_size: float,
    *,
    from_right: bool,
) -> float:
    """Port Prime/NXA's historical Exceed diagonal path.

    Prime's live ``path_exeed`` branch at 0x0806D3E2..0x0806D426 forms
    ``d = beatDistance * 60 * highSpeed``. The first five-lane bank receives
    ``+d`` while the second receives ``-d`` relative to its normal bank origin.
    The value is signed and intentionally unbounded: there is no viewport-height
    normalization, half-field clamp, or absolute-value step in the runtime.

    StepNX scales Prime's 60-unit lane/path pitch to the rendered note pitch,
    preserving the original near-45-degree trajectory at native geometry.
    """

    native_distance = (
        float(beat_distance) * PRIME2_PATH_UNIT * float(high_speed)
    )
    shift = native_distance * (float(note_size) / PRIME2_PATH_UNIT)
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
