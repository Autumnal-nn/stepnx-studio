from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'expected fragment not found in {path}: {old[:180]!r}')
    file.write_text(text.replace(old, new, 1), encoding='utf-8')

# Exceed's renderer uses the same Prime/NXA linear path distance for Y that its
# horizontal branch uses for X. Legacy command Accel/Decel still wins when one
# of those modes is active, matching the native ordering before path_exeed.
replace_once(
    'src/stepnx/gui/preview_widget.py',
    '''        if legacy_mode is not AccDecMode.LINEAR:\n            return self._receptor_y() + legacy_acc_dec_distance(\n                beat_distance,\n                self.session.high_speed,\n                geometry.note_size,\n                legacy_mode,\n            )\n        native_y = native_line_y(\n''',
    '''        if legacy_mode is not AccDecMode.LINEAR:\n            return self._receptor_y() + legacy_acc_dec_distance(\n                beat_distance,\n                self.session.high_speed,\n                geometry.note_size,\n                legacy_mode,\n            )\n        if self.command.exceed_mode or self.session.runtime_modifier.exceed:\n            # Prime/NXA path_exeed shares its unbounded linear distance with\n            # both axes. Keeping R!SE's 65.647/72 Y projection here made the\n            # diagonal about ten percent too shallow even after X was fixed.\n            return self._receptor_y() + legacy_acc_dec_distance(\n                beat_distance,\n                self.session.high_speed,\n                geometry.note_size,\n                AccDecMode.LINEAR,\n            )\n        native_y = native_line_y(\n''',
)

# Strengthen the Double regression so EF029 cannot regress to a mixed legacy-X /
# modern-Y diagonal again.
replace_once(
    'tests/unit/test_qt_preview.py',
    '''            self.assertGreater(expected, widget._geometry().field_width * 0.5)\n            self.assertAlmostEqual(widget._event_x_offset(p1), expected)\n            self.assertAlmostEqual(widget._event_x_offset(p2), -expected)\n        finally:\n''',
    '''            self.assertGreater(expected, widget._geometry().field_width * 0.5)\n            self.assertAlmostEqual(widget._event_x_offset(p1), expected)\n            self.assertAlmostEqual(widget._event_x_offset(p2), -expected)\n            # path_exeed uses that same d for its vertical travel. The native\n            # trajectory is therefore 1:1 in rendered X/Y path units.\n            self.assertAlmostEqual(\n                widget._screen_y_for_beat_distance(4.0) - widget._receptor_y(),\n                expected,\n            )\n            self.assertAlmostEqual(\n                widget._event_x_offset(p1),\n                widget._screen_y_for_beat_distance(4.0) - widget._receptor_y(),\n            )\n        finally:\n''',
)

# Single gets the same invariant irrespective of P1/P2 horizontal sign.
replace_once(
    'tests/unit/test_qt_preview.py',
    '''                if widget is p1:\n                    self.assertAlmostEqual(widget._event_x_offset(event), expected)\n                else:\n                    self.assertAlmostEqual(widget._event_x_offset(event), -expected)\n        finally:\n''',
    '''                vertical = widget._event_y(event) - widget._receptor_y()\n                self.assertAlmostEqual(vertical, expected)\n                if widget is p1:\n                    self.assertAlmostEqual(widget._event_x_offset(event), expected)\n                    self.assertAlmostEqual(widget._event_x_offset(event), vertical)\n                else:\n                    self.assertAlmostEqual(widget._event_x_offset(event), -expected)\n                    self.assertAlmostEqual(widget._event_x_offset(event), -vertical)\n        finally:\n''',
)

# Document the final recovered composition and lock the already validated pieces.
audit = Path('docs/PRIME2_PATH_MODIFIER_AUDIT.md')
text = audit.read_text(encoding='utf-8')
old = '''Prime's live `path_exeed` branch at `0x0806D3E2..0x0806D426` forms the same linear path distance used by the normal vertical renderer:\n\n```text\nd = beatDistance * 60 * highSpeed\n```\n\nThe first native five-lane bank receives `+d` in X and the second receives `-d` relative to its normal bank origin. Single uses the selected player's bank sign even for its centre lane. The value is signed and unbounded: there is no viewport-height normalization, absolute-value conversion or half-field clamp. StepNX scales the native 60-unit path pitch to the rendered note pitch.\n'''
new = '''Prime's live `path_exeed` branch at `0x0806D3E2..0x0806D426` forms the same linear path distance used by the normal vertical renderer:\n\n```text\nd = beatDistance * 60 * highSpeed\n```\n\nThe first native five-lane bank receives `+d` in X and the second receives `-d` relative to its normal bank origin. Single uses the selected player's bank sign even for its centre lane. The normal Y renderer simultaneously uses `receptorY - d` in native bottom-left coordinates, so after StepNX's top-left conversion the rendered vertical travel is `+d`. Exceed is therefore a true 1:1 diagonal in native path units, not a horizontal modifier layered over R!SE's later 65.647/72 vertical projection.\n\nThe value is signed and unbounded: there is no viewport-height normalization, absolute-value conversion or half-field clamp. StepNX scales the native 60-unit path pitch to the rendered note pitch. Legacy Acceleration/Deceleration remains the earlier Y-path producer when explicitly active, matching the native ordering before `path_exeed`.\n'''
if old not in text:
    raise SystemExit('expected Exceed audit paragraph not found')
audit.write_text(text.replace(old, new, 1), encoding='utf-8')

handoff = Path('docs/RISE_RUNTIME_PARITY_HANDOFF.md')
text = handoff.read_text(encoding='utf-8')
needle = '- **Exceed** now uses Prime/NXA\'s recovered signed, unbounded `beatDistance * 60 * highSpeed` horizontal path, scaled to preview note pitch. Double preserves the two native five-lane bank signs and Single keeps the selected player side even for the centre lane.\n'
replacement = '- **Exceed** now uses Prime/NXA\'s recovered signed, unbounded `beatDistance * 60 * highSpeed` path on both axes: X receives the native player/bank sign while Y uses the same distance toward the receptor, producing the source-exact 1:1 diagonal. Double preserves the two native five-lane bank signs and Single keeps the selected player side even for the centre lane.\n'
if needle in text:
    text = text.replace(needle, replacement, 1)
elif 'source-exact 1:1 diagonal' not in text:
    text += '\n- Exceed correction: the recovered linear `d` is now shared by X and Y, removing the residual R!SE vertical-scale mismatch seen in EF029.\n'
handoff.write_text(text, encoding='utf-8')
