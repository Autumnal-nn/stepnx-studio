from __future__ import annotations

import unittest
from dataclasses import replace

from stepnx.authoring import (
    MetronomeClock,
    NoteMetronomeClock,
    TimelineGeometry,
    TimelineLayout,
    TimingProjection,
    create_authoring_snapshot,
)
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import SetNoteAt
from tests.fixture_factory import make_normal_nx20


class AuthoringSkipRuntimeTimingTests(unittest.TestCase):
    @staticmethod
    def _two_block_snapshot():
        document = parse_bytes(make_normal_nx20(), source="skip-authoring.NX")
        snapshot = create_authoring_snapshot(document)
        source_split = snapshot.splits[0]
        skip = replace(
            source_split.blocks[0],
            start_time=1000.0,
            bpm=25.25,
            beat_split=32,
            scroll=1.0 / 32.0,
            smooth_speed=2,
        )
        second_split_id = source_split.stable_id + 100_000
        normal = replace(
            source_split.blocks[0],
            stable_id=source_split.blocks[0].stable_id + 100_000,
            split_id=second_split_id,
            start_time=1500.0,
            bpm=101.0,
            beat_split=8,
            scroll=1.0 / 8.0,
            smooth_speed=0,
        )
        first_split = replace(source_split, blocks=(skip,))
        second_split = replace(
            source_split,
            stable_id=second_split_id,
            index=source_split.index + 1,
            blocks=(normal,),
        )
        return replace(
            snapshot,
            splits=(first_split, second_split),
            active_blocks=(
                (first_split.stable_id, skip.stable_id),
                (second_split.stable_id, normal.stable_id),
            ),
        )

    def test_timeline_playhead_jumps_past_zero_duration_skip_div(self) -> None:
        snapshot = self._two_block_snapshot()
        layout = TimelineLayout(snapshot, TimelineGeometry(row_height=20), playback=True)

        self.assertEqual(
            layout.y_for_chart_time(1000.0),
            layout.segments[1].rows_top,
        )

    def test_beat_metronome_uses_native_active_div_after_skip(self) -> None:
        snapshot = self._two_block_snapshot()
        clock = MetronomeClock(snapshot)

        beat = clock.beat_at(1000.0)

        self.assertEqual(beat.block_id, snapshot.splits[1].blocks[0].stable_id)
        self.assertEqual(beat.beat_index, 0)

    def test_skip_note_rows_keep_start_time_in_arrow_metronome(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="skip-note-clock.NX")
        block = document.splits[0].blocks[0]
        first_row, second_row = block.rows[:2]
        document = SetNoteAt(first_row.stable_id, 0, b"\x43\x03\x00\x00").apply(
            document
        )
        document = SetNoteAt(second_row.stable_id, 1, b"\x43\x03\x00\x00").apply(
            document
        )
        snapshot = create_authoring_snapshot(document)
        source_split = snapshot.splits[0]
        skip = replace(source_split.blocks[0], smooth_speed=2, start_time=2222.0)
        snapshot = replace(
            snapshot,
            splits=(replace(source_split, blocks=(skip,)),),
            active_blocks=((source_split.stable_id, skip.stable_id),),
        )

        projection = TimingProjection(snapshot)
        clock = NoteMetronomeClock(snapshot)

        self.assertEqual(
            projection.point(skip.split_id, skip.stable_id, 0).time_ms,
            2222.0,
        )
        self.assertEqual(
            projection.point(skip.split_id, skip.stable_id, 1).time_ms,
            2222.0,
        )
        self.assertEqual(clock.note_at(2222.0).row_index, 1)


if __name__ == "__main__":
    unittest.main()
