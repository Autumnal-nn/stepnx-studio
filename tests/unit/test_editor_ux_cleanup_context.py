from __future__ import annotations

import unittest
from types import SimpleNamespace

from stepnx.codecs.nx20 import parse_bytes
from stepnx.gui.editor_ux_cleanup import (
    _install_help_truth,
    division_metadata_action_enabled,
)
from tests.fixture_factory import make_normal_nx20


class EditorUxCleanupContextTests(unittest.TestCase):
    @staticmethod
    def _window(*, current_index: int, active_context=None):
        document = parse_bytes(make_normal_nx20(), row_storage="compact")
        stack = SimpleNamespace(current=document)
        return SimpleNamespace(
            _metadata_context=lambda: None,
            _current_document_index=lambda: current_index,
            phase11_active_block_context=active_context,
            sessions={0: stack, 1: stack},
        ), document

    def test_division_action_accepts_current_valid_inspected_block(self) -> None:
        window, document = self._window(current_index=0)
        split = document.splits[0]
        block = split.blocks[0]
        window.phase11_active_block_context = (0, split.stable_id, block.stable_id)
        self.assertTrue(division_metadata_action_enabled(window))

    def test_division_action_rejects_stale_context_from_other_chart(self) -> None:
        window, document = self._window(current_index=1)
        split = document.splits[0]
        block = split.blocks[0]
        window.phase11_active_block_context = (0, split.stable_id, block.stable_id)
        self.assertFalse(division_metadata_action_enabled(window))

    def test_keyboard_help_mentions_both_timeline_zoom_controls(self) -> None:
        import stepnx.gui.keyboard_workflow as keyboard_module

        original = keyboard_module._SHORTCUT_HELP
        try:
            keyboard_module._SHORTCUT_HELP = original.replace(
                "Ctrl+wheel    Vertical timing zoom\n", ""
            ).replace(
                "Alt+wheel     Editor field zoom (25% step)\n", ""
            )
            _install_help_truth(SimpleNamespace(editor_zoom_menu=None))
            self.assertIn("Ctrl+wheel    Vertical timing zoom", keyboard_module._SHORTCUT_HELP)
            self.assertIn("Alt+wheel     Editor field zoom (25% step)", keyboard_module._SHORTCUT_HELP)
        finally:
            keyboard_module._SHORTCUT_HELP = original


if __name__ == "__main__":
    unittest.main()
