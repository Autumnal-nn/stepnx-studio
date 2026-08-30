from __future__ import annotations

from pathlib import Path
import re


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected fragment not found in {path}: {old[:160]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_region(path: str, pattern: str, replacement: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, lambda _: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"expected one region in {path}, found {count}")
    file.write_text(new_text, encoding="utf-8")


legacy = "src/stepnx/preview/legacy_render.py"
replace_once(legacy, "from math import radians, tan\n", "from math import cos, radians, sin, tan\n")
replace_once(
    legacy,
    """LEGACY_NX_FOV_DEGREES = 75.0\nLEGACY_NX_SCALE = 1.5\nLEGACY_NX_ROTATE_DEGREES = -120.0\nLEGACY_NX_DROP_ROTATE_DEGREES = -60.0\nLEGACY_NX_YZ_COUPLING = 1.299038105676658\nLEGACY_NX_Z_OFFSET = -519.6152422706632\n""",
    """LEGACY_NX_FOV_DEGREES = 75.0\nLEGACY_NX_SCALE = 1.5\nLEGACY_NX_SHALLOW_ROTATE_DEGREES = -60.0\nLEGACY_NX_STEEP_ROTATE_DEGREES = -120.0\n""",
)

nx_impl = r'''def _matmul4(
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
'''
replace_region(
    legacy,
    r"def _matmul3\(.*?\n\ndef legacy_nx_project_point",
    nx_impl + "\n\ndef legacy_nx_project_point",
)

# Replace the old self-consistent-but-wrong projection expectations with four
# native branch anchors recovered independently from Prime and NXA.
test_file = "tests/unit/test_rise_visual_modifiers.py"
new_test = r'''    def test_nx_mode_projection_matches_all_native_prime_nxa_branches(self) -> None:
        self.assertEqual(LEGACY_NX_FOV_DEGREES, 75.0)
        receptor = (320.0, 82.0)
        future = (200.0, 300.0)
        expected = {
            (False, False): ((320.0, 240.64634479047592), (192.82099219220635, 356.5807571571442)),
            (True, False): ((320.0, 239.35365520952405), (192.82099219220632, 123.4192428428558)),
            (False, True): ((320.0, 239.353655209524), (447.17900780779365, 123.41924284285578)),
            (True, True): ((320.0, 240.64634479047598), (447.17900780779365, 356.5807571571443)),
        }
        for (drop, under_attack), (expected_receptor, expected_future) in expected.items():
            with self.subTest(drop=drop, under_attack=under_attack):
                projected_receptor = legacy_nx_project_point(
                    *receptor, 640.0, 480.0, drop=drop, under_attack=under_attack
                )
                projected_future = legacy_nx_project_point(
                    *future, 640.0, 480.0, drop=drop, under_attack=under_attack
                )
                self.assertAlmostEqual(projected_receptor[0], expected_receptor[0], places=5)
                self.assertAlmostEqual(projected_receptor[1], expected_receptor[1], places=5)
                self.assertAlmostEqual(projected_future[0], expected_future[0], places=5)
                self.assertAlmostEqual(projected_future[1], expected_future[1], places=5)

        doubled = legacy_nx_project_point(640.0, 164.0, 1280.0, 960.0)
        self.assertAlmostEqual(doubled[0], 640.0, places=5)
        self.assertAlmostEqual(doubled[1], 481.29268958095184, places=5)
'''
replace_region(
    test_file,
    r"    def test_nx_mode_projection_matches_nxa_prime_pipeline\(self\) -> None:.*?\n\n\nclass SequenceZoneTransformTests",
    new_test + "\n\n\nclass SequenceZoneTransformTests",
)

# Strengthen Qt integration against the exact branch table, not merely helper
# self-consistency.
qt_test = "tests/unit/test_qt_preview.py"
new_qt = r'''    def test_nx_mode_qtransform_matches_all_recovered_native_branches(self) -> None:
        cases = (
            ("^", False, False),
            ("^!", True, False),
            ("^u", False, True),
            ("^u!", True, True),
        )
        for command, drop, under_attack in cases:
            widget = self._widget(command)
            try:
                widget.resize(640, 480)
                self.assertTrue(widget._effective_nx_mode())
                transform = widget._playfield_transform()
                for point in (QPointF(320.0, 82.0), QPointF(200.0, 300.0)):
                    mapped = transform.map(point)
                    expected_x, expected_y = legacy_nx_project_point(
                        point.x(),
                        point.y(),
                        640.0,
                        480.0,
                        drop=drop,
                        under_attack=under_attack,
                    )
                    self.assertAlmostEqual(mapped.x(), expected_x, places=5)
                    self.assertAlmostEqual(mapped.y(), expected_y, places=5)
                # Every native NX branch keeps the receptor on the central horizon.
                receptor = transform.map(QPointF(320.0, 82.0))
                self.assertLess(abs(receptor.y() - 240.0), 1.0)
            finally:
                widget.close()
'''
replace_region(
    qt_test,
    r"    def test_nx_mode_qtransform_matches_recovered_projection\(self\) -> None:.*?\n\n    def test_event_culling_uses_chart_time_without_mutating_stream",
    new_qt + "\n\n    def test_event_culling_uses_chart_time_without_mutating_stream",
)

# Correct the audit's branch direction and UA composition. Visibility and the
# locked 221/222 section are intentionally untouched.
doc = "docs/PRIME2_PATH_MODIFIER_AUDIT.md"
replace_once(
    doc,
    """Header 22 and COMMAND `^` feed the same **NX Mode** state. Both supplied executables select a 75-degree perspective instead of the normal 90-degree projection. NXA then applies the recovered 1.5 scale and X-axis tilt: -120 degrees in the normal branch and -60 degrees in the Drop branch. StepNX collapses each fixed-Z plane to the equivalent projective homography, so arrow artwork and long-note geometry are warped rather than merely repositioned. Sink/Rise uses the recovered NX-specific +/-300 Z branch.\n\nThe standalone preview preserves Under Attack as the already-validated independent 180-degree field transform before the NX homography. The native combined UA+NX branch was not separately used as an arbiter in this pass.\n""",
    """Header 22 and COMMAND `^` feed the same **NX Mode** state. Both supplied executables select a 75-degree perspective instead of the normal 90-degree projection. The perspective helper derives camera distance from viewport **height**, translates projection by `(-W/2,-H/2)`, and then uses a +Y `LookAt`. The four native branches are explicit: plain NX uses `Rx(-60)` plus centered `Scale(1.5,+1.5,1.5)`; NX+Drop uses `T(0,H)`, `Rx(-120)` and the same positive-Y scale; NX+Under Attack uses `T(0,H)`, `Rx(-120)`, centered `Scale(1.5,-1.5,1.5)`, then the native UA `T(W,H)/Rz(180)` tail; NX+UA+Drop uses `Rx(-60)`, the negative-Y scale, then that same UA tail. StepNX collapses each fixed-Z plane to the exactly equivalent projective homography, including Qt top-left to OpenGL bottom-left conversion. Sink/Rise uses the recovered NX-specific +/-300 Z branch.\n\nPrime anchors: no-UA NX branch `0x080ae1de`, UA+NX branch `0x080ae0bb`, shared tilt targets near `0x080af5a3/0x080af5cc`, perspective helper `0x08087350`. NXA independently reproduces the same branch structure around `0x0808edc6`, `0x0808f362`, `0x0808fb84` and `0x0808fbce`.\n""",
)
