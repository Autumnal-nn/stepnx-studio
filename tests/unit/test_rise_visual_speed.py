from __future__ import annotations

import struct
import unittest
from dataclasses import replace

from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import InsertMetadata, SetNoteAt
from stepnx.preview import (
    BASE_ARROW_Y,
    LINE_BASE_START_GAP_TIME,
    LINE_BASE_START_Y,
    LINE_BASE_VELOCITY,
    NOTE_RENDER_UNIT,
    GameplaySession,
    RoutePolicy,
    RuntimeSpeedState,
    build_event_stream,
    create_preview_snapshot,
    native_base_velocity_pixels,
    parse_gameplay_command,
    resolve_route,
)
from tests.fixture_factory import make_normal_nx20


def _f32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _single_block_stream(
    *,
    speed: float = 1.0,
    gap_ms: float = 0.0,
    scroll: float = 0.25,
):
    document = parse_bytes(make_normal_nx20(), source="NM.NX", row_storage="compact")
    split = document.splits[0]
    block = replace(
        split.blocks[0],
        start_time=split.blocks[0].start_time.with_value(0.0),
        bpm=split.blocks[0].bpm.with_value(120.0),
        scroll=split.blocks[0].scroll.with_value(scroll),
        offset_or_delay=split.blocks[0].offset_or_delay.with_value(gap_ms),
        speed_or_freeze=split.blocks[0].speed_or_freeze.with_value(speed),
        smooth_speed=split.blocks[0].smooth_speed.with_value(0),
    )
    document = replace(document, splits=(replace(split, blocks=(block,)),))
    document = SetNoteAt(block.rows[1].stable_id, 0, b"\x03\x03\x00\x00").apply(
        document
    )
    snapshot = create_preview_snapshot(document)
    return build_event_stream(snapshot, resolve_route(snapshot, RoutePolicy.MANUAL))


class RiseVisualSpeedTests(unittest.TestCase):
    def test_linebase_velocity_uses_runtime_constants_not_lane_spacing(self) -> None:
        self.assertEqual(BASE_ARROW_Y, 608.0)
        self.assertEqual(LINE_BASE_START_Y, 50.0)
        self.assertEqual(LINE_BASE_START_GAP_TIME, 8.5)
        self.assertAlmostEqual(LINE_BASE_VELOCITY, (608.0 - 50.0) / 8.5)
        self.assertEqual(NOTE_RENDER_UNIT, 72.0)
        self.assertAlmostEqual(
            native_base_velocity_pixels(72.0),
            LINE_BASE_VELOCITY,
        )
        self.assertAlmostEqual(
            native_base_velocity_pixels(80.0),
            80.0 * LINE_BASE_VELOCITY / 72.0,
        )

    def test_speedproc_moves_high_speed_by_point_zero_five_per_60hz_tick(self) -> None:
        state = RuntimeSpeedState.initialized(2.0)
        state.set_speed(3.0)

        state.advance(16.0)
        self.assertAlmostEqual(state.high_speed, 2.0)
        state.advance(1.0)
        self.assertAlmostEqual(state.high_speed, 2.05, places=5)

        state.advance(9 * (1000.0 / 60.0) + 0.1)
        self.assertAlmostEqual(state.high_speed, 2.5, places=4)
        self.assertAlmostEqual(state.mode_speed, 3.0)

    def test_block_speed_snap_and_user_speed_easing_are_separate(self) -> None:
        state = RuntimeSpeedState.initialized(2.0, 1.0)
        state.set_block_speed(3.0, snap=True)
        self.assertAlmostEqual(state.high_speed, 6.0)

        state.set_speed(4.0)
        self.assertAlmostEqual(state.mode_speed, 12.0)
        self.assertAlmostEqual(state.high_speed, 6.0)
        state.advance(1000.0 / 60.0 + 0.1)
        self.assertAlmostEqual(state.high_speed, 6.05, places=4)

    def test_positive_gap_roundtrips_through_loader_and_current_gap(self) -> None:
        stream = _single_block_stream(speed=1.0, gap_ms=125.0, scroll=0.25)
        div = stream.native_timing.blocks[0]

        self.assertAlmostEqual(div.ms_per_line, 125.0)
        self.assertAlmostEqual(div.gap_beats, 0.25)
        self.assertAlmostEqual(div.current_gap_ms, 125.0)
        self.assertAlmostEqual(stream.current_gap_at(0.0), 125.0)

    def test_negative_speed_zeroes_gap_without_creating_visual_freeze(self) -> None:
        stream = _single_block_stream(speed=-3.0, gap_ms=500.0, scroll=0.25)
        div = stream.native_timing.blocks[0]

        self.assertEqual(div.speed, 3.0)
        self.assertEqual(div.gap_beats, 0.0)
        self.assertEqual(div.current_gap_ms, 0.0)
        self.assertEqual(stream.timing[0].freeze_delay_ms, 0.0)
        self.assertEqual(stream.timing[0].start_time_ms, div.start_time_ms)

    def test_normal_routes_use_native_block_line_position_axis(self) -> None:
        stream = _single_block_stream(speed=1.0, gap_ms=0.0, scroll=0.25)
        event = next(event for event in stream.events if event.row_index == 1)

        self.assertAlmostEqual(
            event.position,
            stream.native_timing.line_position(0, 1),
        )
        self.assertAlmostEqual(stream.position_at(62.5), 0.125)
        self.assertAlmostEqual(stream.beat_distance_at(event, 62.5), 0.125)

    def test_header_speed_is_applied_after_launch_speed(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX")
        document = InsertMetadata.from_ints(
            document.stable_id, 1111, _f32_bits(1.5)
        ).apply(document)
        snapshot = create_preview_snapshot(document)
        stream = build_event_stream(snapshot, resolve_route(snapshot, RoutePolicy.MANUAL))

        self.assertAlmostEqual(stream.modifier_for_launch_speed(4.0).speed, 6.0)

        document = InsertMetadata.from_ints(
            document.stable_id, 0, _f32_bits(12.0)
        ).apply(document)
        snapshot = create_preview_snapshot(document)
        stream = build_event_stream(snapshot, resolve_route(snapshot, RoutePolicy.MANUAL))
        # ID 0 decodes 12 -> 3 and replaces the launch speed before 1111 x1.5.
        self.assertAlmostEqual(stream.modifier_for_launch_speed(9.0).speed, 4.5)

    def test_session_exposes_high_speed_easing_without_rewriting_command_target(self) -> None:
        stream = _single_block_stream(speed=1.0)
        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=True)

        self.assertAlmostEqual(session.selected_speed, 1.0)
        self.assertAlmostEqual(session.high_speed, 1.0)
        session.select_speed(3)
        self.assertAlmostEqual(session.selected_speed, 3.0)
        self.assertAlmostEqual(session.command.speed, 3.0)
        self.assertAlmostEqual(session.high_speed, 1.0)

        session.advance(1000.0 / 60.0 + 0.1)
        self.assertAlmostEqual(session.high_speed, 1.05, places=4)


if __name__ == "__main__":
    unittest.main()
