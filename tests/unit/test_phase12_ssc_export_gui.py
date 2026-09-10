from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QMainWindow

from stepnx.gui.phase12_ssc_export import (
    _clean_field,
    _export_defaults,
    _write_text_atomic,
    install_phase12_ssc_export,
)


_app = QApplication.instance() or QApplication([])


class Phase12SscExportGuiTests(unittest.TestCase):
    def test_clean_field_removes_tag_terminators_and_newlines(self) -> None:
        self.assertEqual(_clean_field("NX; chart\nname"), "NX  chart name")

    def test_export_defaults_use_current_chart_and_selected_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Song Folder"
            root.mkdir()
            chart = root / "D22_22.NX"
            audio = root.parent / "Song Folder.mp3"
            workspace = SimpleNamespace(
                root=root,
                selected_audio=audio,
                audio_candidates=(),
            )
            entry = SimpleNamespace(path=chart)
            defaults = _export_defaults(workspace, entry)
            self.assertEqual(defaults.description, "D22_22")
            self.assertEqual(defaults.title, "Song Folder")
            self.assertEqual(defaults.music, "Song Folder.mp3")
            self.assertEqual(defaults.target, chart.with_suffix(".ssc"))

    def test_atomic_writer_replaces_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "chart.ssc"
            target.write_text("old", encoding="utf-8")
            _write_text_atomic(target, "new\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "new\n")
            self.assertFalse((target.parent / f".{target.name}.stepnx-tmp").exists())

    def test_installer_adds_disabled_file_menu_action_until_chart_is_open(self) -> None:
        window = QMainWindow()
        file_menu = window.menuBar().addMenu("&File")
        file_menu.addAction("Open folder…")
        file_menu.addAction("Compare / export NFO mirror…")
        file_menu.addSeparator()
        window.workspace = None

        install_phase12_ssc_export(window)
        action = window.phase12_ssc_export_action

        self.assertIn("XSanity SSC", action.text())
        self.assertFalse(action.isEnabled())
        self.assertIn(action, file_menu.actions())

        # The installer is idempotent and does not duplicate the menu entry.
        install_phase12_ssc_export(window)
        matching = [candidate for candidate in file_menu.actions() if "XSanity SSC" in candidate.text()]
        self.assertEqual(len(matching), 1)


if __name__ == "__main__":
    unittest.main()
