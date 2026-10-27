from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    from stepnx.gui.typed_inputs import (
        LabeledRangeRow,
        PackedMetadataDialog,
        RawU32Dialog,
        PatchedUnknownDivisionDialog,
        MbrSpinRow,
        ResizeSplitDialog,
        mbr_to_rows,
        rows_to_mbr,
    )
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt unavailable: {QT_UNAVAILABLE}")
class TypedInputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_mbr_conversion_roundtrip(self):
        for beat_split, beat_measure in ((4, 4), (8, 4), (64, 3)):
            for rows in (0, 1, beat_split - 1, beat_split, 3520, 100000):
                with self.subTest(beat_split=beat_split, rows=rows):
                    self.assertEqual(
                        mbr_to_rows(*rows_to_mbr(rows, beat_split, beat_measure),
                                    beat_split, beat_measure),
                        rows,
                    )

    def test_mbr_rejects_out_of_range_values(self):
        with self.assertRaises(ValueError):
            mbr_to_rows(1, 4, 0, 8, 4)
        with self.assertRaises(ValueError):
            mbr_to_rows(1, 0, 8, 8, 4)
        with self.assertRaises(ValueError):
            mbr_to_rows(-1, 0, 0, 8, 4)

    def test_mbr_widget_has_dynamic_bounds(self):
        row = MbrSpinRow(beat_split=64, beat_measure=3)
        self.assertEqual(row.beat_spin.maximum(), 2)
        self.assertEqual(row.row_spin.maximum(), 63)
        row.set_from_rows(577)
        self.assertEqual(row.to_rows(), 577)
        row.setReadOnly(True)
        self.assertTrue(row.row_spin.isReadOnly())

    def test_range_edit_preserves_endpoint_order_and_signed_weights(self):
        row = LabeledRangeRow(minimum=-32768, maximum=32767)
        row.set_values(5, -2)
        self.assertEqual(row.values(), (5, -2))
        with self.assertRaises(ValueError):
            row.set_values(5, 32768)
        self.assertEqual(row.values(), (5, -2))

    def test_raw_u32_accepts_unknown_bits_and_full_unsigned_range(self):
        dialog = RawU32Dialog("Raw", 0xFFFFFFFF)
        self.assertEqual(dialog.value(), 0xFFFFFFFF)
        dialog.raw_edit.setText("3735928559")
        self.assertEqual(dialog.value(), 0xDEADBEEF)
        dialog.raw_edit.setText("4294967296")
        self.assertFalse(dialog._ok.isEnabled())

    def test_unknown_patched_division_defaults_to_min_max(self):
        dialog = PatchedUnknownDivisionDialog(0x0002FFFF)
        self.assertFalse(dialog.raw_mode.isChecked())
        self.assertEqual(dialog.range_row.values(), (65535, 2))
        self.assertEqual(dialog.value(), 0x0002FFFF)
        dialog.raw_mode.setChecked(True)
        dialog.raw_edit.setText("0xDEADBEEF")
        self.assertEqual(dialog.value(), 0xDEADBEEF)

    def test_patched_scope_unlocks_unknown_entries_without_unlocking_native(self):
        from stepnx.authoring.metadata import MetadataDraft
        from stepnx.core.profiles import MetadataScope
        from stepnx.gui.metadata_dialog import MetadataCollectionDialog

        unknown = MetadataDraft(0xF0000001, 0xDEADBEEF)
        for scope in (MetadataScope.HEADER, MetadataScope.DIVISION):
            patched = MetadataCollectionDialog(
                (unknown,), "nxa-step5-patched", scope
            )
            native = MetadataCollectionDialog(
                (unknown,), "nxa-native", scope
            )
            self.assertTrue(patched._is_editable(unknown))
            self.assertFalse(native._is_editable(unknown))

    def test_packed_range_dialog_preserves_unsigned_endpoints(self):
        dialog = PackedMetadataDialog(
            "Judgments", kind="u16_range", first=65535, second=0
        )
        self.assertEqual(dialog.values(), (65535, 0))
        dialog.range_row.set_values(5, 10)
        self.assertEqual(dialog.values(), (5, 10))

    def test_dm120_dialog_accepts_signed_weights_and_dynamic_mode_limits(self):
        dialog = PackedMetadataDialog("DM120", kind="dm120", first=1, second=-2)
        self.assertEqual(dialog.values(), (1, -2))
        dialog.mode.setCurrentIndex(0)
        self.assertEqual(dialog.values(), (0, -2))
        button = dialog.findChild(QDialogButtonBox).button(
            QDialogButtonBox.StandardButton.Ok
        )
        self.assertFalse(button.isEnabled())
        dialog.weight.setValue(-1)
        self.assertTrue(button.isEnabled())
        with self.assertRaises(ValueError):
            PackedMetadataDialog("DM120", kind="dm120", first=2, second=0)

    def test_resize_dialog_disables_zero_length_and_preserves_from(self):
        dialog = ResizeSplitDialog(32, beat_split=8, beat_measure=4)
        self.assertEqual(dialog.from_row.to_rows(), 32)
        self.assertEqual(dialog.requested_rows(), 32)
        dialog.to_row.set_from_rows(0)
        ok = dialog.findChild(QDialogButtonBox).button(
            QDialogButtonBox.StandardButton.Ok
        )
        self.assertFalse(ok.isEnabled())
        with self.assertRaises(ValueError):
            dialog.requested_rows()
        dialog.to_row.set_from_rows(39)
        self.assertTrue(ok.isEnabled())
        self.assertEqual(dialog.requested_rows(), 39)
        self.assertEqual(dialog.from_row.to_rows(), 32)


if __name__ == "__main__":
    unittest.main()
