from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stepnx.workspace import open_folder, plan_save_all
from tests.fixture_factory import make_nx10, make_nx10_lightmap

try:
    from stepnx.gui.phase11_nx10_materialization import (
        _assign_in_place_targets,
        _pending_nx10_imports,
    )
except ImportError as exc:
    _assign_in_place_targets = None
    _pending_nx10_imports = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


class _Window:
    def __init__(self, workspace) -> None:
        self.workspace = workspace


@unittest.skipIf(
    _assign_in_place_targets is None,
    f"Qt runtime unavailable: {QT_UNAVAILABLE}",
)
class Phase11NX10MaterializationTests(unittest.TestCase):
    def test_two_imported_nx10_files_become_explicit_in_place_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lm = root / "LM.NX"
            nm = root / "NM.NX"
            lm.write_bytes(make_nx10_lightmap())
            nm.write_bytes(make_nx10())

            window = _Window(open_folder(root))
            pending = _pending_nx10_imports(window)
            self.assertEqual([entry.path.name for entry in pending], ["LM.NX", "NM.NX"])
            self.assertFalse(plan_save_all(window.workspace).is_ready)

            _assign_in_place_targets(window, pending)
            plan = plan_save_all(window.workspace)
            self.assertTrue(plan.is_ready)
            self.assertEqual(
                [operation.target.name for operation in plan.operations],
                ["LM.NX", "NM.NX"],
            )
            for entry in window.workspace.documents:
                self.assertEqual(entry.output_path, entry.path)


if __name__ == "__main__":
    unittest.main()
