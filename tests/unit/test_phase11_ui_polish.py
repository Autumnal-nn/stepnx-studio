from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import QApplication, QMainWindow

    from stepnx.authoring.timeline import TimelineGeometry
    from stepnx.gui.phase11_ui_polish import (
        _install_shortcuts,
        _move_waveform_to_audio,
        _selection_rect,
    )
    from stepnx.gui.phase11_waveform_precision import _install_timing_line_note_alignment
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class Phase11UiPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_selection_is_centered_on_note_timing_line_even_for_empty_cell(self) -> None:
        _install_timing_line_note_alignment()
        geometry = TimelineGeometry()
        row_y = 120.0
        rect = _selection_rect(geometry, 2, row_y, 72.0)
        self.assertAlmostEqual(rect.center().y(), row_y)
        self.assertAlmostEqual(rect.width(), geometry.lane_width - 2.0)
        self.assertAlmostEqual(rect.height(), geometry.lane_width - 2.0)

    def test_waveform_toggle_moves_from_lonely_view_menu_to_audio(self) -> None:
        window = QMainWindow()
        view_menu = window.menuBar().addMenu("&View")
        audio_menu = window.menuBar().addMenu("&Audio")
        audio_menu.addAction("Select audio…")
        separator = audio_menu.addSeparator()
        waveform = QAction("Show waveform", window)
        waveform.setCheckable(True)
        view_menu.addAction(waveform)
        window.phase11_waveform_action = waveform

        _move_waveform_to_audio(window)

        self.assertIn(waveform, audio_menu.actions())
        self.assertLess(audio_menu.actions().index(waveform), audio_menu.actions().index(separator))
        self.assertEqual(waveform.text(), "Show Waveform")
        menu_names = [
            action.text().replace("&", "") for action in window.menuBar().actions()
        ]
        self.assertNotIn("View", menu_names)

    def test_requested_folder_and_audio_shortcuts_are_installed(self) -> None:
        window = QMainWindow()
        file_menu = window.menuBar().addMenu("&File")
        open_action = file_menu.addAction("Open folder…")
        audio_menu = window.menuBar().addMenu("&Audio")
        select_audio = audio_menu.addAction("Select audio…")

        _install_shortcuts(window)

        self.assertEqual(open_action.shortcut(), QKeySequence("Ctrl+O"))
        close_action = next(
            action for action in file_menu.actions() if action.text() == "Close folder"
        )
        self.assertEqual(close_action.shortcut(), QKeySequence("Ctrl+W"))
        self.assertEqual(select_audio.shortcut(), QKeySequence("Ctrl+3"))


if __name__ == "__main__":
    unittest.main()
