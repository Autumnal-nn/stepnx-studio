from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stepnx.importers.authoring_import import (
    load_authoring_import_candidates,
    prepare_authoring_import_batch,
)


class KSFBatchImportTests(unittest.TestCase):
    def test_starttime_centiseconds_are_projected_as_milliseconds(self) -> None:
        source = b"""#BPM:180.0;
#TICKCOUNT:4;
#STARTTIME:25;
#STEP:
1000000000001
0000000000000
2222222222222
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Normal_1.KSF"
            path.write_bytes(source)
            candidates = load_authoring_import_candidates(path)

        self.assertEqual([candidate.key for candidate in candidates], ["chart", "LM"])
        chart, lightmap = candidates
        self.assertAlmostEqual(chart.document.splits[0].blocks[0].start_time.value, 250.0)
        self.assertTrue(lightmap.document.effective_lightmap)
        row = lightmap.document.splits[0].blocks[0].rows[0]
        self.assertEqual(row.raw_channels, b"\x00\x00\x01\x00")

    def test_ten_channel_ksf_gets_empty_required_lightmap(self) -> None:
        source = b"""#BPM:120;
#TICKCOUNT:2;
#STARTTIME:10;
#STEP:
1000000000
0000000000
2222222222222
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Normal_1.KSF"
            path.write_bytes(source)
            candidates = prepare_authoring_import_batch(load_authoring_import_candidates(path))

        self.assertEqual([candidate.key for candidate in candidates], ["chart", "LM"])
        lightmap = candidates[1].document
        self.assertTrue(lightmap.effective_lightmap)
        self.assertAlmostEqual(lightmap.splits[0].blocks[0].start_time.value, 100.0)
        self.assertTrue(
            all(not any(row.raw_channels[:3]) for row in lightmap.splits[0].blocks[0].rows)
        )

    def test_ksf_with_two_playable_banks_exports_both_players_and_lm(self) -> None:
        source = b"""#BPM:120;
#TICKCOUNT:4;
#STARTTIME:0;
#STEP:
1000010000000
2222222222222
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Hard_2.KSF"
            path.write_bytes(source)
            candidates = prepare_authoring_import_batch(load_authoring_import_candidates(path))

        self.assertEqual([candidate.key for candidate in candidates], ["p1", "p2", "LM"])
        self.assertEqual([candidate.document.columns.value for candidate in candidates], [5, 5, 3])


if __name__ == "__main__":
    unittest.main()
