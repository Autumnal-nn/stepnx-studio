from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stepnx.authoring.batch import (
    MetadataBatchMode,
    apply_batch_plan,
    plan_batch_header_metadata,
    plan_batch_shift_start_times,
)
from stepnx.codecs.nx20 import serialize
from stepnx.workspace import open_folder
from tests.fixture_factory import make_implicit_lightmap, make_normal_nx20


class FolderBatchTests(unittest.TestCase):
    def _workspace(self, root: Path):
        (root / "A.NX").write_bytes(make_normal_nx20(sized_trailer=False))
        (root / "B.NX").write_bytes(make_normal_nx20(sized_trailer=False))
        (root / "LM.NX").write_bytes(make_implicit_lightmap())
        return open_folder(root)

    def test_header_metadata_batch_has_explicit_duplicate_policy_and_skips_lightmap(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = self._workspace(Path(temporary))
            plan = plan_batch_header_metadata(
                workspace, 900, 12, mode=MetadataBatchMode.REPLACE_ALL
            )
            self.assertEqual(plan.document_count, 2)
            updated = apply_batch_plan(workspace, plan)
            for entry in updated.documents:
                values = [
                    item.value.value
                    for item in entry.document.header_metadata
                    if item.meta_id.value == 900
                ]
                if entry.path.name == "LM.NX":
                    self.assertEqual(values, [])
                    original = workspace.document_for(entry.path)
                    self.assertEqual(
                        serialize(entry.document), serialize(original.document)
                    )
                else:
                    self.assertEqual(values, [12, 12])

            upsert = plan_batch_header_metadata(
                updated, 65, 400, mode=MetadataBatchMode.UPSERT_LAST
            )
            updated = apply_batch_plan(updated, upsert)
            for entry in updated.documents:
                if entry.path.name != "LM.NX":
                    self.assertEqual(
                        entry.document.header_metadata[-1].meta_id.value, 65
                    )

    def test_batch_plan_is_write_free_and_shift_is_applied_to_every_chart_block(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = self._workspace(root)
            original = {
                entry.path: entry.path.read_bytes() for entry in workspace.documents
            }
            plan = plan_batch_shift_start_times(workspace, 125.5)
            updated = apply_batch_plan(workspace, plan)
            self.assertEqual(plan.document_count, 2)
            self.assertTrue(
                all(path.read_bytes() == payload for path, payload in original.items())
            )
            for entry in updated.documents:
                if entry.path.name != "LM.NX":
                    self.assertAlmostEqual(
                        entry.document.splits[0].blocks[0].start_time.value, 125.5
                    )


if __name__ == "__main__":
    unittest.main()
