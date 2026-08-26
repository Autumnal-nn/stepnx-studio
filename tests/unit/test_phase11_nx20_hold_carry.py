from __future__ import annotations

import unittest

from stepnx.preview.events import PreviewEvent
from stepnx.preview.holds import pair_nx20_holds


def _event(
    note_type: int,
    *,
    time_ms: float,
    split_id: int,
    block_id: int,
    row_index: int,
    lane: int,
) -> PreviewEvent:
    return PreviewEvent(
        time_ms=time_ms,
        beat=0.0,
        split_id=split_id,
        block_id=block_id,
        row_index=row_index,
        lane=lane,
        raw=bytes((note_type, 0x03, 0x00, 0x00)),
        scroll=0.25,
        position=time_ms / 1000.0,
    )


class NX20HoldCarryTests(unittest.TestCase):
    def test_hundreds_of_missing_rows_are_transparent(self) -> None:
        head = _event(0x7, time_ms=0.0, split_id=13, block_id=130, row_index=3, lane=2)
        # No events at all for the 252 source rows in Split 14. RuntimeEventStream
        # therefore presents no non-empty row to the hold state machine.
        body = _event(0xB, time_ms=11000.0, split_id=15, block_id=150, row_index=0, lane=2)
        tail = _event(0xF, time_ms=11200.0, split_id=15, block_id=150, row_index=1, lane=2)
        self.assertEqual(pair_nx20_holds((head, body, tail)), ((head, tail),))

    def test_nonempty_row_with_zero_in_open_lane_cancels_hold(self) -> None:
        head = _event(0x7, time_ms=0.0, split_id=1, block_id=10, row_index=0, lane=2)
        unrelated = _event(0x3, time_ms=100.0, split_id=1, block_id=10, row_index=1, lane=4)
        tail = _event(0xF, time_ms=200.0, split_id=1, block_id=10, row_index=2, lane=2)
        self.assertEqual(pair_nx20_holds((head, unrelated, tail)), ())

    def test_body_on_every_nonempty_row_keeps_hold_across_splits(self) -> None:
        head = _event(0x7, time_ms=0.0, split_id=1, block_id=10, row_index=3, lane=7)
        other_lane = _event(0x3, time_ms=100.0, split_id=2, block_id=20, row_index=0, lane=1)
        body = _event(0xB, time_ms=100.0, split_id=2, block_id=20, row_index=0, lane=7)
        tail = _event(0xF, time_ms=200.0, split_id=3, block_id=30, row_index=0, lane=7)
        self.assertEqual(
            pair_nx20_holds((head, other_lane, body, tail)),
            ((head, tail),),
        )

    def test_new_head_replaces_previous_carry_on_nonempty_row(self) -> None:
        first = _event(0x7, time_ms=0.0, split_id=1, block_id=10, row_index=0, lane=3)
        replacement = _event(0x7, time_ms=100.0, split_id=1, block_id=10, row_index=1, lane=3)
        tail = _event(0xF, time_ms=200.0, split_id=1, block_id=10, row_index=2, lane=3)
        self.assertEqual(pair_nx20_holds((first, replacement, tail)), ((replacement, tail),))


if __name__ == "__main__":
    unittest.main()
