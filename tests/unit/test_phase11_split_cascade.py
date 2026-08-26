from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    from stepnx.authoring.structure import (
        StructureTarget,
        insert_empty_block_after,
        insert_empty_split_after,
    )
    from stepnx.codecs.nx20 import parse_bytes
    from stepnx.gui.phase11_split_cascade import (
        resize_split_boundary_cascade_document,
    )
    from tests.fixture_factory import make_normal_nx20
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class Phase11SplitCascadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _multi_split_document(self):
        document = parse_bytes(make_normal_nx20(), row_storage="rich")
        upper = document.splits[0]
        upper_block = upper.blocks[0]

        # Build a four-Split suffix so the test distinguishes "only the next
        # Split" from the required "every Split below" behavior.
        for _ in range(3):
            document = insert_empty_split_after(
                document,
                StructureTarget(upper.stable_id, upper_block.stable_id),
            ).apply(document)

        # Give each downstream Split more than one Block. Every branch must
        # receive the same absolute-time shift.
        for split in tuple(document.splits[1:]):
            block = split.blocks[0]
            document = insert_empty_block_after(
                document,
                StructureTarget(split.stable_id, block.stable_id),
            ).apply(document)

        return document, upper.stable_id, upper_block.stable_id

    def test_boundary_delta_is_applied_to_every_block_in_every_later_split(self) -> None:
        document, split_id, block_id = self._multi_split_document()
        upper = document.splits[0].blocks[0]
        requested = len(upper.rows) + 2

        before = {
            block.stable_id: float(block.start_time.value)
            for split in document.splits
            for block in split.blocks
        }

        resized, actual = resize_split_boundary_cascade_document(
            document, split_id, block_id, requested
        )
        self.assertEqual(actual, requested)

        delta = 2 * 60_000.0 / (
            float(upper.bpm.value) * int(upper.beat_split.value)
        )

        # The resized Split changes length, not its own absolute Block anchors.
        for block in resized.splits[0].blocks:
            self.assertAlmostEqual(
                float(block.start_time.value), before[block.stable_id], places=4
            )

        # Every branch of every later Split moves by exactly the same delta.
        self.assertGreaterEqual(len(resized.splits), 4)
        for split in resized.splits[1:]:
            self.assertGreaterEqual(len(split.blocks), 2)
            for block in split.blocks:
                self.assertAlmostEqual(
                    float(block.start_time.value),
                    before[block.stable_id] + delta,
                    places=4,
                )


if __name__ == "__main__":
    unittest.main()
