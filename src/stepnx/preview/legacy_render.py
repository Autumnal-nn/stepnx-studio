from __future__ import annotations

from math import cos, radians, sin, tan

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
LEGACY_NX_SHALLOW_ROTATE_DEGREES = -60.0
LEGACY_NX_STEEP_ROTATE_DEGREES = -120.0


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


def _matmul4(
    left: tuple[tuple[float, float, float, float], ...],
    right: tuple[tuple[float, float, float, float], ...],
) -> tuple[tuple[float, float, float, float], ...]:
    return tuple(
        tuple(
            sum(left[row][k] * right[k][column] for k in range(4))
            for column in range(4)
        )
        for row in range(4)
    )


def _translate4(
    x: float, y: float, z: float = 0.0
) -> tuple[tuple[float, float, float, float], ...]:
    return (
        (1.0, 0.0, 0.0, float(x)),
        (0.0, 1.0, 0.0, float(y)),
        (0.0, 0.0, 1.0, float(z)),
        (0.0, 0.0, 0.0, 1.0),
    )


def _scale4(
    x: float, y: float, z: float
) -> tuple[tuple[float, float, float, float], ...]:
    return (
        (float(x), 0.0, 0.0, 0.0),
        (0.0, float(y), 0.0, 0.0),
        (0.0, 0.0, float(z), 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def _rotate_x4(degrees: float) -> tuple[tuple[float, float, float, float], ...]:
    angle = radians(float(degrees))
    cosine = cos(angle)
    sine = sin(angle)
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, cosine, -sine, 0.0),
        (0.0, sine, cosine, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def _rotate_z4(degrees: float) -> tuple[tuple[float, float, float, float], ...]:
    angle = radians(float(degrees))
    cosine = cos(angle)
    sine = sin(angle)
    return (
        (cosine, -sine, 0.0, 0.0),
        (sine, cosine, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def legacy_nx_homography(
    viewport_width: float,
    viewport_height: float,
    *,
    z: float = 0.0,
    drop: bool = False,
    under_attack: bool = False,
) -> tuple[float, float, float, float, float, float, float, float, float]:
    """Collapse the exact Prime/NXA NX fixed-Z OpenGL pipeline to QTransform.

    The native perspective helper derives camera distance from viewport HEIGHT,
    applies Perspective(75, W/H, .1, 5000), translates projection by (-W/2,-H/2),
    then uses LookAt(0,0,d -> 0,0,0, up +Y). NX has four dedicated branches:

    * NX:              Rx(-60),  centered Scale(1.5,+1.5,1.5)
    * NX + Drop: T(0,H), Rx(-120), centered Scale(1.5,+1.5,1.5)
    * NX + UA:   T(0,H), Rx(-120), centered Scale(1.5,-1.5,1.5),
                 then native UA T(W,H) / Rz(180)
    * NX + UA + Drop:  Rx(-60), centered Scale(1.5,-1.5,1.5),
                 then native UA T(W,H) / Rz(180)

    Input/output conversion bridges Qt top-left coordinates and native OpenGL
    bottom-left coordinates. For a fixed Throw Z, the complete 3-D pipeline is
    exactly representable as one 2-D projective transform.
    """

    width = max(1.0, float(viewport_width))
    height = max(1.0, float(viewport_height))
    centre_x = width / 2.0
    centre_y = height / 2.0

    input_qt_to_gl = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, -1.0, 0.0, height),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )

    y_scale = -LEGACY_NX_SCALE if under_attack else LEGACY_NX_SCALE
    centred_scale = _matmul4(
        _matmul4(
            _translate4(centre_x, centre_y),
            _scale4(LEGACY_NX_SCALE, y_scale, LEGACY_NX_SCALE),
        ),
        _translate4(-centre_x, -centre_y),
    )

    # Native branch table: Drop and UA choose opposite X-tilt branches. The
    # steep branch is selected iff exactly one is active.
    steep = bool(drop) ^ bool(under_attack)
    if steep:
        model = _matmul4(
            _matmul4(_translate4(0.0, height), _rotate_x4(LEGACY_NX_STEEP_ROTATE_DEGREES)),
            centred_scale,
        )
    else:
        model = _matmul4(
            _rotate_x4(LEGACY_NX_SHALLOW_ROTATE_DEGREES),
            centred_scale,
        )

    if under_attack:
        model = _matmul4(
            _matmul4(model, _translate4(width, height)),
            _rotate_z4(180.0),
        )

    focal = 1.0 / tan(radians(LEGACY_NX_FOV_DEGREES / 2.0))
    eye_distance = focal * height / 2.0

    # Combined Perspective + projection Translate(-W/2,-H/2) + LookAt,
    # expressed directly in Qt top-left output coordinates.
    projection_to_qt = (
        (eye_distance, 0.0, -centre_x, 0.0),
        (0.0, -eye_distance, -centre_y, height * eye_distance),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, -1.0, eye_distance),
    )
    final = _matmul4(
        _matmul4(projection_to_qt, model),
        input_qt_to_gl,
    )

    fixed_z = float(z)
    # QTransform maps x'=(m11*x+m21*y+m31)/(m13*x+m23*y+m33)
    # and y'=(m12*x+m22*y+m32)/(same denominator).
    return (
        final[0][0],
        final[1][0],
        final[3][0],
        final[0][1],
        final[1][1],
        final[3][1],
        final[0][2] * fixed_z + final[0][3],
        final[1][2] * fixed_z + final[1][3],
        final[3][2] * fixed_z + final[3][3],
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
