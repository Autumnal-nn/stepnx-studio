from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected fragment not found in {path}: {old[:180]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Prime 1's live path_exeed consumer is source-exact and much simpler than the
# old viewport-normalized approximation. d is the signed pre-receptor path
# distance. P1 adds d, P2 subtracts d. No clamp or travel-height normalization.
replace_once(
    "src/stepnx/preview/visuals.py",
    '''def legacy_exceed_x_offset(\n    vertical_pixels: float,\n    field_width: float,\n    *,\n    from_right: bool,\n    travel_height: float,\n) -> float:\n    """Approximate the historical Exceed diagonal path.\n\n    Prime 2 and Andamiro's own modifier documentation confirm the semantic path:\n    notes approach the receptors diagonally from the opposite player's side.\n    The exact legacy affine coefficient has not yet been recovered from either\n    Prime 2 or PIUTESTER. Keep the approximation isolated here so it cannot be\n    mistaken for the source-exact Snake/Sink/Rise formulas.\n    """\n\n    span = max(1.0, abs(float(travel_height)))\n    progress_from_receptor = _clamp01(abs(float(vertical_pixels)) / span)\n    shift = float(field_width) * 0.5 * progress_from_receptor\n    return shift if from_right else -shift\n''',
    '''def legacy_exceed_x_offset(\n    beat_distance: float,\n    high_speed: float,\n    note_size: float,\n    *,\n    from_right: bool,\n) -> float:\n    """Port Prime/NXA's historical Exceed diagonal path.\n\n    Prime's live ``path_exeed`` branch at 0x0806D3E2..0x0806D426 forms\n    ``d = beatDistance * 60 * highSpeed``. The first five-lane bank receives\n    ``+d`` while the second receives ``-d`` relative to its normal bank origin.\n    The value is signed and intentionally unbounded: there is no viewport-height\n    normalization, half-field clamp, or absolute-value step in the runtime.\n\n    StepNX scales Prime's 60-unit lane/path pitch to the rendered note pitch,\n    preserving the original near-45-degree trajectory at native geometry.\n    """\n\n    native_distance = (\n        float(beat_distance) * PRIME2_PATH_UNIT * float(high_speed)\n    )\n    shift = native_distance * (float(note_size) / PRIME2_PATH_UNIT)\n    return shift if from_right else -shift\n''',
)

# Feed the recovered producer values rather than re-deriving a fake distance
# from screen Y. This is significant under speed changes and beyond one viewport.
replace_once(
    "src/stepnx/gui/preview_widget.py",
    '''        if self.command.exceed_mode or self.session.runtime_modifier.exceed:\n            anchor_y = self._base_screen_y_for_beat_distance(beat_distance)\n            if self.columns <= 5:\n                # A centred Single field still has one approach side per player:\n                # P1 enters from the right, P2 from the left. StartColumn >= 5 is\n                # the only chart-local P2 signal available to standalone preview.\n                from_right = self.start_column < 5\n            else:\n                centre_lane = (self.columns - 1) / 2.0\n                from_right = event.lane < centre_lane\n            offset += legacy_exceed_x_offset(\n                anchor_y - self._receptor_y(),\n                geometry.field_width,\n                from_right=from_right,\n                travel_height=float(self.height()),\n            )\n''',
    '''        if self.command.exceed_mode or self.session.runtime_modifier.exceed:\n            if self.columns <= 5:\n                # Prime stores one signed bank offset for the selected Single\n                # player. P1 approaches from the right; P2 approaches from left.\n                from_right = self.start_column < 5\n            else:\n                # Double keeps the two native five-lane bank origins: bank 0 gets\n                # +d and bank 1 gets -d. Do not normalize against field width.\n                from_right = event.lane < 5\n            offset += legacy_exceed_x_offset(\n                beat_distance,\n                self.session.high_speed,\n                geometry.note_size,\n                from_right=from_right,\n            )\n''',
)

# Export/import coverage for the recovered helper.
replace_once(
    "tests/unit/test_rise_visual_modifiers.py",
    '''    legacy_acc_dec_distance,\n    native_acc_dec_offset,\n''',
    '''    legacy_acc_dec_distance,\n    legacy_exceed_x_offset,\n    native_acc_dec_offset,\n''',
)

marker = '''    def test_prime2_sink_and_rise_are_opposite_z_depths(self) -> None:\n'''
insertion = '''    def test_prime_exceed_uses_signed_unbounded_path_distance(self) -> None:\n        # Prime 1 0x0806D3E2..0x0806D426: d = beat * 60 * highSpeed.\n        self.assertEqual(\n            legacy_exceed_x_offset(1.0, 1.0, 60.0, from_right=True),\n            60.0,\n        )\n        self.assertEqual(\n            legacy_exceed_x_offset(1.0, 1.0, 60.0, from_right=False),\n            -60.0,\n        )\n        self.assertEqual(\n            legacy_exceed_x_offset(2.0, 2.0, 60.0, from_right=True),\n            240.0,\n        )\n        # There is no old half-field clamp: distant notes can originate well\n        # outside the visible playfield and enter along the diagonal rail.\n        self.assertEqual(\n            legacy_exceed_x_offset(10.0, 1.0, 60.0, from_right=True),\n            600.0,\n        )\n        # The producer is signed; post-receptor distance crosses the rail rather\n        # than being forced back to the same side by abs().\n        self.assertEqual(\n            legacy_exceed_x_offset(-1.0, 1.0, 60.0, from_right=True),\n            -60.0,\n        )\n\n'''
replace_once("tests/unit/test_rise_visual_modifiers.py", marker, insertion + marker)

# Strengthen the existing Qt Single test and add the native Double bank rule.
replace_once(
    "tests/unit/test_qt_preview.py",
    '''                if widget is p1:\n                    self.assertGreater(widget._event_x_offset(event), 0.0)\n                else:\n                    self.assertLess(widget._event_x_offset(event), 0.0)\n''',
    '''                distance = widget._event_beat_distance(event)\n                expected = abs(distance) * widget.session.high_speed * widget._geometry().note_size\n                if widget is p1:\n                    self.assertAlmostEqual(widget._event_x_offset(event), expected)\n                else:\n                    self.assertAlmostEqual(widget._event_x_offset(event), -expected)\n''',
)

marker = '''    def test_throw_projects_depth_instead_of_adding_y_offset(self) -> None:\n'''
insertion = '''    def test_double_exceed_offsets_native_five_lane_banks_without_clamp(self) -> None:\n        base = self._widget("x")\n        widget = GameplayPreviewWidget(\n            base.stream,\n            columns=10,\n            start_column=0,\n            command=parse_gameplay_command("x"),\n        )\n        try:\n            widget.resize(640, 480)\n            source = widget.stream.events[0]\n            current_position = widget.stream.position_at(widget.chart_time_ms)\n            # Four beats at 2x is deliberately farther than the old half-field\n            # cap, reproducing EF029's off-screen diagonal entry condition.\n            widget.session.select_speed(2)\n            p1 = replace(source, lane=2, native_block_index=-1, position=current_position + 4.0)\n            p2 = replace(source, lane=7, native_block_index=-1, position=current_position + 4.0)\n            expected = 4.0 * widget.session.high_speed * widget._geometry().note_size\n            self.assertGreater(expected, widget._geometry().field_width * 0.5)\n            self.assertAlmostEqual(widget._event_x_offset(p1), expected)\n            self.assertAlmostEqual(widget._event_x_offset(p2), -expected)\n        finally:\n            widget.close()\n            base.close()\n\n'''
replace_once("tests/unit/test_qt_preview.py", marker, insertion + marker)

# Replace the now-obsolete approximation wording with the recovered live branch.
replace_once(
    "docs/PRIME2_PATH_MODIFIER_AUDIT.md",
    '''## Exceed\n\nPrime 2 and the PIUTESTER lineage confirm that Exceed/X Mode is a real horizontal path transform, not a lane permutation. The exact affine coefficient has not yet been recovered strongly enough to call the current 2D projection source-exact. The preview keeps that approximation isolated in `legacy_exceed_x_offset()` rather than contaminating Mirror, Under Attack, Drop, or Random semantics.\n''',
    '''## Exceed\n\nPrime 1's live `path_exeed` flag is the global byte at `0x0AC0255D`; it is set by the historical Exceed path option and consumed directly in the note renderer at `0x0806D3E2..0x0806D426`. The renderer forms `d = beatDistance * 60 * highSpeed`. Native five-lane bank 0 receives `+d`; bank 1 receives `-d` relative to its ordinary bank origin. Single retains the selected player's sign. There is no absolute value, viewport-height normalization, or half-field clamp.\n\nStepNX scales the native 60-unit path pitch by rendered note size and otherwise preserves that signed, unbounded producer exactly. This reproduces EF029/PIUTESTER's diagonal rail, including notes and items entering from well outside the visible field.\n''',
)
replace_once(
    "docs/PRIME2_PATH_MODIFIER_AUDIT.md",
    '''- Exceed as a separately labelled approximation until its exact legacy affine coefficient is recovered.\n''',
    '''- Exceed as the recovered signed Prime/NXA five-lane-bank path, with no viewport clamp.\n''',
)

# Handoff may still carry the old approximation warning. Update it only when the
# exact text exists; otherwise leave unrelated handoff material untouched.
handoff = Path("docs/RISE_RUNTIME_PARITY_HANDOFF.md")
if handoff.exists():
    text = handoff.read_text(encoding="utf-8")
    text = text.replace(
        "- Exceed remains an approximation because the exact historical affine coefficient is not recovered.\n",
        "- Exceed uses the recovered Prime/NXA signed five-lane-bank path: d = beatDistance * 60 * highSpeed, with no viewport clamp.\n",
    )
    handoff.write_text(text, encoding="utf-8")
