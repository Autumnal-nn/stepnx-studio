from __future__ import annotations

import unittest

from stepnx.codecs.nx20 import parse_bytes
from stepnx.preview.native_timing import build_native_timing
from stepnx.preview.routes import (
    PreviewMetrics,
    ResolvedRoute,
    RouteDecision,
    RoutePolicy,
)
from stepnx.preview.snapshot import PreviewBlock, PreviewSnapshot, PreviewSplit
from tests.fixture_factory import make_normal_nx20


class NormalDivInsideSkipRouteTests(unittest.TestCase):
    @staticmethod
    def _snapshot_and_route() -> tuple[PreviewSnapshot, ResolvedRoute]:
        document = parse_bytes(make_normal_nx20(), source="skip-normal-skip.NX")
        source_row = document.splits[0].blocks[0].rows[0]
        skip_rows = tuple(source_row for _ in range(192))
        normal_rows = tuple(source_row for _ in range(16))

        definitions = (
            # PUPA-style snapshot immediately before a normal Div.
            (100, 101, 58_267.36328125, 25.25, 1.0 / 32.0, 32, 0x02, skip_rows),
            # Mirrors PUPA split 112: same StartTime, Smooth Speed 0.
            (200, 201, 58_267.36328125, 101.0, 1.0 / 8.0, 8, 0x00, normal_rows),
            # Next snapshot starts when the normal Div ends.
            (300, 301, 59_455.48046875, 25.25, 1.0 / 32.0, 32, 0x02, skip_rows),
        )
        splits = []
        choices = []
        for index, (
            split_id,
            block_id,
            start,
            bpm,
            scroll,
            beat_split,
            flags,
            rows,
        ) in enumerate(definitions):
            block = PreviewBlock(
                stable_id=block_id,
                split_id=split_id,
                index=0,
                start_time_ms=start,
                bpm=bpm,
                scroll=scroll,
                offset_or_delay_ms=0.0,
                speed_or_freeze=1.0,
                beat_split=beat_split,
                beat_measure=4,
                smooth_speed=flags,
                rows=rows,
                conditions=(),
                triggers=(),
                brain_question_count=0,
            )
            splits.append(
                PreviewSplit(
                    split_id,
                    index,
                    0,
                    False,
                    False,
                    False,
                    0,
                    (block,),
                )
            )
            choices.append((split_id, block_id))

        snapshot = PreviewSnapshot(
            document_stable_id=1,
            source_name="skip-normal-skip.NX",
            profile="nxa-native",
            start_column=0,
            columns=5,
            splits=tuple(splits),
            diagnostics=(),
        )
        route = ResolvedRoute(
            policy=RoutePolicy.MANUAL,
            seed=None,
            decisions=tuple(
                RouteDecision(split, block, RoutePolicy.MANUAL, "fixture", (block,))
                for split, block in choices
            ),
            final_metrics=PreviewMetrics(),
            diagnostics=(),
        )
        return snapshot, route

    def test_normal_div_between_skip_snapshots_moves_fractionally_between_rows(self) -> None:
        snapshot, route = self._snapshot_and_route()
        native = build_native_timing(snapshot, route)
        normal = native.blocks[1]
        self.assertFalse(normal.is_skip)
        self.assertGreater(normal.ms_per_line, 0.0)

        start = normal.start_time_ms
        half_row_time = start + normal.ms_per_line * 0.5
        state = native.state_at(half_row_time)

        self.assertEqual(state.block_index, 1)
        self.assertEqual(state.line, 0)
        self.assertAlmostEqual(state.beat, -0.5 * normal.beat_per_line)
        self.assertAlmostEqual(
            native.current_position(half_row_time) - native.current_position(start),
            0.5 * normal.beat_per_line,
        )
        self.assertAlmostEqual(
            native.block_beat(1, 1, half_row_time),
            0.5 * normal.beat_per_line,
        )

    def test_normal_div_selects_each_row_inside_its_native_interval(self) -> None:
        snapshot, route = self._snapshot_and_route()
        native = build_native_timing(snapshot, route)
        normal = native.blocks[1]

        # GetLine() and Judge() use separate float32 instruction sequences in
        # the native runtime.  At an exact theoretical row boundary, their
        # independently rounded values can differ by one float32 tick.  Test
        # the interior of each row interval instead, where GetLine is
        # unambiguous and the continuous projection is what the preview needs.
        for row in (0, 3, 7, 14):
            time_ms = normal.start_time_ms + (row + 0.5) * normal.ms_per_line
            state = native.state_at(time_ms)
            self.assertEqual(state.block_index, 1)
            self.assertEqual(state.line, row)
            self.assertAlmostEqual(
                native.current_position(time_ms)
                - native.line_position(1, row),
                0.5 * normal.beat_per_line,
                places=5,
            )
            self.assertAlmostEqual(
                native.block_beat(1, row + 1, time_ms),
                0.5 * normal.beat_per_line,
                places=5,
            )


if __name__ == "__main__":
    unittest.main()
