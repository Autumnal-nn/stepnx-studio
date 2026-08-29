from __future__ import annotations

import struct
import unittest

from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import InsertMetadata
from stepnx.preview import (
    AccDecMode,
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
    def test_clear_defaults_match_rise_game_modifier(self) -> None:
        modifier = EffectiveModifier()
        self.assertEqual(modifier.speed, 2.0)
        self.assertIs(modifier.speed_mode, SpeedMode.STATIC)
        self.assertIs(modifier.acc_dec, AccDecMode.LINEAR)
        self.assertIs(modifier.visibility, VisibilityMode.VISIBLE)
        self.assertEqual(modifier.perfect_frame, 2.5)
        self.assertEqual(modifier.interval_frame, 2.5)

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

        # Header 0: 12.0 / 4 = 3.0, then Header 1111 multiplies by 1.5.
        self.assertEqual(modifier.speed, 4.5)
        self.assertEqual(modifier.parameter_70_a, 1.25)
        self.assertEqual(modifier.parameter_70_b, 1.25)

        direct = apply_step_params((StepParam(0, _f32_bits(300.0)),))
        self.assertEqual(direct.speed, 300.0)

    def test_runtime_enum_boolean_and_bitmask_dispatch_matches_header_ids(self) -> None:
        modifier = apply_step_params(
            (
                StepParam(1, 2),
                StepParam(2, 1),
                StepParam(16, 3),
                StepParam(19, 6),
                StepParam(21, 1),
                StepParam(22, 0),
                StepParam(32, 3),
                StepParam(33, 2),
                StepParam(34, 1),
                StepParam(35, 1),
                StepParam(48, 1),
                StepParam(49, 1),
                StepParam(50, 1),
                StepParam(67, 1),
                StepParam(68, 1),
                StepParam(71, 1),
                StepParam(83, 0),
                StepParam(84, 500),
            )
        )

        self.assertIs(modifier.speed_mode, SpeedMode.RANDOM_VELOCITY)
        self.assertIs(modifier.acc_dec, AccDecMode.ACCELERATION)
        self.assertIs(modifier.visibility, VisibilityMode.VANISH_APPEAR)
        self.assertEqual(modifier.random_skin, 6)
        self.assertTrue(modifier.exceed_mode)
        self.assertFalse(modifier.nx_mode)
        self.assertTrue(modifier.under_attack)
        self.assertTrue(modifier.drop)
        self.assertIs(modifier.throw, ThrowMode.RISE)
        self.assertTrue(modifier.snake)
        self.assertTrue(modifier.zigzag)
        self.assertTrue(modifier.mirror)
        self.assertTrue(modifier.alternate_random)
        self.assertTrue(modifier.runner)
        self.assertTrue(modifier.judge_hide)
        self.assertTrue(modifier.judge_by_note)
        self.assertTrue(modifier.flag_71)
        self.assertFalse(modifier.stage_break)
        self.assertEqual(modifier.forced_stage_break_miss_combo, 500)

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

        stream = build_event_stream(
            snapshot, resolve_route(snapshot, RoutePolicy.MANUAL)
        )
        self.assertIsNotNone(stream.effective_modifier)
        assert stream.effective_modifier is not None
        self.assertIs(stream.effective_modifier.speed_mode, SpeedMode.RANDOM_VELOCITY)


if __name__ == "__main__":
    unittest.main()
