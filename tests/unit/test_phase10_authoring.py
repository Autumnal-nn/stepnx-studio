from __future__ import annotations

import unittest


class LegacyImporterApiTests(unittest.TestCase):
    def test_legacy_importer_api_is_available(self):
        from stepnx.importers.legacy import (
            LegacyBlock,
            LegacyContainer,
            load_legacy,
            project_nx20,
        )

        self.assertIsNotNone(LegacyBlock)
        self.assertIsNotNone(LegacyContainer)
        self.assertTrue(callable(load_legacy))
        self.assertTrue(callable(project_nx20))


class EngineProfileTests(unittest.TestCase):
    def test_fiesta2_and_prime2_profiles_are_registered(self):
        from stepnx.core.profiles import get_profile, profile_capabilities

        self.assertEqual(get_profile("fiesta2").label, "Fiesta")
        self.assertEqual(get_profile("prime2").label, "Prime+")
        self.assertIn("items-21-23", profile_capabilities("fiesta2"))
        self.assertIn("items-21-23", profile_capabilities("prime2"))


try:
    import PySide6  # noqa: F401
except ImportError:
    _HAS_QT = False
else:
    _HAS_QT = True


@unittest.skipUnless(_HAS_QT, "PySide6 is required for Phase-10 GUI adapter tests")
class Phase10AdapterTests(unittest.TestCase):
    def test_stepedit_measure_beat_row_notation(self):
        from stepnx.gui.phase10_install import _format_mbr, _parse_mbr

        self.assertEqual(_format_mbr(3520, 8, 4), "110|0|0")
        self.assertEqual(_parse_mbr("110|0|0", 8, 4), 3520)
        self.assertEqual(_parse_mbr("1|2|3", 8, 4), 51)

    def test_measure_beat_row_rejects_out_of_range_subfields(self):
        from stepnx.gui.phase10_install import _parse_mbr

        with self.assertRaises(ValueError):
            _parse_mbr("1|4|0", 8, 4)
        with self.assertRaises(ValueError):
            _parse_mbr("1|0|8", 8, 4)

    def test_chart_audio_policy_excludes_wav(self):
        from stepnx.gui.phase10_install import _ALLOWED_CHART_AUDIO

        self.assertEqual(_ALLOWED_CHART_AUDIO, frozenset({".mp3", ".aud", ".a"}))
        self.assertNotIn(".wav", _ALLOWED_CHART_AUDIO)

    def test_nxa_patched_special_item_raw_matches_documented_cells(self):
        from stepnx.gui.phase10_install import _special_item_raw

        self.assertEqual(_special_item_raw(0), bytes.fromhex("01 03 40 00"))
        self.assertEqual(_special_item_raw(20), bytes.fromhex("01 03 54 00"))
        self.assertEqual(_special_item_raw(27), bytes.fromhex("01 03 5B 00"))
        self.assertEqual(_special_item_raw(28), bytes.fromhex("01 03 5C 00"))
        self.assertEqual(_special_item_raw(30), bytes.fromhex("01 03 5E 00"))
        self.assertEqual(_special_item_raw(96), bytes.fromhex("01 03 A0 00"))
        with self.assertRaises(ValueError):
            _special_item_raw(97)

    def test_nxa_patched_number_block_raw_matches_documented_examples(self):
        from stepnx.gui.phase10_install import _number_block_raw

        examples = {
            18: "02 03 76 01",
            21: "02 03 79 01",
            22: "02 03 7A 01",
            23: "02 03 7B 01",
            24: "02 03 7C 01",
            28: "02 03 80 01",
        }
        for number, raw in examples.items():
            with self.subTest(number=number):
                self.assertEqual(_number_block_raw(number), bytes.fromhex(raw))

    def test_type_tables_use_known_normal_item_and_division_names(self):
        from stepnx.gui.phase10_install import _DIVISION_TYPES, _NORMAL_ITEM_TYPES

        items = dict(_NORMAL_ITEM_TYPES)
        self.assertEqual(items[0], "Action")
        self.assertEqual(items[1], "Shield")
        self.assertEqual(items[21], "Random Velocity")
        self.assertEqual(items[22], "Death / Nuclear")
        self.assertEqual(items[23], "Hyper Potion")
        self.assertEqual(
            dict(_DIVISION_TYPES),
            {0: "Step G", 1: "Step W", 2: "Step A", 3: "Step B", 4: "Step C"},
        )

    def test_item_type_gating_matches_engine_profiles(self):
        from stepnx.gui.phase10_install import _item_types_for_profile

        native = dict(_item_types_for_profile("nxa-native"))
        fiesta = dict(_item_types_for_profile("fiesta2"))
        prime = dict(_item_types_for_profile("prime2"))
        patched = dict(_item_types_for_profile("nxa-step5-patched"))
        self.assertEqual(max(native), 20)
        for table in (fiesta, prime, patched):
            self.assertEqual(table[21], "Random Velocity")
            self.assertEqual(table[22], "Death / Nuclear")
            self.assertEqual(table[23], "Hyper Potion")

    def test_source_slot_and_brain_code_share_raw_byte_without_overlap(self):
        from stepnx.gui.phase10_install import _compose_context_byte

        self.assertEqual(_compose_context_byte(0, 0), 0x00)
        self.assertEqual(_compose_context_byte(0, 6), 0x06)
        self.assertEqual(_compose_context_byte(0, 7), 0x07)
        self.assertEqual(_compose_context_byte(3, 0), 0xC0)
        self.assertEqual(_compose_context_byte(3, 7), 0xC7)
        with self.assertRaises(ValueError):
            _compose_context_byte(4, 0)
        with self.assertRaises(ValueError):
            _compose_context_byte(0, 64)

    def test_special_and_number_encodings_preserve_source_slot_bits(self):
        from stepnx.gui.phase10_install import _number_block_raw, _special_item_raw

        self.assertEqual(_special_item_raw(20, 3), bytes.fromhex("01 03 54 C0"))
        self.assertEqual(_number_block_raw(18, 3), bytes.fromhex("02 03 76 C1"))

    def test_regular_erase_stays_canonical_zero_even_with_raw3_controls(self):
        from stepnx.authoring import NoteFunction, NoteTool, NoteVisibility
        from stepnx.gui.phase10_install import _regular_note_raw

        class Spin:
            def value(self):
                return 3

        class Combo:
            def currentData(self):
                return 7

        class Window:
            phase10_player_slot = Spin()
            phase10_brain_code = Combo()

        self.assertEqual(
            _regular_note_raw(
                Window(),
                NoteTool.ERASE,
                0,
                NoteFunction.NORMAL,
                NoteVisibility.VISIBLE,
            ),
            b"\0\0\0\0",
        )

    def test_basic_brain_code_choices_only_expose_confirmed_values(self):
        from stepnx.gui.phase10_install import _BASIC_BRAIN_CODES, _BRAIN_CODE_LABELS

        self.assertEqual(_BASIC_BRAIN_CODES, (0, 1, 6, 7))
        self.assertEqual(set(_BRAIN_CODE_LABELS), {0, 1, 6, 7})
        self.assertEqual(_BRAIN_CODE_LABELS[6], "Incorrect / X")
        self.assertEqual(_BRAIN_CODE_LABELS[7], "Correct / O")

    def test_source_slot_advanced_state_overrides_legacy_widget_fallback(self):
        from stepnx.gui.phase10_install import _selected_player_slot

        class Spin:
            def value(self):
                return 1

        class Window:
            phase10_source_slot_value = 3
            phase10_player_slot = Spin()

        self.assertEqual(_selected_player_slot(Window()), 3)

    def test_special_atlas_uses_row_major_linear_cell_numbers(self):
        from stepnx.gui.phase10_timeline import Phase10TimelineWidget

        class Atlas:
            columns = 32
            rows = 3

        self.assertEqual(Phase10TimelineWidget._phase10_special_tile(Atlas(), 0), (0, 0))
        self.assertEqual(Phase10TimelineWidget._phase10_special_tile(Atlas(), 31), (31, 0))
        self.assertEqual(Phase10TimelineWidget._phase10_special_tile(Atlas(), 32), (0, 1))
        self.assertEqual(Phase10TimelineWidget._phase10_special_tile(Atlas(), 95), (31, 2))
        self.assertIsNone(Phase10TimelineWidget._phase10_special_tile(Atlas(), 96))

    def test_external_preview_is_built_directly_without_base_tab_callback(self):
        from pathlib import Path

        source = (
            Path(__file__).parents[2]
            / "src"
            / "stepnx"
            / "gui"
            / "phase10_install.py"
        )
        text = source.read_text(encoding="utf-8")
        self.assertIn("def _open_external_gameplay_preview(window)", text)
        self.assertIn("preview = Phase10GameplayPreviewWidget(", text)
        self.assertIn("preview.setFixedSize(640, 480)", text)
        self.assertIn("preview.showNormal()", text)
        self.assertNotIn("[StepNX Preview] direct create", text)
        self.assertIn("preview_menu.removeAction(old_preview_action)", text)
        self.assertIn("old_preview_action.deleteLater()", text)
        self.assertNotIn("base preview action did not create a tab", text)
        self.assertNotIn("original_preview = window._open_gameplay_preview", text)
        self.assertNotIn("window.open_preview_action.triggered.disconnect()", text)

    def test_gameplay_preview_uses_native_base_velocity_projection(self):
        from pathlib import Path

        source = (
            Path(__file__).parents[2]
            / "src"
            / "stepnx"
            / "gui"
            / "preview_widget.py"
        )
        text = source.read_text(encoding="utf-8")
        self.assertIn("native_line_y(", text)
        self.assertIn("native_screen_y(", text)
        self.assertIn(
            "base_velocity = native_base_velocity_pixels(geometry.note_size)",
            text,
        )
        self.assertIn("self.session.high_speed", text)
        self.assertNotIn("scroll_pitch = self._geometry().lane_spacing", text)
        self.assertNotIn("** 1.08", text)
        self.assertNotIn("** 0.92", text)

    def test_gameplay_preview_culls_events_after_chart_end(self):
        from pathlib import Path

        source = (
            Path(__file__).parents[2]
            / "src"
            / "stepnx"
            / "gui"
            / "preview_widget.py"
        )
        text = source.read_text(encoding="utf-8")
        self.assertIn(
            "self._chart_time_ms > self.stream.duration_ms + 250.0",
            text,
        )

    def test_audio_autoload_requires_exact_sibling_folder_mp3(self):
        from pathlib import Path

        source = (
            Path(__file__).parents[2]
            / "src"
            / "stepnx"
            / "gui"
            / "app.py"
        )
        text = source.read_text(encoding="utf-8")
        self.assertIn(
            'preferred_audio_name = f"{self.workspace.root.name}.mp3".casefold()',
            text,
        )
        self.assertIn(
            "for candidate in self.workspace.root.parent.iterdir()",
            text,
        )
        self.assertIn(
            "candidate.name.casefold() == preferred_audio_name",
            text,
        )
        self.assertNotIn(
            "self._load_audio(self.workspace.audio_candidates[0].path)",
            text,
        )

    def test_toggle_and_legacy_tap_are_distinct_labels(self):
        from stepnx.gui.phase10_install import _tool_mode

        class Combo:
            def __init__(self, text, data):
                self._text = text
                self._data = data

            def currentText(self):
                return self._text

            def currentData(self):
                return self._data

        class Window:
            pass

        window = Window()
        window.tool_combo = Combo("Toggle", "tap")
        self.assertEqual(_tool_mode(window), "toggle")
        window.tool_combo = Combo("Tap", "tap")
        self.assertEqual(_tool_mode(window), "tap")


if __name__ == "__main__":
    unittest.main()
