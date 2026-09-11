from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QMainWindow

from stepnx.gui.phase12_ssc_export import (
    SscPoolOption,
    _clean_field,
    _default_pool,
    _export_defaults,
    _format_size,
    _write_text_atomic,
    install_phase12_ssc_export,
)


_app = QApplication.instance() or QApplication([])


class Phase12SscExportGuiTests(unittest.TestCase):
    def test_clean_field_removes_tag_terminators_and_newlines(self) -> None:
        self.assertEqual(_clean_field("NX; chart\nname"), "NX  chart name")

    def test_export_defaults_use_folder_step_ssc_and_selected_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Song Folder"
            root.mkdir()
            chart = root / "D22_22.NX"
            audio = root / "Song Folder.mp3"
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
            self.assertEqual(defaults.target, root / "STEP.SSC")

    def test_large_random_dialog_prefers_360_helper_middle_ground(self) -> None:
        options = tuple(
            SscPoolOption(count, error, count * 1000)
            for count, error in ((72, 1.111), (140, 0.397), (360, 0.159), (2520, 0.0))
        )
        self.assertEqual(_default_pool(options), 360)

    def test_size_formatter_uses_mib_for_large_ssc(self) -> None:
        self.assertEqual(_format_size(64 * 1024 * 1024), "64.0 MiB")

    def test_atomic_writer_replaces_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "STEP.SSC"
            target.write_text("old", encoding="utf-8")
            _write_text_atomic(target, "new\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "new\n")
            self.assertFalse((target.parent / f".{target.name}.stepnx-tmp").exists())

    def test_installer_adds_disabled_folder_action_until_workspace_is_open(self) -> None:
        window = QMainWindow()
        file_menu = window.menuBar().addMenu("&File")
        file_menu.addAction("Open folder…")
        file_menu.addAction("Compare / export NFO mirror…")
        file_menu.addSeparator()
        window.workspace = None

        install_phase12_ssc_export(window)
        action = window.phase12_ssc_export_action

        self.assertIn("folder", action.text().casefold())
        self.assertIn("XSanity SSC", action.text())
        self.assertFalse(action.isEnabled())
        self.assertIn(action, file_menu.actions())

        install_phase12_ssc_export(window)
        matching = [candidate for candidate in file_menu.actions() if "XSanity SSC" in candidate.text()]
        self.assertEqual(len(matching), 1)


if __name__ == "__main__":
    unittest.main()
