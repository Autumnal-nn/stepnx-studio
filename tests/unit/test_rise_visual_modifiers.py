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
    LINE_BASE_X_AMPLITUDE,
    LINE_BASE_Y_MAX,
    LINE_BASE_Y_MIN,
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
    native_acc_dec_offset,
    native_line_local_y,
    native_line_y,
    native_snake_x_offset,
    parse_gameplay_command,
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
        self.assertEqual(LINE_BASE_X_AMPLITUDE, 20.0)
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

        # pHighSpeed scales the already-curved displacement around the receptor.
        self.assertAlmostEqual(
            BASE_ARROW_Y - speed2,
            2.0 * (BASE_ARROW_Y - local),
        )
        # This would differ if speed were incorrectly multiplied into beat
        # distance before GetAccDecYOffset.
        wrong_base = BASE_ARROW_Y - distance * LINE_BASE_VELOCITY * 2.0
        wrong = wrong_base + native_acc_dec_offset(wrong_base, AccDecMode.ACCELERATION)
        self.assertNotAlmostEqual(speed2, wrong)

    def test_snake_uses_native_y_normalization_sine_and_amplitude(self) -> None:
        span = LINE_BASE_Y_MAX - LINE_BASE_Y_MIN
        self.assertAlmostEqual(
            native_snake_x_offset(LINE_BASE_Y_MIN, 72.0),
            0.0,
            places=6,
        )
        self.assertAlmostEqual(
            native_snake_x_offset(LINE_BASE_Y_MIN + span * 0.25, 72.0),
            20.0,
            places=6,
        )
        # R!SE uses its float32 pi constant, so mathematical pi leaves a tiny
        # nonzero residue at the half-cycle instead of an exact Python zero.
        self.assertAlmostEqual(
            native_snake_x_offset(LINE_BASE_Y_MIN + span * 0.50, 72.0),
            0.0,
            delta=2.0e-6,
        )
        self.assertAlmostEqual(
            native_snake_x_offset(LINE_BASE_Y_MIN + span * 0.75, 72.0),
            -20.0,
            places=6,
        )
        self.assertEqual(native_snake_x_offset(LINE_BASE_Y_MAX, 72.0), 0.0)


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
                self.assertEqual(x, 540.0 if base & SequenceZoneTransform.UNDER_ATTACK else 100.0)


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


class RiseSpeedModeTests(unittest.TestCase):
    def test_earthworm_fast_and_slow_branches_match_drawstep_boundaries(self) -> None:
        # DrawStep reads Div._BPM after StepLoader has overwritten that slot
        # with msPerLine. 125 ms/line * BeatSplit 4 = 500 ms/beat, so it takes
        # the >=333.33334 branch.
        self.assertEqual(earthworm_user_speed(0.0, 125.0, 4), 3.0)
        self.assertEqual(earthworm_user_speed(250.9, 125.0, 4), 3.0)
        self.assertEqual(earthworm_user_speed(251.0, 125.0, 4), 2.0)
        self.assertEqual(earthworm_user_speed(500.0, 125.0, 4), 3.0)

        # 62.5 ms/line * BeatSplit 4 = 250 ms/beat, below the threshold.
        self.assertEqual(earthworm_user_speed(0.0, 62.5, 4), 2.0)
        self.assertEqual(earthworm_user_speed(180.9, 62.5, 4), 2.0)
        self.assertEqual(earthworm_user_speed(181.0, 62.5, 4), 1.0)
        self.assertEqual(earthworm_user_speed(360.0, 62.5, 4), 2.0)

        # Skip sets msPerLine / loaded _BPM to zero and therefore uses the
        # low-density 360 ms branch regardless of authored BPM.
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
        self.assertEqual(len(COMMAND_FLAGS), 14)
        codes = tuple(flag.code for flag in COMMAND_FLAGS)
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(
            codes,
            (
                "v",
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
                "s",
                "e",
            ),
        )
        self.assertEqual(serialize_command_flags(("m", "v", "e")), "vme")
        self.assertEqual(serialize_command_flags(("!", "u")), "u!")
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


if __name__ == "__main__":
    unittest.main()
