from __future__ import annotations

import unittest

from stepnx.codecs.nx20 import parse_bytes
from stepnx.preview.events import build_event_stream
from stepnx.preview.native_timing import build_native_timing
from stepnx.preview.routes import (
    PreviewMetrics,
    ResolvedRoute,
    RouteDecision,
    RoutePolicy,
)
from stepnx.preview.snapshot import PreviewBlock, PreviewSnapshot, PreviewSplit
from tests.fixture_factory import make_normal_nx20


class NativeSkipTimingRegressionTests(unittest.TestCase):
    @staticmethod
    def _fixture_rows(count: int = 160):
        document = parse_bytes(make_normal_nx20(), source="PUPA-regression.NX")
        row = document.splits[0].blocks[0].rows[0]
        return tuple(row for _ in range(count))

    @classmethod
    def _snapshot(cls) -> PreviewSnapshot:
        rows = cls._fixture_rows()

        # The first three Divs model PUPA's snapshot sequence.  Their raw
        # delays and Speed signs differ, but bSkip is the common timing rule.
        definitions = (
            (101, 100, 10_000.0, 0.0, 1.0, 0x02, 25.25, 32, 1.0 / 32.0),
            (201, 200, 10_445.0, 445.0, -1.0, 0x02, 25.25, 32, 1.0 / 32.0),
            (301, 300, 10_890.0, 445.0, -1.0, 0x02, 25.25, 32, 1.0 / 32.0),
            # PUPA also overlays a normal 101/8 Div at the same StartTime as a
            # preceding Skip snapshot.  Both products are 808 rows/minute.
            (401, 400, 10_890.0, 0.0, -1.0, 0x00, 101.0, 8, 1.0 / 8.0),
        )
        splits = []
        for index, (
            block_id,
            split_id,
            start,
            delay,
            speed,
            flags,
            bpm,
            beat_split,
            scroll,
        ) in enumerate(definitions):
            block = PreviewBlock(
                stable_id=block_id,
                split_id=split_id,
                index=0,
                start_time_ms=start,
                bpm=bpm,
                scroll=scroll,
                offset_or_delay_ms=delay,
                speed_or_freeze=speed,
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
        return PreviewSnapshot(
            document_stable_id=1,
            source_name="PUPA-regression.NX",
            profile="nxa-native",
            start_column=0,
            columns=5,
            splits=tuple(splits),
            diagnostics=(),
        )

    @staticmethod
    def _route() -> ResolvedRoute:
        choices = ((100, 101), (200, 201), (300, 301), (400, 401))
        return ResolvedRoute(
            policy=RoutePolicy.MANUAL,
            seed=None,
            decisions=tuple(
                RouteDecision(split, block, RoutePolicy.MANUAL, "fixture", (block,))
                for split, block in choices
            ),
            final_metrics=PreviewMetrics(),
            diagnostics=(),
        )

    def test_step_loader_maps_skip_to_zero_ms_per_line_but_keeps_beat_length(self) -> None:
        native = build_native_timing(self._snapshot(), self._route())

        first, second = native.blocks[:2]
        self.assertTrue(first.is_skip)
        self.assertEqual(first.ms_per_line, 0.0)
        self.assertEqual(first.length_beats, 5.0)
        self.assertEqual(second.ms_per_line, 0.0)
        self.assertEqual(second.gap_beats, 0.0)
        self.assertEqual(native.sum_line_sec[:3], (5.0, 10.0, 15.0))

    def test_every_skip_row_uses_div_start_as_judgment_time(self) -> None:
        native = build_native_timing(self._snapshot(), self._route())

        for row in (0, 6, 12, 32, 64, 102, 159):
            self.assertEqual(native.judgment_time(1, row), 10_445.0)

        ordinary = native.blocks[3]
        self.assertGreater(ordinary.ms_per_line, 0.0)
        self.assertAlmostEqual(
            native.judgment_time(3, 1),
            ordinary.start_time_ms + ordinary.ms_per_line,
        )

    def test_get_block_skips_zero_duration_divs_at_their_start_boundary(self) -> None:
        native = build_native_timing(self._snapshot(), self._route())

        self.assertEqual(native.get_block(9_999.0), 0)
        self.assertEqual(native.get_block(10_000.0), 1)
        self.assertEqual(native.get_block(10_200.0), 1)
        self.assertEqual(native.get_block(10_445.0), 2)
        # At 10890 the zero-duration Skip is passed and the overlapping normal
        # Div becomes current, matching Step.GetBlock's <= end-time walk.
        self.assertEqual(native.get_block(10_890.0), 3)

    def test_absolute_current_future_coordinates_equal_native_get_block_beat(self) -> None:
        native = build_native_timing(self._snapshot(), self._route())
        state = native.state_at(10_200.0)
        self.assertEqual(state.block_index, 1)

        current_position = native.current_position_from_state(state)
        for target_block, target_line in ((1, 0), (1, 6), (2, 0), (2, 32), (3, 4)):
            absolute = native.line_position(target_block, target_line)
            self.assertAlmostEqual(
                absolute - current_position,
                native.block_beat_from_state(target_block, target_line, state),
            )

    def test_skip_route_stream_uses_native_position_axis(self) -> None:
        stream = build_event_stream(self._snapshot(), self._route())
        self.assertTrue(stream.uses_native_skip_projection)
        native = stream.native_timing
        assert native is not None
        state = native.state_at(10_200.0)
        self.assertAlmostEqual(
            stream.position_at(10_200.0),
            native.current_position_from_state(state),
        )

    def test_event_stream_keeps_nonzero_skip_rows_judgeable_at_start_time(self) -> None:
        stream = build_event_stream(self._snapshot(), self._route())
        candidates = [
            event
            for event in stream.events
            if event.native_block_index == 1 and event.row_index == 102
        ]
        self.assertTrue(candidates)
        self.assertTrue(any(event.registers for event in candidates))
        self.assertTrue(all(event.time_ms == 10_445.0 for event in candidates))

    def test_raw_negative_speed_delay_does_not_shift_native_judgment_time(self) -> None:
        stream = build_event_stream(self._snapshot(), self._route())
        event = next(
            event
            for event in stream.events
            if event.native_block_index == 1 and event.row_index == 0
        )
        self.assertEqual(event.time_ms, 10_445.0)


if __name__ == "__main__":
    unittest.main()
