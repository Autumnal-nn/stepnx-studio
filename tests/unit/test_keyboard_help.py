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
        help_menus = [
            menu_action.menu()
            for menu_action in window.menuBar().actions()
            if menu_action.menu() is not None
            and menu_action.menu().title().replace("&", "") == "Help"
        ]
        self.assertEqual(len(help_menus), 1)
        self.assertIn(action, help_menus[0].actions())


if __name__ == "__main__":
    unittest.main()
