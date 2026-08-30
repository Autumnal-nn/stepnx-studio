from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected fragment not found in {path}: {old[:180]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# External gameplay preview owns the moving chart view while it is open. Keep
# the authoring timeline synchronized in time, but suspend its expensive follow
# scroll/reprojection path. Preserve the user's previous Follow Chart state and
# restore it only after the last external preview is actually destroyed.
replace_once(
    "src/stepnx/gui/phase10_install.py",
    '''def _open_external_gameplay_preview(window) -> None:\n''',
    '''def _suspend_follow_chart_for_preview(window) -> None:\n    action = getattr(window, "follow_audio_action", None)\n    if action is None:\n        return\n    if getattr(window, "phase10_follow_chart_restore", None) is None:\n        window.phase10_follow_chart_restore = (\n            bool(action.isChecked()),\n            bool(action.isEnabled()),\n        )\n    action.setChecked(False)\n    action.setEnabled(False)\n\n\ndef _restore_follow_chart_after_preview(window) -> None:\n    if getattr(window, "phase10_preview_windows", ()):  # another preview owns it\n        return\n    restore = getattr(window, "phase10_follow_chart_restore", None)\n    if restore is None:\n        return\n    action = getattr(window, "follow_audio_action", None)\n    window.phase10_follow_chart_restore = None\n    if action is None:\n        return\n    checked, enabled = restore\n    action.setChecked(bool(checked))\n    action.setEnabled(bool(enabled))\n\n\ndef _open_external_gameplay_preview(window) -> None:\n''',
)
replace_once(
    "src/stepnx/gui/phase10_install.py",
    '''    preview.setFixedSize(640, 480)\n    preview.setWindowState(Qt.WindowState.WindowNoState)\n\n    window.phase10_preview_windows.append(preview)\n''',
    '''    preview.setFixedSize(640, 480)\n    preview.setWindowState(Qt.WindowState.WindowNoState)\n    # close() must destroy the standalone widget so ownership state is restored\n    # deterministically rather than waiting for Python/Qt object collection.\n    preview.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)\n\n    window.phase10_preview_windows.append(preview)\n    _suspend_follow_chart_for_preview(window)\n''',
)
replace_once(
    "src/stepnx/gui/phase10_install.py",
    '''        if preview in window.phase10_preview_windows:\n            window.phase10_preview_windows.remove(preview)\n        window.phase10_preview_snapshots.pop(preview, None)\n        # Restore metronome context to whichever authoring tab is active.\n''',
    '''        if preview in window.phase10_preview_windows:\n            window.phase10_preview_windows.remove(preview)\n        window.phase10_preview_snapshots.pop(preview, None)\n        _restore_follow_chart_after_preview(window)\n        # Restore metronome context to whichever authoring tab is active.\n''',
)
replace_once(
    "src/stepnx/gui/phase10_install.py",
    '''    window.phase10_preview_windows = []\n    window.phase10_raw_override = None\n''',
    '''    window.phase10_preview_windows = []\n    window.phase10_follow_chart_restore = None\n    window.phase10_raw_override = None\n''',
)

# A shaft is a visual interval, not a mandatory two-pixel marker. The old 2 px
# floor fabricated a body when low/zero Scroll projected both terminals to the
# same point. Also suppress the shaft while two still-visible terminal sprites
# overlap; once either terminal has aged out during an active hold, the body is
# allowed to remain so sustain feedback is not lost.
replace_once(
    "src/stepnx/gui/preview_widget.py",
    '''    def _draw_hold_shafts(\n        self,\n        painter: QPainter,\n        note_size: float,\n        visibility_filter: int,\n    ) -> None:\n''',
    '''    @staticmethod\n    def _hold_shaft_height(\n        y1: float,\n        y2: float,\n        rendered_note_size: float,\n        *,\n        head_terminal_visible: bool,\n        tail_terminal_visible: bool,\n    ) -> float:\n        span = abs(float(y2) - float(y1))\n        # Subpixel endpoint noise must not manufacture a visible long body.\n        if span <= 0.5:\n            return 0.0\n        # When both terminal quads are still present, there is no exposed shaft\n        # until their screen-space silhouettes stop overlapping.\n        if (\n            head_terminal_visible\n            and tail_terminal_visible\n            and span <= max(1.0, float(rendered_note_size))\n        ):\n            return 0.0\n        return span\n\n    def _draw_hold_shafts(\n        self,\n        painter: QPainter,\n        note_size: float,\n        visibility_filter: int,\n    ) -> None:\n''',
)
replace_once(
    "src/stepnx/gui/preview_widget.py",
    '''            centre = (x1 + x2) / 2.0\n            rendered_note_size = note_size * scale\n            if (\n                not self._effective_nx_mode()\n                and (max(y1, y2) < -100 or min(y1, y2) > self.height() + 100)\n            ):\n                continue\n            target = QRectF(\n                centre - rendered_note_size / 2,\n                min(y1, y2),\n                rendered_note_size,\n                max(2.0, abs(y2 - y1)),\n            )\n''',
    '''            centre = (x1 + x2) / 2.0\n            rendered_note_size = note_size * scale\n            head_visible = (\n                self.session.event_key(head) not in self.session.judgments\n                or head.time_ms >= self._chart_time_ms - 80.0\n            )\n            tail_visible = (\n                self.session.event_key(tail) not in self.session.judgments\n                or tail.time_ms >= self._chart_time_ms - 80.0\n            )\n            shaft_height = self._hold_shaft_height(\n                y1,\n                y2,\n                rendered_note_size,\n                head_terminal_visible=head_visible,\n                tail_terminal_visible=tail_visible,\n            )\n            if shaft_height <= 0.0:\n                continue\n            if (\n                not self._effective_nx_mode()\n                and (max(y1, y2) < -100 or min(y1, y2) > self.height() + 100)\n            ):\n                continue\n            target = QRectF(\n                centre - rendered_note_size / 2,\n                min(y1, y2),\n                rendered_note_size,\n                shaft_height,\n            )\n''',
)
replace_once(
    "src/stepnx/gui/preview_widget.py",
    '''                            width,\n                            max(2.0, abs(y2 - y1)),\n                        ),\n''',
    '''                            width,\n                            shaft_height,\n                        ),\n''',
)

# Regression coverage for preview ownership of Follow Chart.
test = Path("tests/unit/test_phase10_authoring.py")
text = test.read_text(encoding="utf-8")
anchor = '''    def test_external_preview_is_built_directly_without_base_tab_callback(self):\n'''
if anchor not in text:
    raise SystemExit("phase10 test anchor not found")
addition = '''    def test_external_preview_suspends_follow_chart_until_last_window_closes(self):\n        from stepnx.gui.phase10_install import (\n            _restore_follow_chart_after_preview,\n            _suspend_follow_chart_for_preview,\n        )\n\n        class Action:\n            def __init__(self, checked=True, enabled=True):\n                self.checked = checked\n                self.enabled = enabled\n\n            def isChecked(self):\n                return self.checked\n\n            def isEnabled(self):\n                return self.enabled\n\n            def setChecked(self, value):\n                self.checked = bool(value)\n\n            def setEnabled(self, value):\n                self.enabled = bool(value)\n\n        class Window:\n            pass\n\n        window = Window()\n        window.follow_audio_action = Action(checked=True, enabled=True)\n        first = object()\n        second = object()\n        window.phase10_preview_windows = [first]\n        window.phase10_follow_chart_restore = None\n\n        _suspend_follow_chart_for_preview(window)\n        self.assertFalse(window.follow_audio_action.isChecked())\n        self.assertFalse(window.follow_audio_action.isEnabled())\n        self.assertEqual(window.phase10_follow_chart_restore, (True, True))\n\n        window.phase10_preview_windows.append(second)\n        _suspend_follow_chart_for_preview(window)\n        self.assertEqual(window.phase10_follow_chart_restore, (True, True))\n\n        window.phase10_preview_windows.remove(first)\n        _restore_follow_chart_after_preview(window)\n        self.assertFalse(window.follow_audio_action.isChecked())\n        self.assertFalse(window.follow_audio_action.isEnabled())\n\n        window.phase10_preview_windows.clear()\n        _restore_follow_chart_after_preview(window)\n        self.assertTrue(window.follow_audio_action.isChecked())\n        self.assertTrue(window.follow_audio_action.isEnabled())\n        self.assertIsNone(window.phase10_follow_chart_restore)\n\n    def test_external_preview_close_has_deterministic_delete_on_close(self):\n        from pathlib import Path\n\n        source = (\n            Path(__file__).parents[2]\n            / "src"\n            / "stepnx"\n            / "gui"\n            / "phase10_install.py"\n        )\n        text = source.read_text(encoding="utf-8")\n        self.assertIn("Qt.WidgetAttribute.WA_DeleteOnClose", text)\n        self.assertIn("_suspend_follow_chart_for_preview(window)", text)\n        self.assertIn("_restore_follow_chart_after_preview(window)", text)\n\n'''
text = text.replace(anchor, addition + anchor, 1)
test.write_text(text, encoding="utf-8")

# Regression coverage for projected tiny/zero-scroll holds.
test = Path("tests/unit/test_qt_preview.py")
text = test.read_text(encoding="utf-8")
anchor = '''    def test_collapsed_long_draws_head_after_tail_in_gameplay_preview(self) -> None:\n'''
if anchor not in text:
    raise SystemExit("qt preview test anchor not found")
addition = '''    def test_collapsed_and_overlapping_long_terminals_do_not_fabricate_a_shaft(self) -> None:\n        widget = self._widget()\n        try:\n            size = widget._geometry().note_size\n            self.assertEqual(\n                widget._hold_shaft_height(100.0, 100.0, size, head_terminal_visible=True, tail_terminal_visible=True),\n                0.0,\n            )\n            self.assertEqual(\n                widget._hold_shaft_height(100.0, 100.4, size, head_terminal_visible=True, tail_terminal_visible=True),\n                0.0,\n            )\n            self.assertEqual(\n                widget._hold_shaft_height(100.0, 100.0 + size, size, head_terminal_visible=True, tail_terminal_visible=True),\n                0.0,\n            )\n            self.assertGreater(\n                widget._hold_shaft_height(100.0, 101.0 + size, size, head_terminal_visible=True, tail_terminal_visible=True),\n                0.0,\n            )\n            # If the head has already disappeared during an active sustain, a\n            # short real interval remains drawable instead of losing feedback.\n            self.assertEqual(\n                widget._hold_shaft_height(100.0, 110.0, size, head_terminal_visible=False, tail_terminal_visible=True),\n                10.0,\n            )\n        finally:\n            widget.close()\n\n'''
text = text.replace(anchor, addition + anchor, 1)
test.write_text(text, encoding="utf-8")

# Record the performance/visual policy in the audit handoff.
audit = Path("docs/RISE_RUNTIME_PARITY_HANDOFF.md")
text = audit.read_text(encoding="utf-8")
notes = '''\n- External preview ownership: while one or more standalone gameplay preview windows exist, Audio > Follow Chart is forced unchecked and disabled. Its exact prior checked/enabled state is restored when the final preview is destroyed. This removes authoring-follow repaint pressure from the shared Qt GUI thread without freezing the editor or audio transport.\n- Collapsed long rendering: the gameplay renderer no longer enforces a synthetic 2 px shaft. Projected zero/subpixel shafts are omitted; shafts are also omitted while both visible terminal quads overlap. Active sustains may still draw a short shaft after a terminal ages out. This is screen-space raster policy only and does not alter NX timing/Scroll semantics.\n'''
if "External preview ownership:" not in text:
    text += notes
audit.write_text(text, encoding="utf-8")
