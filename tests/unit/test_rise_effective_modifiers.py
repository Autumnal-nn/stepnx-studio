from __future__ import annotations

import struct
import unittest

from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import InsertMetadata
from stepnx.preview import (
    AccDecMode,
    ComboDisplay,
    DirectionMode,
    EffectiveModifier,
    RoutePolicy,
    SpeedMode,
    StepParam,
    ThrowMode,
    VisibilityMode,
    apply_step_params,
    build_event_stream,
    create_preview_snapshot,
    resolve_route,
)
from tests.fixture_factory import make_normal_nx20


def _f32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


class RiseEffectiveModifierTests(unittest.TestCase):
    def test_clear_defaults_match_game_and_common_modifier(self) -> None:
        modifier = EffectiveModifier()
        self.assertEqual(modifier.skins, (0, 0, 0, 0, 0, 0))
        self.assertEqual(modifier.speed, 2.0)
        self.assertIs(modifier.speed_mode, SpeedMode.STATIC)
        self.assertIs(modifier.acc_dec, AccDecMode.LINEAR)
        self.assertIs(modifier.visibility, VisibilityMode.VISIBLE)
        self.assertIs(modifier.direction, DirectionMode.NORMAL)
        self.assertEqual(modifier.perfect_frame, 2.5)
        self.assertEqual(modifier.interval_frame, 2.5)
        self.assertFalse(modifier.combo_per_bank)
        self.assertFalse(modifier.merge_combo)
        self.assertEqual(modifier.gauge_link_factor, 0)
        self.assertEqual(modifier.speed_boost, 0.0)

    def test_step_param_lookup_is_first_match_and_minus_one_is_no_override(self) -> None:
        modifier = apply_step_params(
            (
                StepParam(1, 1),
                StepParam(1, 2),
                StepParam(17, 0xFFFFFFFF),
                StepParam(18, 7),
            )
        )

        self.assertIs(modifier.speed_mode, SpeedMode.EARTHWORM)
        self.assertFalse(modifier.freedom)
        self.assertTrue(modifier.flash)

    def test_float_parameters_reinterpret_raw_bits_before_runtime_math(self) -> None:
        modifier = apply_step_params(
            (
                StepParam(0, _f32_bits(12.0)),
                StepParam(70, _f32_bits(2.25)),
                StepParam(1111, _f32_bits(1.5)),
            )
        )

        # Header 0: 12.0 / 4 = 3.0, then mpmSpeedX multiplies by 1.5.
        self.assertEqual(modifier.speed, 4.5)
        self.assertEqual(modifier.alt_skin_score_factor, 1.25)
        self.assertEqual(modifier.alt_skin_gauge_factor, 1.25)

        direct = apply_step_params((StepParam(0, _f32_bits(300.0)),))
        self.assertEqual(direct.speed, 300.0)

    def test_visibility_three_is_hidden_not_vanish_appear(self) -> None:
        modifier = apply_step_params((StepParam(16, 3),))
        self.assertIs(modifier.visibility, VisibilityMode.HIDDEN)

    def test_speed_mode_auto_velocity_enum_value_is_not_applied_by_header_dispatcher(self) -> None:
        base = EffectiveModifier(speed_mode=SpeedMode.EARTHWORM)
        modifier = apply_step_params((StepParam(1, 3),), base)
        self.assertIs(modifier.speed_mode, SpeedMode.EARTHWORM)

    def test_direction_maps_to_common_modifier_rotate_and_upside_down_bits(self) -> None:
        expected = {
            0: (DirectionMode.NORMAL, False, False),
            1: (DirectionMode.ROTATE_180, True, False),
            2: (DirectionMode.UPSIDE_DOWN, False, True),
            3: (DirectionMode.MIRROR, True, True),
        }
        for raw, state in expected.items():
            with self.subTest(raw=raw):
                modifier = apply_step_params((StepParam(32, raw),))
                self.assertEqual(
                    (modifier.direction, modifier.rotate_180, modifier.upside_down),
                    state,
                )

    def test_later_lane_and_judge_ids_map_to_named_game_modifier_fields(self) -> None:
        modifier = apply_step_params(
            (
                StepParam(48, 1),
                StepParam(49, 1),
                StepParam(50, 1),
                StepParam(51, 1),
                StepParam(64, 1),
                StepParam(66, 1),
                StepParam(67, 1),
                StepParam(68, 1),
                StepParam(71, 1),
            )
        )

        self.assertTrue(modifier.mirror_turn)
        self.assertTrue(modifier.mirror_lr)
        self.assertTrue(modifier.random)
        # mpRunner exists in PUMP.Param, but ApplyStepParamToMod has no ID-51 branch.
        self.assertFalse(modifier.runner)
        self.assertTrue(modifier.judge_bank)
        self.assertTrue(modifier.judge_reverse)
        self.assertTrue(modifier.hide_judge)
        self.assertTrue(modifier.judge_by_note)
        self.assertTrue(modifier.free_performance)

    def test_combo_display_writes_both_game_and_common_modifier_state(self) -> None:
        single = apply_step_params((StepParam(69, 0),))
        self.assertIs(single.combo_display, ComboDisplay.SINGLE_BANK)
        self.assertTrue(single.combo_per_bank)
        self.assertFalse(single.merge_combo)

        all_bank = apply_step_params((StepParam(69, 1),))
        self.assertIs(all_bank.combo_display, ComboDisplay.ALL_BANK)
        self.assertFalse(all_bank.combo_per_bank)
        self.assertFalse(all_bank.merge_combo)

        all_player = apply_step_params((StepParam(69, 2),))
        self.assertIs(all_player.combo_display, ComboDisplay.ALL_PLAYER)
        self.assertFalse(all_player.combo_per_bank)
        self.assertTrue(all_player.merge_combo)

    def test_random_skin_fills_unspecified_six_slot_skin_array_with_254(self) -> None:
        modifier = apply_step_params(
            (
                StepParam(19, 6),
                StepParam(900, 12),
                StepParam(903, 33),
            )
        )
        self.assertEqual(modifier.random_skin, 6)
        self.assertEqual(modifier.skins, (12, 254, 254, 33, 254, 254))

        explicit = apply_step_params(
            tuple(StepParam(900 + slot, 20 + slot) for slot in range(6))
        )
        self.assertEqual(explicit.skins, (20, 21, 22, 23, 24, 25))

    def test_force_bga_and_speed_boost_are_lookups_not_effective_writes_here(self) -> None:
        base = EffectiveModifier(disable_bg=True, speed_boost=2.5)
        modifier = apply_step_params(
            (
                StepParam(20, 1234),
                StepParam(1110, _f32_bits(4.0)),
            ),
            base,
        )
        self.assertTrue(modifier.disable_bg)
        self.assertEqual(modifier.speed_boost, 2.5)

    def test_runtime_enum_boolean_gauge_and_level_dispatch_matches_header_ids(self) -> None:
        modifier = apply_step_params(
            (
                StepParam(1001, 27),
                StepParam(1, 2),
                StepParam(2, 1),
                StepParam(17, 1),
                StepParam(18, 1),
                StepParam(19, 0),
                StepParam(21, 1),
                StepParam(22, 0),
                StepParam(33, 2),
                StepParam(34, 1),
                StepParam(35, 1),
                StepParam(80, 1500),
                StepParam(81, 1200),
                StepParam(82, 650),
                StepParam(83, 0),
                StepParam(84, 500),
                StepParam(85, 3),
            )
        )

        self.assertEqual(modifier.level, 27)
        self.assertIs(modifier.speed_mode, SpeedMode.RANDOM_VELOCITY)
        self.assertIs(modifier.acc_dec, AccDecMode.ACCELERATION)
        self.assertTrue(modifier.freedom)
        self.assertTrue(modifier.flash)
        self.assertTrue(modifier.exceed)
        self.assertFalse(modifier.nx)
        self.assertIs(modifier.throw, ThrowMode.RISE)
        self.assertTrue(modifier.snake)
        self.assertTrue(modifier.zigzag)
        self.assertEqual(modifier.gauge_max, 1500)
        self.assertEqual(modifier.gauge_display_max, 1200)
        self.assertEqual(modifier.gauge_initial_value, 650)
        self.assertFalse(modifier.stage_break)
        self.assertEqual(modifier.miss_combo_break, 500)
        self.assertEqual(modifier.gauge_link_factor, 3)

    def test_id65_updates_modifier_frames_but_not_gameplay_windows_yet(self) -> None:
        modifier = apply_step_params((StepParam(65, 75),))
        self.assertEqual(modifier.perfect_frame, 6.7)
        self.assertEqual(modifier.interval_frame, 5.0)

    def test_snapshot_preserves_header_and_split_params_without_fake_split_override(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX")
        document = InsertMetadata.from_ints(document.stable_id, 1, 2).apply(document)
        split = document.splits[0]
        document = InsertMetadata.from_ints(split.stable_id, 1, 1).apply(document)

        snapshot = create_preview_snapshot(document)
        self.assertEqual(snapshot.header_step_params[-1], StepParam(1, 2))
        self.assertEqual(snapshot.splits[0].step_params[-1], StepParam(1, 1))
        self.assertIs(snapshot.effective_modifier().speed_mode, SpeedMode.RANDOM_VELOCITY)

        stream = build_event_stream(snapshot, resolve_route(snapshot, RoutePolicy.MANUAL))
        self.assertIsNotNone(stream.effective_modifier)
        assert stream.effective_modifier is not None
        self.assertIs(stream.effective_modifier.speed_mode, SpeedMode.RANDOM_VELOCITY)


if __name__ == "__main__":
    unittest.main()
