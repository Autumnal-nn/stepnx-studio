from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication, QMainWindow

    from stepnx.gui.phase11_preferences import install_phase11_preferences
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class Phase11PreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.original_style = self.application.style().objectName()
        self.original_palette = QPalette(self.application.palette())
        self.tempdir = tempfile.TemporaryDirectory()
        self.settings = QSettings(
            str(Path(self.tempdir.name) / "settings.ini"),
            QSettings.Format.IniFormat,
        )

    def tearDown(self) -> None:
        self.application.setStyle(self.original_style)
        self.application.setPalette(self.original_palette)
        self.settings.clear()
        self.settings.sync()
        self.tempdir.cleanup()

    def _window(self) -> QMainWindow:
        window = QMainWindow()
        window.settings_menu = window.menuBar().addMenu("Settings")
        return window

    def test_dark_mode_toggle_is_persisted_and_reversible(self) -> None:
        window = self._window()
        try:
            with patch(
                "stepnx.gui.phase11_preferences._settings",
                return_value=self.settings,
            ):
                install_phase11_preferences(window)
                action = window.phase11_dark_mode_action
                self.assertFalse(action.isChecked())

                action.trigger()
                self.assertTrue(action.isChecked())
                self.assertEqual(self.application.style().objectName().lower(), "fusion")
                self.assertTrue(self.settings.value("appearance/dark_mode", type=bool))
                self.assertLess(
                    self.application.palette().window().color().lightness(),
                    128,
                )

                action.trigger()
                self.assertFalse(action.isChecked())
                self.assertFalse(self.settings.value("appearance/dark_mode", type=bool))
                self.assertEqual(
                    self.application.style().objectName().lower(),
                    self.original_style.lower(),
                )
        finally:
            window.deleteLater()

    def test_saved_dark_mode_is_restored_on_install(self) -> None:
        self.settings.setValue("appearance/dark_mode", True)
        self.settings.sync()
        window = self._window()
        try:
            with patch(
                "stepnx.gui.phase11_preferences._settings",
                return_value=self.settings,
            ):
                install_phase11_preferences(window)
                self.assertTrue(window.phase11_dark_mode_action.isChecked())
                self.assertEqual(self.application.style().objectName().lower(), "fusion")
                self.assertLess(
                    self.application.palette().window().color().lightness(),
                    128,
                )
        finally:
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
