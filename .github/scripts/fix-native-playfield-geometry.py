from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected fragment not found in {path}: {old[:160]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Replace the old viewport-stretched geometry with Prime/NXA native logical
# coordinates. Lane pitch, path unit and sprite quad are independent runtime
# measures: 50, 60 and 64 respectively on the 640x480 SD renderer.
Path("src/stepnx/preview/geometry.py").write_text(
    '''from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from math import floor


LEGACY_LOGICAL_WIDTH = 640.0
LEGACY_LANE_PITCH = 50.0
LEGACY_PATH_UNIT = 60.0
LEGACY_NOTE_QUAD = 64.0

# Prime/NXA judge-line centres recovered from the native renderer.  Single and
# Versus share the side-bank centres; the distinction is whether one bank or
# two independent player banks are presented.  Double brings both banks toward
# the centre while Centered collapses them onto the common centre line.
LEGACY_SINGLE_P1_CENTER = 160.0
LEGACY_SINGLE_P2_CENTER = 480.0
LEGACY_DOUBLE_P1_CENTER = 194.0
LEGACY_DOUBLE_P2_CENTER = 446.0
LEGACY_CENTERED_CENTER = 320.0


class PlayfieldStyle(IntEnum):
    SINGLE = 0
    DOUBLE = 1
    VERSUS = 2
    CENTERED = 3


def default_playfield_style(columns: int) -> PlayfieldStyle:
    """Return StepNX's launch default when Division 200 is absent.

    The preview deliberately keeps the editor-friendly defaults: ordinary
    five-column charts are centered, while Half-Double and Double use the
    native Double presentation. Division Metadata 200 may override this per
    active block without changing authored lanes or judgment semantics.
    """

    return PlayfieldStyle.CENTERED if int(columns) <= 5 else PlayfieldStyle.DOUBLE


@dataclass(frozen=True, slots=True)
class PlayfieldGeometry:
    """Project Prime/NXA's logical playfield into a StepNX viewport.

    The historical renderer does not derive every measure from one cell size.
    At native SD geometry lane pitch is 50, legacy path distance uses 60-unit
    coordinates, and note/item quads are 64x64.  Wider StepNX windows keep those
    logical dimensions and merely center the 640-wide playfield; narrower
    windows scale the complete logical system uniformly so it remains usable.

    ``start_column`` is the NX absolute-lane origin. It matters for Half-Double
    (2..7), P2 Single (5..9), and any style override that collapses or separates
    the two native five-lane banks.
    """

    viewport_width: float
    columns: int
    render_style: PlayfieldStyle | None = None
    start_column: int = 0

    def __post_init__(self) -> None:
        if self.viewport_width <= 0:
            raise ValueError("playfield viewport width must be positive")
        if self.columns <= 0:
            raise ValueError("playfield requires at least one column")
        if self.render_style is not None:
            PlayfieldStyle(self.render_style)

    @property
    def style(self) -> PlayfieldStyle:
        return (
            default_playfield_style(self.columns)
            if self.render_style is None
            else PlayfieldStyle(self.render_style)
        )

    @property
    def logical_scale(self) -> float:
        return min(1.0, self.viewport_width / LEGACY_LOGICAL_WIDTH)

    @property
    def logical_left(self) -> float:
        return (self.viewport_width - LEGACY_LOGICAL_WIDTH * self.logical_scale) / 2.0

    def _logical_x(self, x: float) -> float:
        return self.logical_left + float(x) * self.logical_scale

    @property
    def lane_spacing(self) -> float:
        return LEGACY_LANE_PITCH * self.logical_scale

    @property
    def path_unit(self) -> float:
        """Rendered size of one native 60-unit legacy path measure."""

        return LEGACY_PATH_UNIT * self.logical_scale

    @property
    def note_size(self) -> float:
        """Rendered size of Prime/NXA's native 64x64 note/item quad."""

        return LEGACY_NOTE_QUAD * self.logical_scale

    @property
    def _selected_single_bank(self) -> int:
        return 1 if self.start_column >= 5 else 0

    def _bank_center_logical(self, bank: int) -> float:
        bank = 1 if int(bank) else 0
        style = self.style
        if style is PlayfieldStyle.CENTERED:
            return LEGACY_CENTERED_CENTER
        if style is PlayfieldStyle.SINGLE:
            return (
                LEGACY_SINGLE_P2_CENTER
                if self._selected_single_bank
                else LEGACY_SINGLE_P1_CENTER
            )
        if style is PlayfieldStyle.DOUBLE:
            return LEGACY_DOUBLE_P2_CENTER if bank else LEGACY_DOUBLE_P1_CENTER
        return LEGACY_SINGLE_P2_CENTER if bank else LEGACY_SINGLE_P1_CENTER

    def _absolute_lane(self, visual_lane: int) -> int:
        return int(self.start_column) + int(visual_lane)

    def _lane_components(self, visual_lane: int) -> tuple[int, int]:
        absolute = self._absolute_lane(visual_lane)
        bank = 0 if absolute < 5 else 1
        local_lane = absolute if bank == 0 else absolute - 5
        return bank, local_lane

    def lane_center(self, visual_lane: int) -> float:
        if not 0 <= int(visual_lane) < self.columns:
            raise IndexError(visual_lane)
        bank, local_lane = self._lane_components(int(visual_lane))
        centre = self._bank_center_logical(bank)
        logical_x = centre + (local_lane - 2) * LEGACY_LANE_PITCH
        return self._logical_x(logical_x)

    def lane_position(self, visual_lane_position: float) -> float:
        """Project a fractional lane coordinate through the selected layout.

        Snake Path interpolation is defined in lane-index space.  Interpolating
        between actual lane centres preserves the recovered 2-unit Double bank
        separation instead of silently reverting to a synthetic uniform field.
        """

        position = float(visual_lane_position)
        if self.columns == 1:
            return self.lane_center(0)
        if position <= 0.0:
            first = self.lane_center(0)
            second = self.lane_center(1)
            return first + position * (second - first)
        if position >= self.columns - 1:
            last = self.lane_center(self.columns - 1)
            previous = self.lane_center(self.columns - 2)
            return last + (position - (self.columns - 1)) * (last - previous)
        lower = int(floor(position))
        fraction = position - lower
        left = self.lane_center(lower)
        right = self.lane_center(lower + 1)
        return left + fraction * (right - left)

    @property
    def _visible_banks(self) -> tuple[int, ...]:
        if self.style in (PlayfieldStyle.SINGLE, PlayfieldStyle.CENTERED):
            return (self._selected_single_bank,)
        banks = []
        for lane in range(self.columns):
            bank, _ = self._lane_components(lane)
            if bank not in banks:
                banks.append(bank)
        return tuple(banks) or (self._selected_single_bank,)

    @property
    def panel_count(self) -> int:
        return len(self._visible_banks)

    @property
    def panel_width(self) -> float:
        return 5.0 * self.lane_spacing

    def panel_left(self, panel: int) -> float:
        if not 0 <= int(panel) < self.panel_count:
            raise IndexError(panel)
        bank = self._visible_banks[int(panel)]
        centre = self._logical_x(self._bank_center_logical(bank))
        return centre - self.panel_width / 2.0

    @property
    def left(self) -> float:
        centres = tuple(self.lane_center(lane) for lane in range(self.columns))
        return min(centres) - self.lane_spacing / 2.0

    @property
    def field_width(self) -> float:
        centres = tuple(self.lane_center(lane) for lane in range(self.columns))
        return max(centres) - min(centres) + self.lane_spacing
''',
    encoding="utf-8",
)

# Preview exports.
replace_once(
    "src/stepnx/preview/__init__.py",
    "from stepnx.preview.geometry import PlayfieldGeometry\n",
    "from stepnx.preview.geometry import (\n    PlayfieldGeometry,\n    PlayfieldStyle,\n    default_playfield_style,\n)\n",
)
replace_once(
    "src/stepnx/preview/__init__.py",
    '    "PlayfieldGeometry",\n',
    '    "PlayfieldGeometry",\n    "PlayfieldStyle",\n',
)
replace_once(
    "src/stepnx/preview/__init__.py",
    '    "earthworm_user_speed",\n',
    '    "default_playfield_style",\n    "earthworm_user_speed",\n',
)

# Correct Division Metadata 200's typed values to the four renderer states.
replace_once(
    "src/stepnx/core/profiles.py",
    '''        choices=tuple(\n            ValueChoice(value, label)\n            for value, label in enumerate(\n                ("Default", "Versus", "Double", "Single (collapsed)")\n            )\n        ),\n''',
    '''        choices=(\n            ValueChoice(0, "Single"),\n            ValueChoice(1, "Double"),\n            ValueChoice(2, "Versus"),\n            ValueChoice(3, "Centered"),\n        ),\n''',
)

# Wire active-block Division 200 into the renderer and keep legacy 60-unit
# paths independent from the 64-unit sprite quad.
replace_once(
    "src/stepnx/gui/preview_widget.py",
    "from stepnx.preview.geometry import PlayfieldGeometry\n",
    "from stepnx.preview.geometry import (\n    PlayfieldGeometry,\n    PlayfieldStyle,\n    default_playfield_style,\n)\n",
)
replace_once(
    "src/stepnx/gui/preview_widget.py",
    '''    def _geometry(self) -> PlayfieldGeometry:\n        return PlayfieldGeometry(max(1.0, float(self.width())), self.columns)\n''',
    '''    def _default_playfield_style(self) -> PlayfieldStyle:\n        return default_playfield_style(self.columns)\n\n    def _active_playfield_style(self) -> PlayfieldStyle:\n        """Resolve the active Prime-style judge-line layout.\n\n        Division Metadata 200 is block-local and must be re-evaluated whenever\n        native timing selects a different block. Missing/unknown values fall\n        back to StepNX's launch default without mutating chart structure.\n        """\n\n        default = self._default_playfield_style()\n        timing = self.stream.native_timing\n        if timing is None or not timing.blocks:\n            return default\n        state = timing.state_at(self._chart_time_ms)\n        block_id = timing.blocks[state.block_index].block_id\n        for current_block_id, params in self.stream.block_step_params:\n            if current_block_id != block_id:\n                continue\n            for param in params:\n                if param.metadata_id != 200:\n                    continue\n                try:\n                    return PlayfieldStyle(param.raw_value)\n                except ValueError:\n                    return default\n            break\n        return default\n\n    def _geometry(self) -> PlayfieldGeometry:\n        return PlayfieldGeometry(\n            max(1.0, float(self.width())),\n            self.columns,\n            self._active_playfield_style(),\n            self.start_column,\n        )\n''',
)
replace_once(
    "src/stepnx/gui/preview_widget.py",
    '''    def _lane_position_x(self, visual_lane_position: float) -> float:\n        """Project a fractional visual-lane coordinate into the playfield."""\n\n        if self.columns <= 1:\n            return self.lane_center(0)\n        lane_map = self._lane_map()\n        first = self.lane_center(lane_map[0])\n        second = self.lane_center(lane_map[1])\n        return first + float(visual_lane_position) * (second - first)\n''',
    '''    def _lane_position_x(self, visual_lane_position: float) -> float:\n        """Project a fractional visual-lane coordinate into the active layout."""\n\n        return self._geometry().lane_position(float(visual_lane_position))\n''',
)

widget = Path("src/stepnx/gui/preview_widget.py")
text = widget.read_text(encoding="utf-8")
text = text.replace(
    "                geometry.note_size,\n                legacy_mode,\n",
    "                geometry.path_unit,\n                legacy_mode,\n",
)
text = text.replace(
    "                geometry.note_size,\n                AccDecMode.LINEAR,\n",
    "                geometry.path_unit,\n                AccDecMode.LINEAR,\n",
)
text = text.replace(
    "prime2_snake_x_offset(beat_distance, geometry.note_size)",
    "prime2_snake_x_offset(beat_distance, geometry.path_unit)",
)
text = text.replace(
    "                geometry.note_size,\n                from_right=from_right,\n",
    "                geometry.path_unit,\n                from_right=from_right,\n",
)
text = text.replace(
    "                geometry.note_size / LEGACY_ACCDEC_PATH_UNIT\n",
    "                geometry.path_unit / LEGACY_ACCDEC_PATH_UNIT\n",
)
text = text.replace(
    "                from_right = event.lane < 5\n",
    "                from_right = (self.start_column + self._visual_lane(event.lane)) < 5\n",
)
widget.write_text(text, encoding="utf-8")

# Replace the old stretched-viewport geometry tests with source-anchored Prime
# coordinates and explicit style/default coverage.
test_preview = Path("tests/unit/test_preview.py")
text = test_preview.read_text(encoding="utf-8")
text = text.replace(
    "    PlayfieldGeometry,\n",
    "    PlayfieldGeometry,\n    PlayfieldStyle,\n",
    1,
)
start = text.index("class PreviewGeometryTests(unittest.TestCase):")
end = text.index("\n\nclass PreviewNoteSemanticsTests", start)
new_geometry_tests = '''class PreviewGeometryTests(unittest.TestCase):\n    def test_prime_sd_geometry_keeps_lane_path_and_quad_units_separate(self) -> None:\n        geometry = PlayfieldGeometry(640, 10, PlayfieldStyle.DOUBLE, 0)\n\n        self.assertEqual(geometry.lane_spacing, 50.0)\n        self.assertEqual(geometry.path_unit, 60.0)\n        self.assertEqual(geometry.note_size, 64.0)\n        self.assertEqual(\n            tuple(geometry.lane_center(lane) for lane in range(10)),\n            (94.0, 144.0, 194.0, 244.0, 294.0, 346.0, 396.0, 446.0, 496.0, 546.0),\n        )\n        self.assertEqual(geometry.panel_count, 2)\n        self.assertEqual(geometry.panel_left(0) + geometry.panel_width / 2.0, 194.0)\n        self.assertEqual(geometry.panel_left(1) + geometry.panel_width / 2.0, 446.0)\n        self.assertEqual(geometry.lane_position(4.5), 320.0)\n\n    def test_prime_styles_preserve_distinct_judge_line_origins(self) -> None:\n        versus = PlayfieldGeometry(640, 10, PlayfieldStyle.VERSUS, 0)\n        double = PlayfieldGeometry(640, 10, PlayfieldStyle.DOUBLE, 0)\n        single = PlayfieldGeometry(640, 10, PlayfieldStyle.SINGLE, 0)\n        centered = PlayfieldGeometry(640, 10, PlayfieldStyle.CENTERED, 0)\n\n        self.assertEqual(versus.lane_center(2), 160.0)\n        self.assertEqual(versus.lane_center(7), 480.0)\n        self.assertEqual(double.lane_center(2), 194.0)\n        self.assertEqual(double.lane_center(7), 446.0)\n        self.assertEqual(single.lane_center(2), 160.0)\n        self.assertEqual(single.lane_center(7), 160.0)\n        self.assertEqual(centered.lane_center(2), 320.0)\n        self.assertEqual(centered.lane_center(7), 320.0)\n        self.assertEqual(single.panel_count, 1)\n        self.assertEqual(centered.panel_count, 1)\n\n    def test_p2_single_uses_right_native_bank(self) -> None:\n        geometry = PlayfieldGeometry(640, 5, PlayfieldStyle.SINGLE, 5)\n        self.assertEqual(\n            tuple(geometry.lane_center(lane) for lane in range(5)),\n            (380.0, 430.0, 480.0, 530.0, 580.0),\n        )\n\n    def test_launch_defaults_are_centered_for_five_and_double_for_six_or_ten(self) -> None:\n        five = PlayfieldGeometry(640, 5, start_column=0)\n        six = PlayfieldGeometry(640, 6, start_column=2)\n        ten = PlayfieldGeometry(640, 10, start_column=0)\n\n        self.assertIs(five.style, PlayfieldStyle.CENTERED)\n        self.assertIs(six.style, PlayfieldStyle.DOUBLE)\n        self.assertIs(ten.style, PlayfieldStyle.DOUBLE)\n        self.assertEqual(five.lane_center(2), 320.0)\n        self.assertEqual(\n            tuple(six.lane_center(lane) for lane in range(6)),\n            (194.0, 244.0, 294.0, 346.0, 396.0, 446.0),\n        )\n\n    def test_wide_viewports_center_native_geometry_without_stretching_it(self) -> None:\n        geometry = PlayfieldGeometry(960, 10, PlayfieldStyle.DOUBLE, 0)\n        self.assertEqual(geometry.lane_spacing, 50.0)\n        self.assertEqual(geometry.path_unit, 60.0)\n        self.assertEqual(geometry.note_size, 64.0)\n        self.assertEqual(geometry.lane_center(0), 254.0)\n        self.assertEqual(geometry.lane_center(9), 706.0)\n\n    def test_narrow_viewports_scale_all_three_native_units_together(self) -> None:\n        geometry = PlayfieldGeometry(320, 10, PlayfieldStyle.DOUBLE, 0)\n        self.assertEqual(geometry.lane_spacing, 25.0)\n        self.assertEqual(geometry.path_unit, 30.0)\n        self.assertEqual(geometry.note_size, 32.0)\n'''
text = text[:start] + new_geometry_tests + text[end:]
test_preview.write_text(text, encoding="utf-8")

# Qt-level regressions: legacy curves use path units, not sprite size, and
# Division 200 directly selects the four active renderer layouts.
qt_test = Path("tests/unit/test_qt_preview.py")
text = qt_test.read_text(encoding="utf-8")
text = text.replace(
    "        RoutePolicy,\n",
    "        PlayfieldStyle,\n        RoutePolicy,\n",
    1,
)
text = text.replace(
    "                    widget._geometry().note_size,\n                    mode,\n",
    "                    widget._geometry().path_unit,\n                    mode,\n",
)
text = text.replace(
    "expected = abs(distance) * widget.session.high_speed * widget._geometry().note_size",
    "expected = abs(distance) * widget.session.high_speed * widget._geometry().path_unit",
)
text = text.replace(
    "expected = 4.0 * widget.session.high_speed * widget._geometry().note_size",
    "expected = 4.0 * widget.session.high_speed * widget._geometry().path_unit",
)
needle = "    def test_throw_projects_depth_instead_of_adding_y_offset(self) -> None:\n"
if needle not in text:
    raise SystemExit("qt insertion anchor not found")
new_test = '''    def test_division_200_selects_all_four_prime_render_styles(self) -> None:\n        base = self._widget()\n        try:\n            timing = base.stream.native_timing\n            self.assertIsNotNone(timing)\n            block_id = timing.blocks[0].block_id\n            expected = {\n                0: (PlayfieldStyle.SINGLE, 160.0, 160.0),\n                1: (PlayfieldStyle.DOUBLE, 194.0, 446.0),\n                2: (PlayfieldStyle.VERSUS, 160.0, 480.0),\n                3: (PlayfieldStyle.CENTERED, 320.0, 320.0),\n            }\n            for raw_value, (style, p1, p2) in expected.items():\n                stream = replace(\n                    base.stream,\n                    block_step_params=((block_id, (StepParam(200, raw_value),)),),\n                )\n                widget = GameplayPreviewWidget(\n                    stream,\n                    columns=10,\n                    start_column=0,\n                    command=parse_gameplay_command(""),\n                )\n                try:\n                    widget.resize(640, 480)\n                    self.assertIs(widget._active_playfield_style(), style)\n                    self.assertEqual(widget._geometry().lane_center(2), p1)\n                    self.assertEqual(widget._geometry().lane_center(7), p2)\n                finally:\n                    widget.close()\n        finally:\n            base.close()\n\n    def test_missing_division_200_uses_chart_width_defaults(self) -> None:\n        five = self._widget()\n        ten_base = self._widget()\n        ten = GameplayPreviewWidget(\n            ten_base.stream,\n            columns=10,\n            start_column=0,\n            command=parse_gameplay_command(""),\n        )\n        try:\n            five.resize(640, 480)\n            ten.resize(640, 480)\n            self.assertIs(five._active_playfield_style(), PlayfieldStyle.CENTERED)\n            self.assertIs(ten._active_playfield_style(), PlayfieldStyle.DOUBLE)\n        finally:\n            five.close()\n            ten.close()\n            ten_base.close()\n\n'''
text = text.replace(needle, new_test + needle, 1)
qt_test.write_text(text, encoding="utf-8")

# Document the recovered coordinate contract and the now-live Division 200
# projection. Keep R!SE-specific geometry separate from this Prime/NXA layer.
audit = Path("docs/PRIME2_PATH_MODIFIER_AUDIT.md")
text = audit.read_text(encoding="utf-8")
section = '''\n## Native playfield geometry and Division 200\n\nThe Prime/NXA renderer keeps three independent SD measures instead of deriving everything from a single cell size: lane pitch `50`, legacy path unit `60`, and note/item quad size `64`. The native 640-wide judge-line centres are `160/480` for side Single/Versus banks, `194/446` for Double, and `320` for Centered. StepNX now preserves those logical coordinates, centres them without stretching on wider preview windows, and scales the complete logical system only when the viewport is narrower than 640.\n\nThe four render states are explicit and do not rewrite authored columns or judgment lanes: `0=Single`, `1=Double`, `2=Versus`, `3=Centered`. Division Metadata `200` is resolved from the active block and therefore may switch presentation as native timing advances. When no `200` is present, StepNX intentionally keeps its authoring defaults: five-column charts launch Centered; six- and ten-column charts launch Double.\n\nThis separation also fixes legacy path composition: Exceed, historical Acceleration/Deceleration, and the Prime Snake path scale through the native 60-unit path measure, while note/item artwork continues to use the independent 64-unit quad. Half-Double bank selection uses `start_column + lane`, so its native 2..7 span crosses banks at the correct boundary.\n'''
if "## Native playfield geometry and Division 200" not in text:
    text += section
audit.write_text(text, encoding="utf-8")

handoff = Path("docs/RISE_RUNTIME_PARITY_HANDOFF.md")
text = handoff.read_text(encoding="utf-8")
line = "- Prime/NXA playfield geometry is now explicit: 50-unit lane pitch, 60-unit legacy path measure and 64-unit note quad, with Single/Double/Versus/Centered layouts and active-block Division 200 projection. Five-column launch defaults to Centered; six/ten-column launch defaults to Double.\n"
if line not in text:
    text += "\n" + line
handoff.write_text(text, encoding="utf-8")
