from __future__ import annotations

import unittest
from dataclasses import replace

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
        source_split = snapshot.splits[0]
        # The shared fixture intentionally carries smooth_speed=2, which is
        # now correctly interpreted as bSkip. This test is about ordinary
        # positive-msPerLine timing, so make that premise explicit instead of
        # relying on the old mistaken meaning of raw value 2.
        block = replace(source_split.blocks[0], smooth_speed=0)
        split = replace(source_split, blocks=(block,))
        snapshot = replace(
            snapshot,
            splits=(split,),
            active_blocks=((split.stable_id, block.stable_id),),
        )
        projection = TimingProjection(snapshot)

        point = projection.point(block.split_id, block.stable_id, 1)

        self.assertEqual(point.beat, 0.25)
        self.assertAlmostEqual(point.time_ms, block.start_time + 125.0)
        self.assertEqual(projection.nearest_row(point.time_ms), point)

    def test_skip_rows_share_start_time_and_transport_advances_past_div(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX")
        snapshot = create_authoring_snapshot(document)
        source_split = snapshot.splits[0]
        first = replace(
            source_split.blocks[0],
            start_time=1000.0,
            smooth_speed=2,
        )
        second_split_id = source_split.stable_id + 100_000
        second = replace(
            source_split.blocks[0],
            stable_id=source_split.blocks[0].stable_id + 100_000,
            split_id=second_split_id,
            start_time=1500.0,
            smooth_speed=0,
        )
        first_split = replace(source_split, blocks=(first,))
        second_split = replace(
            source_split,
            stable_id=second_split_id,
            index=source_split.index + 1,
            blocks=(second,),
        )
        snapshot = replace(
            snapshot,
            splits=(first_split, second_split),
            active_blocks=(
                (first_split.stable_id, first.stable_id),
                (second_split.stable_id, second.stable_id),
            ),
        )
        projection = TimingProjection(snapshot)

        self.assertEqual(projection.row_duration_ms(first), 0.0)
        self.assertEqual(
            projection.point(
                first.split_id,
                first.stable_id,
                first.row_count,
            ).time_ms,
            1000.0,
        )
        at_skip_start = projection.locate(1000.0)
        self.assertEqual(at_skip_start.block_id, second.stable_id)
        self.assertEqual(at_skip_start.row, 0.0)


if __name__ == "__main__":
    unittest.main()