from __future__ import annotations

import unittest

from stepnx.codecs.nx20 import parse_bytes
from stepnx.preview.events import build_event_stream
from stepnx.preview.routes import (
    PreviewMetrics,
    ResolvedRoute,
    RouteDecision,
    RoutePolicy,
)
from stepnx.preview.snapshot import PreviewBlock, PreviewSnapshot, PreviewSplit
from tests.fixture_factory import make_normal_nx20


class PreviewSkipFlagRegressionTests(unittest.TestCase):
    @staticmethod
    def _snapshot(*, flags: int, delay_ms: float, speed: float = -2.0) -> PreviewSnapshot:
        document = parse_bytes(make_normal_nx20(), source="PUPA-regression.NX")
        rows = document.splits[0].blocks[0].rows
        first_block = PreviewBlock(
            stable_id=101,
            split_id=100,
            index=0,
            start_time_ms=10_000.0,
            bpm=25.25,
            scroll=1.0 / 32.0,
            offset_or_delay_ms=delay_ms,
            speed_or_freeze=speed,
            beat_split=32,
            beat_measure=4,
            smooth_speed=flags,
            rows=rows,
            conditions=(),
            triggers=(),
            brain_question_count=0,
        )
        overlapping_block = PreviewBlock(
            stable_id=201,
            split_id=200,
            index=0,
            start_time_ms=10_000.0,
            bpm=101.0,
            scroll=1.0 / 8.0,
            offset_or_delay_ms=0.0,
            speed_or_freeze=1.0,
            beat_split=8,
            beat_measure=4,
            smooth_speed=0,
            rows=rows,
            conditions=(),
            triggers=(),
            brain_question_count=0,
        )
        return PreviewSnapshot(
            document_stable_id=1,
            source_name="PUPA-regression.NX",
            profile="nxa-native",
            start_column=0,
            columns=5,
            splits=(
                PreviewSplit(100, 0, 0, False, False, False, 0, (first_block,)),
                PreviewSplit(200, 1, 0, False, False, False, 0, (overlapping_block,)),
            ),
            diagnostics=(),
        )

    @staticmethod
    def _route() -> ResolvedRoute:
        return ResolvedRoute(
            policy=RoutePolicy.MANUAL,
            seed=None,
            decisions=(
                RouteDecision(100, 101, RoutePolicy.MANUAL, "fixture", (101,)),
                RouteDecision(200, 201, RoutePolicy.MANUAL, "fixture", (201,)),
            ),
            final_metrics=PreviewMetrics(),
            diagnostics=(),
        )

    def test_skip_flag_does_not_turn_freeze_gap_into_a_start_time_shift(self) -> None:
        stream = build_event_stream(
            self._snapshot(flags=0x02, delay_ms=445.0), self._route()
        )

        first, second = stream.timing
        self.assertEqual(first.block_id, 101)
        self.assertEqual(second.block_id, 201)
        self.assertEqual(first.start_time_ms, 10_000.0)
        self.assertEqual(second.start_time_ms, 10_000.0)
        self.assertEqual(first.freeze_delay_ms, 0.0)

    def test_normal_freeze_still_applies_its_delay(self) -> None:
        stream = build_event_stream(
            self._snapshot(flags=0x00, delay_ms=445.0), self._route()
        )
        freeze_segment = next(segment for segment in stream.timing if segment.block_id == 101)

        self.assertEqual(freeze_segment.freeze_delay_ms, 445.0)
        self.assertEqual(freeze_segment.start_time_ms, 10_445.0)

    def test_skip_with_zero_delay_keeps_existing_preview_timing(self) -> None:
        stream = build_event_stream(
            self._snapshot(flags=0x02, delay_ms=0.0), self._route()
        )
        first = stream.timing[0]

        self.assertEqual(first.block_id, 101)
        self.assertEqual(first.start_time_ms, 10_000.0)
        self.assertEqual(first.freeze_delay_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
