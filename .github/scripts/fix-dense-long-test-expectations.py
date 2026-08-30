from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected fragment not found in {path}: {old!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# The production optimization caches the immutable stream duration once at
# widget construction. Preserve the intent of this older source-level guard
# without requiring a deliberately repeated O(n) RuntimeEventStream.duration_ms
# property lookup on every paint.
replace_once(
    "tests/unit/test_phase10_authoring.py",
    '''        self.assertIn(\n            "self._chart_time_ms > self.stream.duration_ms + 250.0",\n            text,\n        )\n''',
    '''        self.assertIn(\n            "self._chart_time_ms > self._duration_ms + 250.0",\n            text,\n        )\n        self.assertIn("self._duration_ms = stream.duration_ms", text)\n''',
)

# The ordinary fixture legitimately contains one transition-visibility note,
# so it may need one screen-space mask layer. Use Non-Step for the explicit
# "no layer can contribute" case while retaining the one-cull-per-paint check.
replace_once(
    "tests/unit/test_qt_preview.py",
    '''    def test_paint_culls_render_events_once_and_skips_empty_visibility_layers(self) -> None:\n        widget = self._widget()\n''',
    '''    def test_paint_culls_render_events_once_and_skips_empty_visibility_layers(self) -> None:\n        widget = self._widget("n")\n''',
)
