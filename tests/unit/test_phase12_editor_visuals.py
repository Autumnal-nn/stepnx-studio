from __future__ import annotations

import unittest

from stepnx.authoring.tools import NoteFunction, NoteTool, NoteVisibility, note_tool_raw
from stepnx.gui.phase10_preview import _phase10_noteskin_terminal_row
from stepnx.gui.phase12_editor_note_visuals import (
    _GHOST_OUTLINE_RADIUS,
    _is_roll_head,
    _profile_supports_low_visibility,
    _should_apply_editor_mask,
    _visibility_alpha,
)


class Phase12EditorLongVisualTests(unittest.TestCase):
    def test_roll_is_the_long_head_with_sustain_bit_cleared(self) -> None:
        self.assertFalse(_is_roll_head(bytes.fromhex("37 02 00 00")))
        self.assertTrue(_is_roll_head(bytes.fromhex("47 05 00 00")))
        self.assertFalse(_is_roll_head(bytes.fromhex("57 03 00 00")))
        self.assertFalse(_is_roll_head(bytes.fromhex("43 03 00 00")))

    def test_roll_tool_emits_official_no_sustain_head_family(self) -> None:
        self.assertEqual(note_tool_raw(NoteTool.ROLL, 0), bytes.fromhex("47 03 00 00"))
        self.assertEqual(
            note_tool_raw(
                NoteTool.ROLL,
                2,
                NoteFunction.NORMAL,
                NoteVisibility.APPEAR_LOW,
            ),
            bytes.fromhex("47 05 02 00"),
        )

    def test_visibility_filters_live_on_tap_or_head_not_body_or_tail(self) -> None:
        self.assertTrue(_should_apply_editor_mask(bytes.fromhex("47 05 00 00")))
        self.assertTrue(_should_apply_editor_mask(bytes.fromhex("23 04 02 80")))
        self.assertFalse(_should_apply_editor_mask(bytes.fromhex("4B 05 00 00")))
        self.assertFalse(_should_apply_editor_mask(bytes.fromhex("4F 05 00 00")))

    def test_low_visibility_modes_keep_their_runtime_direction(self) -> None:
        self.assertEqual(_visibility_alpha(5, 0.0), 255)  # AppearLow
        self.assertEqual(_visibility_alpha(5, 1.0), 0)
        self.assertEqual(_visibility_alpha(4, 0.0), 0)  # VanishLow
        self.assertEqual(_visibility_alpha(4, 1.0), 255)

    def test_low_visibility_choices_are_nxa_only(self) -> None:
        self.assertTrue(_profile_supports_low_visibility("nxa-native"))
        self.assertTrue(_profile_supports_low_visibility("nxa-step5-patched"))
        self.assertFalse(_profile_supports_low_visibility("fiesta2"))
        self.assertFalse(_profile_supports_low_visibility("prime2"))

    def test_ghost_outline_is_three_pixels_for_editor_legibility(self) -> None:
        self.assertEqual(_GHOST_OUTLINE_RADIUS, 3)

    def test_preview_uses_normal_art_for_ghost_tap_and_roll_art_for_no_sustain_head(self) -> None:
        self.assertEqual(_phase10_noteskin_terminal_row(bytes.fromhex("23 04 02 80")), 1)
        self.assertEqual(_phase10_noteskin_terminal_row(bytes.fromhex("37 02 00 00")), 1)
        self.assertEqual(_phase10_noteskin_terminal_row(bytes.fromhex("47 05 00 00")), 2)
        self.assertEqual(_phase10_noteskin_terminal_row(bytes.fromhex("57 03 00 00")), 1)
        self.assertIsNone(_phase10_noteskin_terminal_row(bytes.fromhex("4B 05 00 00")))


if __name__ == "__main__":
    unittest.main()
