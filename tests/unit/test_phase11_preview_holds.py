from __future__ import annotations

import unittest

try:
    from stepnx.gui.preview_widget import GameplayPreviewWidget
    from stepnx.preview.events import PreviewEvent
except ImportError as exc:  # pragma: no cover - Windows GUI gate installs PySide6
    GameplayPreviewWidget = None
    PreviewEvent = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _event(
    note_type: int,
    *,
    time_ms: float,
    split_id: int,
    block_id: int,
    row_index: int,
    lane: int,
    position: float,
):
    assert PreviewEvent is not None
    return PreviewEvent(
        time_ms,
        row_index / 4.0,
        split_id,
        block_id,
        row_index,
        lane,
        bytes((note_type, 0x03, 0x00, 0x00)),
        0.25,
        position,
    )


@unittest.skipIf(GameplayPreviewWidget is None, f"PySide6 unavailable: {_IMPORT_ERROR}")
class Phase11PreviewHoldTests(unittest.TestCase):
    def test_hold_pairs_across_sequential_splits_and_blocks(self) -> None:
        head = _event(
            0x07,
            time_ms=100.0,
            split_id=10,
            block_id=100,
            row_index=1,
            lane=2,
            position=0.25,
        )
        body = _event(
            0x0B,
            time_ms=200.0,
            split_id=11,
            block_id=200,
            row_index=0,
            lane=2,
            position=0.50,
        )
        tail = _event(
            0x0F,
            time_ms=300.0,
            split_id=12,
            block_id=300,
            row_index=0,
            lane=2,
            position=0.75,
        )

        pairs = GameplayPreviewWidget._pair_holds((head, body, tail))

        self.assertEqual(pairs, ((head, tail),))

    def test_tail_on_another_lane_does_not_close_open_hold(self) -> None:
        head = _event(
            0x07,
            time_ms=100.0,
            split_id=10,
            block_id=100,
            row_index=0,
            lane=1,
            position=0.0,
        )
        wrong_tail = _event(
            0x0F,
            time_ms=200.0,
            split_id=11,
            block_id=200,
            row_index=0,
            lane=2,
            position=0.25,
        )
        right_tail = _event(
            0x0F,
            time_ms=300.0,
            split_id=12,
            block_id=300,
            row_index=0,
            lane=1,
            position=0.50,
        )

        pairs = GameplayPreviewWidget._pair_holds((head, wrong_tail, right_tail))

        self.assertEqual(pairs, ((head, right_tail),))

    def test_new_head_replaces_an_orphan_head_on_the_same_lane(self) -> None:
        orphan = _event(
            0x07,
            time_ms=100.0,
            split_id=10,
            block_id=100,
            row_index=0,
            lane=3,
            position=0.0,
        )
        replacement = _event(
            0x07,
            time_ms=200.0,
            split_id=11,
            block_id=200,
            row_index=0,
            lane=3,
            position=0.25,
        )
        tail = _event(
            0x0F,
            time_ms=300.0,
            split_id=12,
            block_id=300,
            row_index=0,
            lane=3,
            position=0.50,
        )

        pairs = GameplayPreviewWidget._pair_holds((orphan, replacement, tail))

        self.assertEqual(pairs, ((replacement, tail),))


if __name__ == "__main__":
    unittest.main()
