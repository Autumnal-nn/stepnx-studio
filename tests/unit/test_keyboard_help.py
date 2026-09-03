from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication, QMainWindow

    from stepnx.gui.keyboard_workflow import _install_keyboard_help
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class KeyboardHelpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_f1_keyboard_map_is_visible_in_help_menu(self) -> None:
        window = QMainWindow()

        _install_keyboard_help(window)

        action = window.keyboard_help_action
        self.assertEqual(action.text(), "Keyboard shortcuts…")
        self.assertEqual(action.shortcut(), QKeySequence("F1"))

        # Keep the QMenu wrapper strongly referenced while inspecting it. Some
        # Linux/offscreen PySide builds transfer ownership through QAction and
        # may invalidate a temporary wrapper returned repeatedly by action.menu().
        help_menu = None
        for menu_action in window.menuBar().actions():
            candidate = menu_action.menu()
            if (
                candidate is not None
                and candidate.title().replace("&", "") == "Help"
            ):
                help_menu = candidate
                break

        self.assertIsNotNone(help_menu)
        self.assertIn(action, help_menu.actions())


if __name__ == "__main__":
    unittest.main()
