from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stepnx.core.errors import ParseError
from stepnx.importers.authoring_import import (
    load_authoring_import_candidates,
    prepare_authoring_import_batch,
)


class KSFBatchImportTests(unittest.TestCase):
    def _timeline_blocks(self, document):
        """Return sequential timing Blocks, which live one-per-Split in NX20."""

        self.assertTrue(document.splits)
        self.assertTrue(
            all(len(split.blocks) == 1 for split in document.splits),
            "sequential KSF timing must not be encoded as alternative Blocks in one Split",
        )
        return tuple(split.blocks[0] for split in document.splits)

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
2222222222
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

    def test_couple_ksf_exports_both_nonempty_players_and_lm(self) -> None:
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

    def test_single_filename_keeps_only_player1_even_if_second_bank_has_data(self) -> None:
        source = b"""#BPM:120;
#TICKCOUNT:4;
#STARTTIME:0;
#STEP:
1000010000000
2222222222222
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Hard_1.KSF"
            path.write_bytes(source)
            candidates = prepare_authoring_import_batch(load_authoring_import_candidates(path))

        self.assertEqual([candidate.key for candidate in candidates], ["chart", "LM"])
        self.assertEqual(candidates[0].document.columns.value, 5)
        self.assertTrue(any("ignored by Single semantics" in item for item in candidates[0].diagnostics))

    def test_double_filename_keeps_all_ten_playable_lanes(self) -> None:
        source = b"""#BPM:120;
#TICKCOUNT:4;
#STARTTIME:0;
#STEP:
1000010000000
2222222222222
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Double.KSF"
            path.write_bytes(source)
            candidates = prepare_authoring_import_batch(load_authoring_import_candidates(path))

        self.assertEqual([candidate.key for candidate in candidates], ["double", "LM"])
        self.assertEqual(candidates[0].document.columns.value, 10)
        self.assertEqual(candidates[0].document.start_column.value, 0)

    def test_player_double_header_overrides_generic_filename(self) -> None:
        source = b"""#BPM:120;
#TICKCOUNT:4;
#STARTTIME:0;
#PLAYER:DOUBLE;
#STEP:
1000010000000
2222222222222
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Custom.KSF"
            path.write_bytes(source)
            candidates = prepare_authoring_import_batch(load_authoring_import_candidates(path))

        self.assertEqual(candidates[0].key, "double")
        self.assertEqual(candidates[0].document.columns.value, 10)

    def test_halfdouble_uses_six_lanes_with_global_offset_two(self) -> None:
        source = b"""#BPM:120;
#TICKCOUNT:4;
#STARTTIME:0;
#STEP:
0010000100000
2222222222222
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HalfDouble.KSF"
            path.write_bytes(source)
            candidates = prepare_authoring_import_batch(load_authoring_import_candidates(path))

        chart = candidates[0]
        self.assertEqual(chart.key, "halfdouble")
        self.assertEqual(chart.document.columns.value, 6)
        self.assertEqual(chart.document.start_column.value, 2)

    def test_kick_it_up_bunki_headers_create_reanchored_sequential_splits(self) -> None:
        rows = "\n".join(
            "1000000000000" if index % 2 == 0 else "0100000000000"
            for index in range(16)
        )
        source = (
            "#BPM:120;\n"
            "#BPM2:240;\n"
            "#BUNKI:100;\n"
            "#STARTTIME:0;\n"
            "#STARTTIME2:50;\n"
            "#TICKCOUNT:4;\n"
            "#STEP:\n"
            + rows
            + "\n2222222222222\n"
        ).encode("ascii")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Old_1.KSF"
            path.write_bytes(source)
            candidates = load_authoring_import_candidates(path)

        chart = candidates[0]
        blocks = self._timeline_blocks(chart.document)
        self.assertEqual(len(chart.document.splits), 2)
        self.assertEqual(len(blocks), 2)
        self.assertEqual([block.row_count.value for block in blocks], [8, 8])
        self.assertEqual([block.bpm.value for block in blocks], [120.0, 240.0])
        self.assertAlmostEqual(blocks[0].start_time.value, 0.0, places=3)
        self.assertAlmostEqual(blocks[1].start_time.value, 1000.0, places=3)
        self.assertTrue(any("ksf.kiu-header-timing" in item for item in chart.diagnostics))
        self.assertFalse(any("extended-timing-not-projected" in item for item in chart.diagnostics))

    def test_mixed_old_and_direct_move_timing_is_rejected(self) -> None:
        source = b"""#BPM:120;
#BPM2:180;
#BUNKI:100;
#STARTTIME:0;
#STARTTIME2:20;
#TICKCOUNT:4;
#STEP:
1000000000000
|B90|
0100000000000
2222222222222
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Mixed.KSF"
            path.write_bytes(source)
            with self.assertRaisesRegex(ParseError, "mixes Kick It Up"):
                load_authoring_import_candidates(path)

    def test_direct_move_pipe_timing_creates_sequential_splits_not_note_rows(self) -> None:
        source = b"""#BPM:138;
#TICKCOUNT:12;
#STARTTIME:25;
#STEP:
1000000000000
|B92|
|T18|
0100000000000
|E18|
0010000000000
|D125|
0001000000000
2222222222222
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "EX-C.KSF"
            path.write_bytes(source)
            candidates = load_authoring_import_candidates(path)

        chart = candidates[0]
        blocks = self._timeline_blocks(chart.document)
        self.assertEqual(len(chart.document.splits), 4)
        self.assertEqual(len(blocks), 4)
        self.assertEqual(sum(block.row_count.value for block in blocks), 4)
        self.assertEqual([block.bpm.value for block in blocks], [138.0, 92.0, 92.0, 92.0])
        self.assertEqual([block.beat_split.value for block in blocks], [12, 18, 18, 18])
        self.assertAlmostEqual(blocks[0].start_time.value, 250.0, places=3)
        self.assertAlmostEqual(blocks[1].start_time.value, 286.231884, places=3)
        self.assertAlmostEqual(blocks[2].offset_or_delay.value, 60000.0 / 92.0, places=3)
        self.assertAlmostEqual(blocks[3].offset_or_delay.value, 125.0, places=3)
        self.assertTrue(
            any("ksf.direct-move-timing" in diagnostic for diagnostic in chart.diagnostics)
        )

    def test_unprojected_direct_move_control_is_not_treated_as_an_item_row(self) -> None:
        source = b"""#BPM:120;
#TICKCOUNT:4;
#STARTTIME:0;
#STEP:
1000000000000
|X2|
0100000000000
2222222222222
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DM.KSF"
            path.write_bytes(source)
            candidates = load_authoring_import_candidates(path)

        chart = candidates[0]
        blocks = self._timeline_blocks(chart.document)
        self.assertEqual(sum(block.row_count.value for block in blocks), 2)
        self.assertTrue(
            any(
                "ksf.direct-move-controls-not-projected" in diagnostic
                for diagnostic in chart.diagnostics
            )
        )


if __name__ == "__main__":
    unittest.main()
