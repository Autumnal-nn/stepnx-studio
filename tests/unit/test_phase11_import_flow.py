from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from stepnx.codecs.nx20 import parse_bytes
from stepnx.importers.authoring_import import (
    load_authoring_import_candidates,
    materialize_authoring_import,
    validate_import_filename,
)


UCS = b""":Format=1
:Mode=Single
:BPM=120
:Delay=0
:Beat=4
:Split=4
:VendorHint=preserve-me
X....
.....
"""


class AuthoringImportFlowTests(unittest.TestCase):
    def test_ucs_candidate_keeps_selected_profile_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.ucs"
            source.write_bytes(UCS)
            candidates = load_authoring_import_candidates(source, profile="fiesta2")

            self.assertEqual(len(candidates), 1)
            candidate = candidates[0]
            self.assertEqual(candidate.source_format, "ucs")
            self.assertEqual(candidate.document.profile, "fiesta2")
            self.assertEqual(candidate.default_filename, "sample.NX")
            self.assertFalse(candidate.semantically_lossless)
            self.assertTrue(
                any("ucs.directive.unknown" in diagnostic for diagnostic in candidate.diagnostics)
            )

    def test_materialization_creates_native_nx20_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.ucs"
            source.write_bytes(UCS)
            candidate = load_authoring_import_candidates(source)[0]

            target = materialize_authoring_import(candidate, root, "S4_TEST.NX")
            self.assertEqual(target.read_bytes()[:4], b"NX20")
            reparsed = parse_bytes(target.read_bytes(), source=str(target))
            self.assertEqual(reparsed.columns.value, 5)

            with self.assertRaises(FileExistsError):
                materialize_authoring_import(candidate, root, "S4_TEST.NX")

    def test_target_filename_must_remain_inside_open_folder(self) -> None:
        self.assertEqual(validate_import_filename("S10.NX"), "S10.NX")
        for invalid in ("", "S10", "../S10.NX", "sub/S10.NX", "LM.NFO"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_import_filename(invalid)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMainWindow

    from stepnx.gui.phase11_import import AuthoringImportDialog, install_phase11_import

    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "PySide6 is not installed")
class QtAuthoringImportSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_installer_adds_file_import_action(self) -> None:
        window = QMainWindow()
        menu = window.menuBar().addMenu("&File")
        menu.addAction("Open folder...")
        menu.addAction("Save All...")
        install_phase11_import(window)

        self.assertEqual(window.phase11_import_action.text(), "Import chart…")
        self.assertEqual(window.phase11_import_action.shortcut().toString(), "Ctrl+I")
        self.assertEqual(
            [action.text() for action in menu.actions()][:3],
            ["Open folder...", "Import chart…", "Save All..."],
        )
        window.close()

    def test_dialog_blocks_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.ucs"
            source.write_bytes(UCS)
            candidate = load_authoring_import_candidates(source)[0]
            (root / candidate.default_filename).write_bytes(b"existing")

            dialog = AuthoringImportDialog(source, root, (candidate,))
            ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
            self.assertFalse(ok.isEnabled())
            self.assertIn("already exists", dialog.validation.text())
            dialog.close()


if __name__ == "__main__":
    unittest.main()
