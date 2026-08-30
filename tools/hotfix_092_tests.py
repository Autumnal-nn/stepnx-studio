from pathlib import Path
import re


def repl(path, old, new, count=1):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    if s.count(old) != count:
        raise SystemExit(f"unexpected source shape in {path}: {old[:70]!r}")
    p.write_text(s.replace(old, new), encoding="utf-8")


def sub(path, pattern, new):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    s2, n = re.subn(pattern, new, s, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f"unexpected source shape in {path}: regex")
    p.write_text(s2, encoding="utf-8")

qt = "tests/unit/test_qt_preview.py"
repl(qt, "    def test_collapsed_long_draws_head_after_tail_in_gameplay_preview(self) -> None:\n", "    def test_overlapping_long_keeps_tail_then_head_order_in_gameplay_preview(self) -> None:\n")
sub(qt, r'''                with patch\.object\(\n                    widget,\n                    "_draw_asset",\n                    side_effect=lambda _painter, note, _rect: draw_order\.append\(\n                        note\.note_type\n                    \)\n                    or True,\n                \), patch\.object\(\n                    widget,\n                    "_projected_note_centre_and_extent",\n                    side_effect=lambda note: \(\n                        QPointF\(100\.0, 100\.0 if note\.note_type == 0x07 else 110\.0\),\n                        64\.0,\n                    \),\n                \):''', '''                with patch.object(\n                    widget,\n                    "_draw_asset",\n                    side_effect=lambda _painter, note, _rect: draw_order.append(\n                        note.note_type\n                    )\n                    or True,\n                ):''')
repl(qt, "            self.assertEqual(draw_order, [0x07])\n", "            self.assertEqual(draw_order, [0x0F, 0x07])\n")
sub(qt, r'''                with patch\.object\(\n                    widget,\n                    "_draw_asset",\n                    side_effect=lambda _painter, note, _rect: draw_order\.append\(note\.note_type\) or True,\n                \), patch\.object\(\n                    widget,\n                    "_projected_note_centre_and_extent",\n                    side_effect=lambda note: \(\n                        QPointF\(100\.0, 100\.0 if note\.note_type == 0x07 else 220\.0\),\n                        64\.0,\n                    \),\n                \):''', '''                with patch.object(\n                    widget,\n                    "_draw_asset",\n                    side_effect=lambda _painter, note, _rect: draw_order.append(note.note_type) or True,\n                ):''')

view = "tests/unit/test_qt_viewport.py"
repl(view, "    def test_low_projection_collapses_body_and_tail_to_head_in_editor(self) -> None:\n", "    def test_low_projection_keeps_tail_and_uses_head_last_order_in_editor(self) -> None:\n")
sub(view, r'''            collapsed = widget\._collapsed_hold_cells\(\)\n            self\.assertIn\(\(rows\[1\]\.stable_id, 0\), collapsed\)\n            self\.assertIn\(\(rows\[2\]\.stable_id, 0\), collapsed\)\n            self\.assertNotIn\(\(rows\[0\]\.stable_id, 0\), collapsed\)\n''', "")
repl(view, '''            self.assertIn(0x07, notes)\n            self.assertNotIn(0x0F, notes)\n            self.assertEqual(spans, [])\n''', '''            self.assertIn(0x07, notes)\n            self.assertIn(0x0F, notes)\n            self.assertEqual(notes[-1], 0x07)\n            self.assertLess(notes.index(0x0F), notes.index(0x07))\n''')

profiles = "tests/unit/test_profile_semantics.py"
repl(profiles, '''        definition = metadata_definition("fiesta2", MetadataScope.HEADER, 0x0003044F)\n        self.assertIsNotNone(definition)\n        self.assertEqual(definition.meta_id, 1103)\n        self.assertEqual(definition.kind, ValueKind.TRAILER_OFFSET)\n''', '''        definition = metadata_definition("fiesta2", MetadataScope.HEADER, 0x0003044F)\n        self.assertIsNotNone(definition)\n        self.assertEqual(definition.meta_id, 1103)\n        self.assertEqual(definition.kind, ValueKind.TRAILER_OFFSET)\n        prime_1100 = metadata_definition("prime2", MetadataScope.HEADER, 0x0005044C)\n        self.assertIsNotNone(prime_1100)\n        self.assertEqual(prime_1100.meta_id, 1100)\n        self.assertEqual(prime_1100.kind, ValueKind.TRAILER_OFFSET)\n        self.assertEqual(metadata_display_id("prime2", MetadataScope.HEADER, 0x0001044C), "1/1100")\n''')
repl(profiles, '''        capabilities = profile_capabilities("prime2")\n        self.assertIn("direct-noteskin-index", capabilities)\n''', '''        native_20 = metadata_definition("nxa-native", MetadataScope.HEADER, 20)\n        fiesta_20 = metadata_definition("fiesta2", MetadataScope.HEADER, 20)\n        prime_20 = metadata_definition("prime2", MetadataScope.HEADER, 20)\n        self.assertEqual(native_20.label, "BGA OFF / COSMOS")\n        self.assertNotEqual(native_20.kind, ValueKind.TRAILER_OFFSET)\n        self.assertEqual(fiesta_20.label, "BGA video resource (.V)")\n        self.assertEqual(fiesta_20.kind, ValueKind.TRAILER_OFFSET)\n        self.assertEqual(prime_20.label, "BGA video resource (.V)")\n        self.assertEqual(prime_20.kind, ValueKind.TRAILER_OFFSET)\n        self.assertIn("Prime uses the same later-generation", prime_20.description)\n\n        capabilities = profile_capabilities("prime2")\n        self.assertIn("direct-noteskin-index", capabilities)\n''')

modern = "tests/unit/test_modern_profile_extensions.py"
repl(modern, "    def test_step_artist_is_modern_only_trailer_metadata(self) -> None:\n", '''    def test_prime_trailer_registry_marks_1100_localized_and_keeps_header20(self) -> None:\n        field_1100 = trailer_field_definition("prime2", 1100)\n        field_1103 = trailer_field_definition("prime2", 1103)\n        field_20 = trailer_field_definition("prime2", 20)\n        self.assertIsNotNone(field_1100)\n        self.assertIsNotNone(field_1103)\n        self.assertIsNotNone(field_20)\n        self.assertTrue(field_1100.localized)\n        self.assertTrue(field_1103.localized)\n        self.assertEqual(field_20.label, "V resource override")\n        self.assertIsNone(trailer_field_definition("nxa-native", 20))\n\n    def test_step_artist_is_modern_only_trailer_metadata(self) -> None:\n''')

print("regression tests patched")
