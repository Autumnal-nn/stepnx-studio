from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    from stepnx.gui.phase11_authoring_polish import _parse_timing_value
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class Phase11AuthoringPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_inspector_timing_parser_keeps_float_precision(self) -> None:
        self.assertAlmostEqual(_parse_timing_value("BPM", "136.375"), 136.375)
        self.assertAlmostEqual(
            _parse_timing_value("Start Time (ms)", "-20.125"), -20.125
        )

    def test_inspector_integer_fields_accept_decimal_and_hex(self) -> None:
        self.assertEqual(_parse_timing_value("Beat split", "64"), 64)
        self.assertEqual(_parse_timing_value("Raw Flag", "0x81"), 0x81)

    def test_non_timing_rows_remain_outside_direct_editor(self) -> None:
        with self.assertRaises(ValueError):
            _parse_timing_value("Division metadata — Brain opcode", "21")


if __name__ == "__main__":
    unittest.main()
