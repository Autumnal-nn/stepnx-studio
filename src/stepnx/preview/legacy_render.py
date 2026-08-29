from __future__ import annotations

from math import radians, tan

LEGACY_LOGICAL_WIDTH = 640.0
LEGACY_LOGICAL_HEIGHT = 480.0

LEGACY_VISIBILITY_MASK_HEIGHT = 512.0
LEGACY_VISIBILITY_MASK_CENTER = 256.0
LEGACY_VISIBILITY_VERTEX_OFFSET = 16.5
LEGACY_VISIBILITY_ALPHA_BIAS = 128.0
LEGACY_VISIBILITY_ALPHA_SLOPE = 8.0
LEGACY_VISIBILITY_SCREEN_CENTER = (
    LEGACY_LOGICAL_HEIGHT
    + LEGACY_VISIBILITY_VERTEX_OFFSET
    - LEGACY_VISIBILITY_MASK_CENTER
)

LEGACY_NX_FOV_DEGREES = 75.0
LEGACY_NX_SCALE = 1.5
LEGACY_NX_ROTATE_DEGREES = -120.0
LEGACY_NX_DROP_ROTATE_DEGREES = -60.0
LEGACY_NX_YZ_COUPLING = 1.299038105676658
LEGACY_NX_Z_OFFSET = -519.6152422706632


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, float(value)))


def legacy_visibility_alpha(
    screen_y: float,
    viewport_height: float,
    visibility: int,
) -> float:
    """Return the NXA/Prime screen-space alpha mask at one Y coordinate.

    Both supplied executables build the same 32x512 RGBA effect texture. The
    low two VisualEffect bits select Invisible, Appear, Vanish, or Visible. The
    transition bands use centre 256, vertex offset 16.5, bias 128 and a signed
    slope of eight alpha units per logical screen pixel.
    """

    mode = int(visibility) & 0x03
    if mode == 0:
        return 0.0
    if mode == 3:
        return 1.0
    height = max(1.0, float(viewport_height))
    logical_y = float(screen_y) * LEGACY_LOGICAL_HEIGHT / height
    mask_y = LEGACY_LOGICAL_HEIGHT - logical_y + LEGACY_VISIBILITY_VERTEX_OFFSET
    direction = 1.0 if mode == 1 else -1.0
    alpha_byte = (
        (mask_y - LEGACY_VISIBILITY_MASK_CENTER)
        * LEGACY_VISIBILITY_ALPHA_SLOPE
        * direction
        + LEGACY_VISIBILITY_ALPHA_BIAS
    )
    return _clamp(alpha_byte, 0.0, 255.0) / 255.0


def legacy_visibility_gradient_stops(
    visibility: int,
) -> tuple[tuple[float, float], ...]:
    """Return normalized viewport stops for the exact piecewise-linear mask."""

    mode = int(visibility) & 0x03
    if mode == 0:
        return ((0.0, 0.0), (1.0, 0.0))
    if mode == 3:
        return ((0.0, 1.0), (1.0, 1.0))

    centre = LEGACY_VISIBILITY_SCREEN_CENTER
    low_span = LEGACY_VISIBILITY_ALPHA_BIAS / LEGACY_VISIBILITY_ALPHA_SLOPE
    high_span = (
        255.0 - LEGACY_VISIBILITY_ALPHA_BIAS
    ) / LEGACY_VISIBILITY_ALPHA_SLOPE
    if mode == 1:
        full_y = centre - high_span
        zero_y = centre + low_span
        stops = (
            (0.0, 1.0),
            (full_y / LEGACY_LOGICAL_HEIGHT, 1.0),
            (zero_y / LEGACY_LOGICAL_HEIGHT, 0.0),
            (1.0, 0.0),
        )
    else:
        zero_y = centre - low_span
        full_y = centre + high_span
        stops = (
            (0.0, 0.0),
            (zero_y / LEGACY_LOGICAL_HEIGHT, 0.0),
            (full_y / LEGACY_LOGICAL_HEIGHT, 1.0),
            (1.0, 1.0),
        )
    return tuple((_clamp(position, 0.0, 1.0), alpha) for position, alpha in stops)


def _matmul3(
    left: tuple[tuple[float, float, float], ...],
    right: tuple[tuple[float, float, float], ...],
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        tuple(
            sum(left[row][k] * right[k][column] for k in range(3))
            for column in range(3)
        )
        for row in range(3)
    )


def legacy_nx_homography(
    viewport_width: float,
    viewport_height: float,
    *,
    z: float = 0.0,
    drop: bool = False,
    under_attack: bool = False,
) -> tuple[float, float, float, float, float, float, float, float, float]:
    """Return the NXA/Prime NX Mode projective transform as Qt coefficients.

    The source pipeline is a 640x480 logical field with Perspective(75), a
    -120 degree X tilt (-60 in the Drop branch), centre translation and 1.5
    scale. For a fixed Z plane this collapses exactly to a 2-D homography. The
    tuple order matches QTransform's nine-argument constructor.
    """

    width = max(1.0, float(viewport_width))
    height = max(1.0, float(viewport_height))
    fixed_z = float(z)

    focal = 1.0 / tan(radians(LEGACY_NX_FOV_DEGREES / 2.0))
    eye_distance = focal * LEGACY_LOGICAL_WIDTH / 2.0
    projection_scale = focal * LEGACY_LOGICAL_HEIGHT / 2.0

    x_in = LEGACY_LOGICAL_WIDTH / width
    y_in = LEGACY_LOGICAL_HEIGHT / height
    x_out = width / LEGACY_LOGICAL_WIDTH
    y_out = height / LEGACY_LOGICAL_HEIGHT

    y_z = -LEGACY_NX_YZ_COUPLING if drop else LEGACY_NX_YZ_COUPLING
    z_z = 0.75 if drop else -0.75
    denominator_constant = eye_distance - LEGACY_NX_Z_OFFSET - z_z * fixed_z
    if abs(denominator_constant) < 1e-9:
        denominator_constant = 1e-9

    c = LEGACY_NX_YZ_COUPLING
    matrix = (
        (
            x_out * (1.5 * projection_scale) * x_in / denominator_constant,
            x_out * (-320.0 * c) * y_in / denominator_constant,
            x_out
            * (320.0 * denominator_constant - 480.0 * projection_scale)
            / denominator_constant,
        ),
        (
            0.0,
            y_out
            * (-240.0 * c - 0.75 * projection_scale)
            * y_in
            / denominator_constant,
            y_out
            * (
                240.0 * denominator_constant
                + 60.0 * projection_scale
                - projection_scale * y_z * fixed_z
            )
            / denominator_constant,
        ),
        (
            0.0,
            -c * y_in / denominator_constant,
            1.0,
        ),
    )

    if under_attack:
        matrix = _matmul3(
            matrix,
            (
                (-1.0, 0.0, width),
                (0.0, -1.0, height),
                (0.0, 0.0, 1.0),
            ),
        )

    return (
        matrix[0][0],
        matrix[1][0],
        matrix[2][0],
        matrix[0][1],
        matrix[1][1],
        matrix[2][1],
        matrix[0][2],
        matrix[1][2],
        matrix[2][2],
    )


def legacy_nx_project_point(
    x: float,
    y: float,
    viewport_width: float,
    viewport_height: float,
    *,
    z: float = 0.0,
    drop: bool = False,
    under_attack: bool = False,
) -> tuple[float, float]:
    """Project one point through the exact fixed-Z NX Mode homography."""

    m11, m12, m13, m21, m22, m23, m31, m32, m33 = legacy_nx_homography(
        viewport_width,
        viewport_height,
        z=z,
        drop=drop,
        under_attack=under_attack,
    )
    denominator = m13 * float(x) + m23 * float(y) + m33
    if abs(denominator) < 1e-9:
        denominator = 1e-9 if denominator >= 0.0 else -1e-9
    return (
        (m11 * float(x) + m21 * float(y) + m31) / denominator,
        (m12 * float(x) + m22 * float(y) + m32) / denominator,
    )
