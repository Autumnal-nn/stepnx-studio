from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from stepnx.codecs.nx20 import parse_bytes
from stepnx.importers.authoring_import import (
    load_authoring_import_candidates,
    materialize_authoring_import_batch,
    prepare_authoring_import_batch,
    validate_authoring_import_batch,
    validate_import_filename,
)


UCS = b""":Format=1
:Mode=Single
:BPM=120
:Delay=0
:Beat=4
:Split=4
X....
.....
"""


class AuthoringImportFlowTests(unittest.TestCase):
    def test_ucs_batch_adds_required_empty_lightmap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "sample.ucs"
            source.write_bytes(UCS)
            candidates = prepare_authoring_import_batch(
                load_authoring_import_candidates(source, profile="fiesta2")
            )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].document.profile, "fiesta2")
        self.assertFalse(candidates[0].document.effective_lightmap)
        self.assertEqual(candidates[1].default_filename, "LM.NX")
        self.assertTrue(candidates[1].document.effective_lightmap)

    def test_batch_materialization_creates_complete_openable_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.ucs"
            source.write_bytes(UCS)
            candidates = prepare_authoring_import_batch(load_authoring_import_candidates(source))
            targets = materialize_authoring_import_batch(candidates, root)

            self.assertEqual({path.name for path in targets}, {"sample.NX", "LM.NX"})
            for target in targets:
                self.assertEqual(target.read_bytes()[:4], b"NX20")
                parse_bytes(target.read_bytes(), source=str(target))

            with self.assertRaises(FileExistsError):
                validate_authoring_import_batch(candidates, root)

    def test_target_filename_must_be_windows_safe_and_local(self) -> None:
        self.assertEqual(validate_import_filename("S10.NX"), "S10.NX")
        for invalid in (
            "",
            "S10",
            "../S10.NX",
            "sub/S10.NX",
            r"sub\S10.NX",
            "LM.NFO",
            "CON.NX",
            "bad:name.NX",
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_import_filename(invalid)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import (
        QApplication,
        QDialogButtonBox,
        QMainWindow,
        QTableWidget,
        QTabWidget,
        QTreeWidget,
    )

    from stepnx.gui.phase11_import import (
        AuthoringImportDialog,
        _close_workspace,
        install_phase11_import,
    )

    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "PySide6 is not installed")
class QtAuthoringImportSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_installer_adds_close_and_batch_import_actions(self) -> None:
        window = QMainWindow()
        menu = window.menuBar().addMenu("&File")
        menu.addAction("Open folder...")
        menu.addAction("Save All...")
        install_phase11_import(window)

        self.assertEqual(window.phase11_close_folder_action.text(), "Close Folder")
        self.assertEqual(window.phase11_import_action.text(), "Import charts…")
        self.assertEqual(window.phase11_import_action.shortcut().toString(), "Ctrl+I")
        self.assertEqual(
            [action.text() for action in menu.actions()][:4],
            ["Open folder...", "Close Folder", "Import charts…", "Save All..."],
        )
        window.close()

    def test_batch_dialog_blocks_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.ucs"
            source.write_bytes(UCS)
            candidates = prepare_authoring_import_batch(load_authoring_import_candidates(source))
            (root / candidates[0].default_filename).write_bytes(b"existing")

            dialog = AuthoringImportDialog(source, root, candidates)
            ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
            self.assertFalse(ok.isEnabled())
            self.assertIn("already exists", dialog.validation.text())
            dialog.close()

    def test_close_workspace_returns_to_blank_editor_state(self) -> None:
        window = QMainWindow()
        window.workspace = SimpleNamespace(root=Path("C:/fake"))
        window._confirm_discard = lambda: True
        window.sessions = {1: object()}
        window.baselines = {1: object()}
        window.widget_documents = {object(): 1}
        window.preview_snapshots = {1: object()}
        window.gesture_keys = {object(): object()}
        window.tabs = QTabWidget()
        window.tabs.addTab(QTreeWidget(), "chart")
        window.tree = QTreeWidget()
        window.tree.addTopLevelItem(__import__("PySide6.QtWidgets", fromlist=["QTreeWidgetItem"]).QTreeWidgetItem(["root"]))
        window.diagnostics = QTreeWidget()
        window.routes = QTreeWidget()
        window.inspector = QTableWidget(1, 1)
        window.waveform = object()
        window.metronome_clock = object()
        window.note_metronome_clock = object()

        self.assertTrue(_close_workspace(window))
        self.assertIsNone(window.workspace)
        self.assertEqual(window.tabs.count(), 0)
        self.assertEqual(window.tree.topLevelItemCount(), 0)
        self.assertEqual(window.inspector.rowCount(), 0)
        self.assertFalse(window.sessions)
        self.assertIsNone(window.waveform)
        window.close()


if __name__ == "__main__":
    unittest.main()
