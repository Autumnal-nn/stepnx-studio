from __future__ import annotations

import unittest

from stepnx.authoring import (
    BlockTimingValues,
    ShiftBlockStartTimes,
    TimingEditError,
    TimingProjection,
    create_authoring_snapshot,
)
from stepnx.codecs.nx20 import parse_bytes, serialize
from tests.fixture_factory import make_normal_nx20


class BlockTimingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = parse_bytes(make_normal_nx20(), source="NM.NX")
        self.block = self.document.splits[0].blocks[0]

    def test_all_timing_fields_change_atomically_and_roundtrip(self) -> None:
        values = BlockTimingValues(
            start_time_ms=-75.5,
            bpm=173.25,
            scroll_factor=0.75,
            offset_or_delay_ms=125.0,
            speed_or_freeze=-2.0,
            beat_split=48,
            beat_measure=3,
            smooth_speed=3,
            raw_flag=0xA5,
        )
        edited = values.command(self.block.stable_id).apply(self.document)
        reparsed = parse_bytes(serialize(edited), source="edited.NX")
        actual = BlockTimingValues.from_block(reparsed.splits[0].blocks[0])

        self.assertEqual(actual, values)
        self.assertTrue(actual.is_freeze)
        self.assertEqual(actual.real_scroll, 36.0)

    def test_invalid_timing_is_rejected_without_normalization(self) -> None:
        values = BlockTimingValues(0, 0, 1, 0, 1, 0, 4, 0, 0)
        with self.assertRaises(TimingEditError):
            values.command(self.block.stable_id)

    def test_shift_start_times_updates_every_block_as_one_command(self) -> None:
        shifted = ShiftBlockStartTimes(-50.0).apply(self.document)
        self.assertAlmostEqual(
            shifted.splits[0].blocks[0].start_time.value,
            self.block.start_time.value - 50.0,
        )


class TimingProjectionTests(unittest.TestCase):
    def test_row_beat_and_millisecond_projection_use_explicit_block_anchor(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX")
        snapshot = create_authoring_snapshot(document)
        block = snapshot.splits[0].blocks[0]
        projection = TimingProjection(snapshot)

        point = projection.point(block.split_id, block.stable_id, 1)

        self.assertEqual(point.beat, 0.25)
        self.assertAlmostEqual(point.time_ms, block.start_time + 125.0)
        self.assertEqual(projection.nearest_row(point.time_ms), point)


if __name__ == "__main__":
    unittest.main()
