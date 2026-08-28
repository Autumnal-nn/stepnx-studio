from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    from stepnx.authoring.timing import BlockTimingValues
    from stepnx.gui.timing_dialog import BlockTimingDialog
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class DivFlagsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    @staticmethod
    def _values(flags: int) -> BlockTimingValues:
        return BlockTimingValues(
            start_time_ms=0.0,
            bpm=120.0,
            scroll_factor=0.25,
            offset_or_delay_ms=0.0,
            speed_or_freeze=1.0,
            beat_split=4,
            beat_measure=4,
            smooth_speed=flags,
            raw_flag=0,
        )

    def test_skip_only_does_not_present_as_smooth(self) -> None:
        dialog = BlockTimingDialog(self._values(0x02))
        try:
            self.assertFalse(dialog._smooth_transition.isChecked())
            self.assertTrue(dialog._skip.isChecked())
            self.assertEqual(dialog.values().smooth_speed, 0x02)
        finally:
            dialog.close()

    def test_known_toggles_preserve_unknown_upper_bits(self) -> None:
        dialog = BlockTimingDialog(self._values(0x82))
        try:
            dialog._smooth_transition.setChecked(True)
            self.assertEqual(dialog.values().smooth_speed, 0x83)

            dialog._skip.setChecked(False)
            self.assertEqual(dialog.values().smooth_speed, 0x81)

            dialog._smooth_transition.setChecked(False)
            self.assertEqual(dialog.values().smooth_speed, 0x80)
        finally:
            dialog.close()

    def test_raw_byte_updates_both_named_bits_without_normalizing_it(self) -> None:
        dialog = BlockTimingDialog(self._values(0x00))
        try:
            dialog._smooth.setValue(0xC3)
            self.assertTrue(dialog._smooth_transition.isChecked())
            self.assertTrue(dialog._skip.isChecked())
            self.assertEqual(dialog.values().smooth_speed, 0xC3)
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
