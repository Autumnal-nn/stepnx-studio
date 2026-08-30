from pathlib import Path
import re


def repl(path, old, new, count=1):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    if s.count(old) != count:
        raise SystemExit(f"unexpected source shape in {path}: {old[:60]!r}")
    p.write_text(s.replace(old, new), encoding="utf-8")


def sub(path, pattern, new):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    s2, n = re.subn(pattern, new, s, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"unexpected source shape in {path}: regex")
    p.write_text(s2, encoding="utf-8")

preview = "src/stepnx/gui/preview_widget.py"
sub(preview, r"\n    def _projected_note_centre_and_extent\(.*?\n    def _draw_note_group\(", "\n    def _draw_note_group(")
repl(preview, '''        # The native game collapses a hold whose complete projected length fits\n        # underneath one terminal into the head silhouette. Shaft is already\n        # suppressed by _hold_shaft_height; suppress the covered tail too.\n        drawable_notes = tuple(\n            note for note in notes if not self._collapsed_hold_tail(note)\n        )\n        ordered_notes = tuple(\n            note for note in drawable_notes if note.note_type != 0x7\n        ) + tuple(note for note in drawable_notes if note.note_type == 0x7)\n''', '''        # Native collapse comes from draw order, not a note-size threshold.\n        # Keep the tail: a truly coincident head covers it; a merely short hold\n        # can still expose the part of the tail that lies outside the head.\n        ordered_notes = tuple(\n            note for note in notes if note.note_type != 0x7\n        ) + tuple(note for note in notes if note.note_type == 0x7)\n''')

timeline = "src/stepnx/gui/timeline_widget.py"
# Keep the now-unused cache member and its invalidations in this minimal hotfix.
# Removing those lines changes block shapes in wheel/set-playback code for no
# functional benefit; they can be cleaned up in a later refactor.
sub(timeline, r"\n    def _collapsed_hold_cells\(self\) -> frozenset\[tuple\[int, int\]\]:.*?\n    def _draw_segment\(", "\n    def _draw_segment(")
repl(timeline, "        collapsed_hold_cells = self._collapsed_hold_cells()\n", "")
repl(timeline, '''                    if (row.stable_id, lane) in collapsed_hold_cells:\n                        if self._playback_active:\n                            flush_body(lane)\n                        continue\n''', "")

print("renderer patch applied")