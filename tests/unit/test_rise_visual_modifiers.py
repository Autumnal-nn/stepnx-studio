from __future__ import annotations

import math
import unittest
from dataclasses import replace

from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import InsertMetadata, SetNoteAt
from stepnx.preview import (
    BASE_ARROW_Y,
    COMMAND_FLAGS,
    LINE_BASE_ACC_OFFSET,
    LINE_BASE_ACC_POW,
    LINE_BASE_ACC_SCALE,
    LINE_BASE_VELOCITY,
    LINE_BASE_WAVE_RATE,
    LINE_BASE_Y_MAX,
    LINE_BASE_Y_MIN,
    PRIME2_SNAKE_AMPLITUDE,
    PRIME2_THROW_AMPLITUDE,
    PRIME2_THROW_CAMERA_EYE_Z,
    PRIME2_THROW_SPAN,
    PRIME2_ZIGZAG_KEYFRAME_COUNT,
    AccDecMode,
    GameplaySession,
    RoutePolicy,
    SequenceZoneTransform,
    SpeedMode,
    VisibilityMode,
    apply_global_visibility_effect,
    build_event_stream,
    create_preview_snapshot,
    earthworm_user_speed,
    legacy_acc_dec_distance,
    native_acc_dec_offset,
    native_line_local_y,
    native_line_y,
    parse_gameplay_command,
    prime2_snake_path_lane_position,
    prime2_snake_x_offset,
    prime2_throw_perspective_scale,
    prime2_throw_y_offset,
    prime2_throw_z_offset,
    prime2_zigzag_keyframes,
    random_velocity_triggers,
    random_velocity_user_speed,
    resolve_route,
    serialize_command_flags,
    transform_sequence_zone_point,
)
from tests.fixture_factory import make_normal_nx20


def _stream_with_header(metadata_id: int | None = None, value: int = 0):
    document = parse_bytes(make_normal_nx20(), source="NM.NX")
    split = document.splits[0]
    block = replace(
        split.blocks[0],
        start_time=split.blocks[0].start_time.with_value(0.0),
        bpm=split.blocks[0].bpm.with_value(120.0),
        smooth_speed=split.blocks[0].smooth_speed.with_value(0),
        speed_or_freeze=split.blocks[0].speed_or_freeze.with_value(1.0),
    )
    document = replace(document, splits=(replace(split, blocks=(block,)),))
    if metadata_id is not None:
        document = InsertMetadata.from_ints(document.stable_id, metadata_id, value).apply(
            document
        )
    snapshot = create_preview_snapshot(document)
    return document, build_event_stream(
        snapshot,
        resolve_route(snapshot, RoutePolicy.MANUAL),
    )


class RiseLineBaseVisualTests(unittest.TestCase):
    def test_linebase_constructor_defaults_match_binary(self) -> None:
        self.assertEqual(LINE_BASE_Y_MIN, 200.0)
        self.assertEqual(LINE_BASE_Y_MAX, 550.0)
        self.assertEqual(LINE_BASE_WAVE_RATE, 2.0)
        self.assertEqual(LINE_BASE_ACC_POW, 1.5)
        self.assertEqual(LINE_BASE_ACC_SCALE, 1.0)
        self.assertEqual(LINE_BASE_ACC_OFFSET, -200.0)

    def test_accel_and_decel_use_native_normalized_power_curves(self) -> None:
        midpoint = (LINE_BASE_Y_MIN + LINE_BASE_Y_MAX) / 2.0
        half_pow = math.pow(0.5, LINE_BASE_ACC_POW)

        self.assertEqual(
            native_acc_dec_offset(LINE_BASE_Y_MAX, AccDecMode.ACCELERATION),
            0.0,
        )
        self.assertEqual(
            native_acc_dec_offset(midpoint, AccDecMode.LINEAR),
            0.0,
        )
        self.assertAlmostEqual(
            native_acc_dec_offset(midpoint, AccDecMode.ACCELERATION),
            (1.0 - half_pow) * -200.0,
        )
        self.assertAlmostEqual(
            native_acc_dec_offset(midpoint, AccDecMode.DECELERATION),
            half_pow * -200.0,
        )

    def test_accdec_is_applied_before_high_speed_parent_scale(self) -> None:
        distance = (BASE_ARROW_Y - (LINE_BASE_Y_MIN + 70.0)) / LINE_BASE_VELOCITY
        local = native_line_local_y(distance, AccDecMode.ACCELERATION)
        speed2 = native_line_y(distance, 2.0, AccDecMode.ACCELERATION)

        self.assertAlmostEqual(
            BASE_ARROW_Y - speed2,
            2.0 * (BASE_ARROW_Y - local),
        )
        wrong_base = BASE_ARROW_Y - distance * LINE_BASE_VELOCITY * 2.0
        wrong = wrong_base + native_acc_dec_offset(wrong_base, AccDecMode.ACCELERATION)
        self.assertNotAlmostEqual(speed2, wrong)

    def test_prime_and_nxa_legacy_accdec_formulas_match_recovered_constants(self) -> None:
        # Both supplied executables map mode 2 to x^3/1600 (Deceleration) and
        # mode 1 to 600 - 50000/(x+83.33333587646484) (Acceleration).
        self.assertAlmostEqual(
            legacy_acc_dec_distance(0.0, 1.0, 60.0, AccDecMode.ACCELERATION),
            600.0 - 50000.0 / 83.33333587646484,
            places=10,
        )
        self.assertAlmostEqual(
            legacy_acc_dec_distance(0.0, 1.0, 60.0, AccDecMode.DECELERATION),
            0.0,
            places=5,
        )
        beat_for_x100 = 100.0 / 60.0
        self.assertAlmostEqual(
            legacy_acc_dec_distance(
                beat_for_x100, 1.0, 60.0, AccDecMode.DECELERATION
            ),
            625.0,
            places=5,
        )
        self.assertAlmostEqual(
            legacy_acc_dec_distance(
                beat_for_x100, 1.0, 60.0, AccDecMode.ACCELERATION
            ),
            600.0 - 50000.0 / (100.0 + 83.33333587646484),
            places=5,
        )

    def test_prime_snake_path_uses_nine_permutation_keyframes_and_div_phase(self) -> None:
        frames = prime2_zigzag_keyframes(5, 123)
        self.assertEqual(len(frames), PRIME2_ZIGZAG_KEYFRAME_COUNT)
        for frame in frames:
            self.assertEqual(sorted(frame), list(range(5)))

        lane = 2
        self.assertEqual(frames[0], tuple(range(5)))
        at_boundary = prime2_snake_path_lane_position(
            lane, 1.0, 5, 123, start=1.0, interval=2.0
        )
        just_above = prime2_snake_path_lane_position(
            lane, 1.000001, 5, 123, start=1.0, interval=2.0
        )
        self.assertEqual(at_boundary, float(lane))
        self.assertAlmostEqual(just_above, float(lane), places=5)
        halfway = prime2_snake_path_lane_position(
            lane, 2.0, 5, 123, start=1.0, interval=2.0
        )
        self.assertAlmostEqual(
            halfway, (frames[0][lane] + frames[1][lane]) / 2.0
        )
        self.assertEqual(
            prime2_snake_path_lane_position(
                lane, 100.0, 5, 123, start=1.0, interval=2.0
            ),
            float(frames[-1][lane]),
        )

    def test_runtime_stream_preserves_block_221_222_for_snake_path(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX")
        block = document.splits[0].blocks[0]
        document = InsertMetadata.from_ints(block.stable_id, 221, 3).apply(document)
        document = InsertMetadata.from_ints(block.stable_id, 222, 5).apply(document)
        snapshot = create_preview_snapshot(document)
        stream = build_event_stream(
            snapshot, resolve_route(snapshot, RoutePolicy.MANUAL)
        )
        self.assertEqual(stream.block_param(block.stable_id, 221), 3.0)
        self.assertEqual(stream.block_param(block.stable_id, 222), 5.0)
        self.assertEqual(stream.block_param(block.stable_id, 999, 7.0), 7.0)

    def test_prime2_arbitrates_legacy_snake_at_thirty_units(self) -> None:
        # Supplied Prime 2 exec: sinf(pi*phase) * 60.0 * 0.5.
        self.assertEqual(PRIME2_SNAKE_AMPLITUDE, 30.0)
        self.assertAlmostEqual(prime2_snake_x_offset(0.5, 60.0), 30.0, places=5)
        self.assertAlmostEqual(prime2_snake_x_offset(1.5, 60.0), -30.0, places=5)

    def test_prime2_sink_and_rise_are_opposite_z_depths(self) -> None:
        self.assertEqual(PRIME2_THROW_SPAN, 453.0)
        self.assertEqual(PRIME2_THROW_AMPLITUDE, 96.0)
        self.assertEqual(PRIME2_THROW_CAMERA_EYE_Z, 600.0)
        half_peak_beat = PRIME2_THROW_SPAN / (2.0 * 60.0 * 1.0)
        sink_z = prime2_throw_z_offset(half_peak_beat, 1.0, rise=False)
        rise_z = prime2_throw_z_offset(half_peak_beat, 1.0, rise=True)
        self.assertAlmostEqual(sink_z, 96.0, places=5)
        self.assertAlmostEqual(rise_z, -96.0, places=5)
        self.assertGreater(prime2_throw_perspective_scale(sink_z), 1.0)
        self.assertLess(prime2_throw_perspective_scale(rise_z), 1.0)
        # Compatibility wrapper retains the old scalar API but is not used as Y.
        self.assertAlmostEqual(
            prime2_throw_y_offset(half_peak_beat, 1.0, 60.0, rise=False),
            96.0,
            places=5,
        )

    def test_legacy_vanish_and_appear_keep_continuous_fade(self) -> None:
        vanish = parse_gameplay_command("v")
        appear = parse_gameplay_command("p")
        for distance, vanish_expected, appear_expected in (
            (200.0, 1.0, 0.0),
            (100.0, 0.5, 0.5),
            (50.0, 0.25, 0.75),
            (0.0, 0.0, 1.0),
        ):
            self.assertAlmostEqual(
                vanish.note_opacity(
                    3, distance=distance, fade_distance=200.0, time_ms=0.0
                ),
                vanish_expected,
            )
            self.assertAlmostEqual(
                appear.note_opacity(
                    3, distance=distance, fade_distance=200.0, time_ms=0.0
                ),
                appear_expected,
            )


class SequenceZoneTransformTests(unittest.TestCase):
    def test_native_ua_drop_are_independent_affine_bits(self) -> None:
        width = 640.0
        height = 480.0
        point = (100.0, 413.0)

        self.assertEqual(
            transform_sequence_zone_point(
                *point,
                SequenceZoneTransform.NORMAL,
                width,
                height,
                normal_receptor_y=413.0,
            ),
            (100.0, 413.0),
        )
        self.assertEqual(
            transform_sequence_zone_point(
                *point,
                SequenceZoneTransform.DROP,
                width,
                height,
                normal_receptor_y=413.0,
            ),
            (100.0, 67.0),
        )
        self.assertEqual(
            transform_sequence_zone_point(
                *point,
                SequenceZoneTransform.UNDER_ATTACK,
                width,
                height,
                normal_receptor_y=413.0,
            ),
            (540.0, 67.0),
        )
        self.assertEqual(
            transform_sequence_zone_point(
                *point,
                SequenceZoneTransform.UNDER_ATTACK | SequenceZoneTransform.DROP,
                width,
                height,
                normal_receptor_y=413.0,
            ),
            (540.0, 413.0),
        )

    def test_patched_mid_moves_receptor_to_exact_midpoint_under_all_compositions(self) -> None:
        width = 640.0
        height = 480.0
        receptor = (100.0, 413.0)
        for base in (
            SequenceZoneTransform.NORMAL,
            SequenceZoneTransform.UNDER_ATTACK,
            SequenceZoneTransform.DROP,
            SequenceZoneTransform.UNDER_ATTACK | SequenceZoneTransform.DROP,
        ):
            with self.subTest(base=base):
                x, y = transform_sequence_zone_point(
                    *receptor,
                    base | SequenceZoneTransform.MID,
                    width,
                    height,
                    normal_receptor_y=413.0,
                )
                self.assertEqual(y, 240.0)
                self.assertEqual(
                    x,
                    540.0 if base & SequenceZoneTransform.UNDER_ATTACK else 100.0,
                )


class RiseVisibilityTests(unittest.TestCase):
    def test_header_visibility_replaces_only_low_effect_nibble(self) -> None:
        self.assertEqual(
            apply_global_visibility_effect(0x13, VisibilityMode.VISIBLE), 0x13
        )
        self.assertEqual(
            apply_global_visibility_effect(0x13, VisibilityMode.VANISH), 0x12
        )
        self.assertEqual(
            apply_global_visibility_effect(0x13, VisibilityMode.APPEAR), 0x11
        )
        self.assertEqual(
            apply_global_visibility_effect(0x13, VisibilityMode.HIDDEN), 0x10
        )

    def test_runtime_stream_projects_header_visibility_without_mutating_document(self) -> None:
        for mode, expected in ((1, 0x12), (2, 0x11), (3, 0x10)):
            with self.subTest(mode=mode):
                document = parse_bytes(make_normal_nx20(), source="NM.NX")
                block = document.splits[0].blocks[0]
                document = SetNoteAt(
                    block.rows[0].stable_id,
                    0,
                    b"\x03\x13\x00\x00",
                ).apply(document)
                document = InsertMetadata.from_ints(
                    document.stable_id,
                    16,
                    mode,
                ).apply(document)
                canonical_raw = document.splits[0].blocks[0].rows[0].cells[0].raw
                snapshot = create_preview_snapshot(document)
                stream = build_event_stream(
                    snapshot,
                    resolve_route(snapshot, RoutePolicy.MANUAL),
                )
                event = next(
                    item
                    for item in stream.events
                    if item.row_index == 0 and item.lane == 0
                )

                self.assertEqual(canonical_raw, b"\x03\x13\x00\x00")
                self.assertEqual(event.raw, bytes((0x03, expected, 0x00, 0x00)))
                self.assertEqual(event.visual_effect & 0x10, 0x10)
                self.assertTrue(event.snake_path)


class RiseSpeedModeTests(unittest.TestCase):
    def test_earthworm_fast_and_slow_branches_match_drawstep_boundaries(self) -> None:
        self.assertEqual(earthworm_user_speed(0.0, 125.0, 4), 3.0)
        self.assertEqual(earthworm_user_speed(250.9, 125.0, 4), 3.0)
        self.assertEqual(earthworm_user_speed(251.0, 125.0, 4), 2.0)
        self.assertEqual(earthworm_user_speed(500.0, 125.0, 4), 3.0)
        self.assertEqual(earthworm_user_speed(0.0, 62.5, 4), 2.0)
        self.assertEqual(earthworm_user_speed(180.9, 62.5, 4), 2.0)
        self.assertEqual(earthworm_user_speed(181.0, 62.5, 4), 1.0)
        self.assertEqual(earthworm_user_speed(360.0, 62.5, 4), 2.0)
        self.assertEqual(earthworm_user_speed(181.0, 0.0, 4), 1.0)

    def test_random_velocity_uses_line_48_gate_and_modulo_four_speed(self) -> None:
        self.assertTrue(random_velocity_triggers(0))
        self.assertFalse(random_velocity_triggers(47))
        self.assertTrue(random_velocity_triggers(48))
        self.assertTrue(random_velocity_triggers(96))
        self.assertEqual(
            tuple(random_velocity_user_speed(value) for value in range(8)),
            (1.0, 2.0, 3.0, 4.0, 1.0, 2.0, 3.0, 4.0),
        )

    def test_header_and_command_earthworm_drive_modespeed_not_x_motion(self) -> None:
        _, header_stream = _stream_with_header(1, 1)
        header_session = GameplaySession(
            header_stream,
            parse_gameplay_command(""),
            autoplay=True,
        )
        self.assertIs(header_session.speed_mode, SpeedMode.EARTHWORM)
        header_session.advance(17.0)
        self.assertAlmostEqual(header_session.mode_speed, 3.0)
        self.assertAlmostEqual(header_session.high_speed, 1.05, places=4)

        _, command_stream = _stream_with_header()
        command_session = GameplaySession(
            command_stream,
            parse_gameplay_command("e"),
            autoplay=True,
        )
        self.assertIs(command_session.speed_mode, SpeedMode.EARTHWORM)
        command_session.advance(17.0)
        self.assertAlmostEqual(command_session.mode_speed, 3.0)

    def test_native_timing_retains_loaded_bpm_slot_for_earthworm(self) -> None:
        _, stream = _stream_with_header()
        div = stream.native_timing.blocks[0]
        self.assertAlmostEqual(div.ms_per_line, 125.0)
        self.assertAlmostEqual(div.bpm, div.ms_per_line)
        self.assertEqual(div.beat_split, 4)

    def test_speed_modes_are_independent_of_external_advance_chunking(self) -> None:
        _, stream = _stream_with_header(1, 1)
        coarse = GameplaySession(stream, parse_gameplay_command(""), autoplay=True)
        fine = GameplaySession(stream, parse_gameplay_command(""), autoplay=True)

        coarse.advance(260.0)
        for moment in range(10, 261, 10):
            fine.advance(float(moment))

        self.assertEqual(coarse.mode_speed, fine.mode_speed)
        self.assertEqual(coarse.high_speed, fine.high_speed)
        self.assertEqual(coarse.block_speed, fine.block_speed)

    def test_random_velocity_rerolls_each_drawstep_tick_on_qualifying_line(self) -> None:
        import random

        _, stream = _stream_with_header(1, 2)
        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=True)
        expected_rng = random.Random(stream.route.seed or 0)

        first = random_velocity_user_speed(expected_rng.randrange(0, 0x7FFFFFFF))
        second = random_velocity_user_speed(expected_rng.randrange(0, 0x7FFFFFFF))

        session.advance(17.0)
        self.assertEqual(session.mode_speed, first)
        session.advance(34.0)
        self.assertEqual(session.mode_speed, second)

    def test_non_ui_command_order_resolves_mutually_exclusive_speed_modes(self) -> None:
        _, stream = _stream_with_header()
        self.assertIs(
            GameplaySession(stream, parse_gameplay_command("se")).speed_mode,
            SpeedMode.EARTHWORM,
        )
        self.assertIs(
            GameplaySession(stream, parse_gameplay_command("es")).speed_mode,
            SpeedMode.RANDOM_VELOCITY,
        )


class CommandRegistryTests(unittest.TestCase):
    def test_registry_is_complete_unique_and_serializes_in_ui_order(self) -> None:
        self.assertEqual(len(COMMAND_FLAGS), 19)
        codes = tuple(flag.code for flag in COMMAND_FLAGS)
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(
            codes,
            (
                "v",
                "p",
                "n",
                "w",
                "f",
                "m",
                "r",
                "u",
                "!",
                "j",
                "d",
                "a",
                "x",
                "^",
                "(",
                ")",
                "z",
                "s",
                "e",
            ),
        )
        self.assertEqual(serialize_command_flags(("m", "v", "e")), "vme")
        self.assertEqual(serialize_command_flags(("!", "u")), "u!")
        self.assertEqual(serialize_command_flags(("^", "x")), "x^")
        nx = parse_gameplay_command("x^")
        self.assertTrue(nx.exceed_mode)
        self.assertTrue(nx.nx_mode)
        self.assertEqual(nx.pending_effects, ("^",))
        with self.assertRaisesRegex(ValueError, "unsupported COMMAND"):
            serialize_command_flags(("v", "?"))

    def test_ua_drop_and_random_are_not_fixed_lane_permutations(self) -> None:
        command = parse_gameplay_command("ur!")
        self.assertTrue(command.under_attack)
        self.assertTrue(command.drop)
        self.assertTrue(command.randomize)
        self.assertEqual(command.lane_map(5, seed=123), (0, 1, 2, 3, 4))

        mirror = parse_gameplay_command("m")
        self.assertEqual(mirror.lane_map(5), (4, 3, 2, 1, 0))

    def test_appear_and_vanish_compose_to_hidden(self) -> None:
        command = parse_gameplay_command("vp")
        self.assertTrue(command.vanish)
        self.assertTrue(command.appear)
        self.assertEqual(
            command.note_opacity(
                3,
                distance=100.0,
                fade_distance=200.0,
                time_ms=0.0,
            ),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
