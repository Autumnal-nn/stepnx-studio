from __future__ import annotations

import struct
import unittest
from dataclasses import replace

from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import InsertMetadata, SetNoteAt
from stepnx.preview import (
    EffectiveModifier,
    GameplaySession,
    HPBarType,
    JUDGE_FRAME_MS,
    Judgment,
    NativeJudgeTiming,
    RoutePolicy,
    RuntimeGauge,
    add_score_floor_zero,
    build_event_stream,
    create_preview_snapshot,
    native_base_score,
    native_score_delta,
    parse_gameplay_command,
    resolve_route,
)
from tests.fixture_factory import make_normal_nx20


def _f32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _tap_stream(*, raw: bytes = b"\x43\x03\x00\x00", metadata=()):
    document = parse_bytes(make_normal_nx20(), source="NM.NX", row_storage="compact")
    split = document.splits[0]
    block = replace(
        split.blocks[0],
        start_time=split.blocks[0].start_time.with_value(100.0),
        bpm=split.blocks[0].bpm.with_value(120.0),
        scroll=split.blocks[0].scroll.with_value(0.25),
        speed_or_freeze=split.blocks[0].speed_or_freeze.with_value(1.0),
        smooth_speed=split.blocks[0].smooth_speed.with_value(0),
    )
    document = replace(document, splits=(replace(split, blocks=(block,)),))
    block = document.splits[0].blocks[0]
    for row in block.rows:
        for lane in range(len(row.cells)):
            document = SetNoteAt(row.stable_id, lane, b"\0\0\0\0").apply(document)
    row = document.splits[0].blocks[0].rows[0]
    document = SetNoteAt(row.stable_id, 0, raw).apply(document)
    for metadata_id, value in metadata:
        document = InsertMetadata.from_ints(document.stable_id, metadata_id, value).apply(
            document
        )
    snapshot = create_preview_snapshot(document)
    return build_event_stream(snapshot, resolve_route(snapshot, RoutePolicy.MANUAL))


class RiseJudgeTimingTests(unittest.TestCase):
    def test_default_timing_uses_native_frame_and_late_delay(self) -> None:
        timing = NativeJudgeTiming.from_modifier(EffectiveModifier())
        p = 2.5 * JUDGE_FRAME_MS

        self.assertAlmostEqual(timing.perfect_ms, p)
        self.assertAlmostEqual(timing.interval_ms, p)
        self.assertAlmostEqual(timing.delay_ms, p)
        self.assertAlmostEqual(timing.end_ms, 4.0 * p)
        self.assertAlmostEqual(timing.late_limit_ms, 5.0 * p)

        self.assertEqual(timing.grade_for_error(-p), 0)
        self.assertEqual(timing.grade_for_error(-(p + 0.01)), 1)
        self.assertEqual(timing.grade_for_error(p + p), 0)
        self.assertEqual(timing.grade_for_error(p + p + 0.01), 1)
        self.assertIsNone(timing.grade_for_error(-(timing.early_limit_ms + 0.01)))
        self.assertIsNone(timing.grade_for_error(timing.late_limit_ms + 0.01))

    def test_header_65_changes_perfect_and_interval_frames(self) -> None:
        stream = _tap_stream(metadata=((65, 701),))
        timing = NativeJudgeTiming.from_modifier(stream.effective_modifier)

        self.assertAlmostEqual(stream.effective_modifier.perfect_frame, 0.4)
        self.assertAlmostEqual(stream.effective_modifier.interval_frame, 2.0)
        self.assertAlmostEqual(timing.perfect_ms, 0.4 * JUDGE_FRAME_MS)
        self.assertAlmostEqual(timing.interval_ms, 2.0 * JUDGE_FRAME_MS)

    def test_speedboost_scales_whole_judge_frame_only_when_prepopulated(self) -> None:
        normal = NativeJudgeTiming.from_modifier(EffectiveModifier())
        boosted = NativeJudgeTiming.from_modifier(EffectiveModifier(speed_boost=1.5))
        self.assertAlmostEqual(boosted.perfect_ms, normal.perfect_ms * 1.5)
        self.assertAlmostEqual(boosted.interval_ms, normal.interval_ms * 1.5)
        self.assertAlmostEqual(boosted.delay_ms, normal.delay_ms * 1.5)

    def test_manual_session_uses_asymmetric_late_window(self) -> None:
        stream = _tap_stream()
        event = stream.events[0]
        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=False)
        p = session.windows.perfect_ms
        delay = session.windows.delay_ms

        self.assertIs(session.press(0, event.time_ms + delay + p), Judgment.PERFECT)


class RiseScoreTests(unittest.TestCase):
    def test_getscore_table_combo_bonus_and_chord_multipliers(self) -> None:
        expected = (1000, 1000, 500, 100, -200)
        for grade, value in enumerate(expected):
            with self.subTest(grade=grade):
                self.assertEqual(
                    native_base_score(grade, combo=0, note_count=1), value
                )

        self.assertEqual(native_base_score(0, combo=50, note_count=1), 1000)
        self.assertEqual(native_base_score(0, combo=51, note_count=1), 2000)
        self.assertEqual(native_base_score(1, combo=51, note_count=3), 3000)
        self.assertEqual(native_base_score(0, combo=1, note_count=4), 2000)
        self.assertEqual(
            native_base_score(4, combo=0, note_count=1, ordinary_note_miss=True),
            -300,
        )

    def test_postprocess_applies_alt_skin_factor_then_score_floor(self) -> None:
        self.assertEqual(
            native_score_delta(
                0,
                combo=1,
                note_count=1,
                ordinary_note_miss=False,
                alt_skin_factor=1.5,
            ),
            1500,
        )
        self.assertEqual(add_score_floor_zero(100, -300), 0)

    def test_session_first_perfect_uses_native_score(self) -> None:
        stream = _tap_stream()
        event = stream.events[0]
        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=False)

        self.assertIs(session.press(0, event.time_ms), Judgment.PERFECT)
        self.assertEqual(session.stats.score, 1000)
        self.assertEqual(session.stats.combo, 1)


class RiseGaugeTests(unittest.TestCase):
    def test_reset_hp_presets_and_level_limit(self) -> None:
        single = RuntimeGauge.from_modifier(EffectiveModifier(level=20), columns=5)
        half = RuntimeGauge.from_modifier(EffectiveModifier(level=20), columns=6)
        double = RuntimeGauge.from_modifier(EffectiveModifier(level=20), columns=10)

        self.assertIs(single.bar_type, HPBarType.SINGLE)
        self.assertIs(half.bar_type, HPBarType.HALF_DOUBLE)
        self.assertIs(double.bar_type, HPBarType.DOUBLE)
        self.assertEqual(single.limit, 2200)
        self.assertEqual((single.factor_min, single.factor_max, single.factor), (200, 1000, 500))
        self.assertEqual((half.factor_min, half.factor_max, half.factor), (0, 800, 100))
        self.assertEqual((double.factor_min, double.factor_max, double.factor), (100, 900, 300))

    def test_header_80_81_82_override_limit_display_and_life(self) -> None:
        modifier = EffectiveModifier(
            level=20,
            gauge_max=777,
            gauge_display_max=555,
            gauge_initial_value=600,
        )
        gauge = RuntimeGauge.from_modifier(modifier, columns=5)
        self.assertEqual((gauge.limit, gauge.display_max, gauge.life), (777, 555, 600))

    def test_judgeunit_dynamic_factor_and_miss_delta(self) -> None:
        gauge = RuntimeGauge.from_modifier(EffectiveModifier(), columns=5)
        self.assertEqual(gauge.apply_grade(0), 6)
        self.assertEqual((gauge.life, gauge.factor), (506, 520))
        self.assertEqual(gauge.apply_grade(1), 5)
        self.assertEqual((gauge.life, gauge.factor), (511, 536))
        self.assertEqual(gauge.apply_grade(3), -50)
        self.assertEqual(gauge.life, 461)
        self.assertEqual(gauge.apply_grade(4), -135)
        self.assertEqual((gauge.life, gauge.factor), (326, 200))

    def test_session_applies_gauge_header_overrides_and_native_perfect_delta(self) -> None:
        stream = _tap_stream(metadata=((80, 2000), (81, 900), (82, 700)))
        event = stream.events[0]
        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=False)

        self.assertEqual(session.stats.gauge, 700)
        self.assertEqual(session.gauge_limit, 2000)
        self.assertEqual(session.gauge_display_max, 900)
        session.press(0, event.time_ms)
        self.assertEqual(session.stats.gauge, 706)

    def test_no_miss_expiration_skips_postprocess_and_gauge(self) -> None:
        # 0x63 carries bNoMiss while remaining a judgeable Type=Normal note.
        stream = _tap_stream(raw=b"\x63\x03\x00\x00")
        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=False)
        after = stream.events[0].time_ms + session.windows.late_limit_ms + 1.0

        session.advance(after)
        self.assertEqual(session.stats.miss, 0)
        self.assertEqual(session.stats.score, 0)
        self.assertEqual(session.stats.gauge, 500)


if __name__ == "__main__":
    unittest.main()
