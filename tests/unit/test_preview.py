from __future__ import annotations

import unittest
from dataclasses import replace
from math import isnan

from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import (
    InsertBlock,
    InsertMetadata,
    InsertRow,
    InsertSplit,
    SetNoteAt,
)
from stepnx.core.profiles import pack_u16_range
from stepnx.preview import (
    GameplaySession,
    Judgment,
    PlayfieldGeometry,
    PreviewNoteFunction,
    PreviewNoteVisibility,
    RoutePolicy,
    build_event_stream,
    create_preview_snapshot,
    parse_gameplay_command,
    resolve_route,
)
from tests.fixture_factory import make_implicit_lightmap, make_normal_nx20


def _branched_document():
    document = parse_bytes(make_normal_nx20(), source="NM.NX", row_storage="compact")
    split = document.splits[0]
    block = replace(
        split.blocks[0], smooth_speed=split.blocks[0].smooth_speed.with_value(0)
    )
    document = replace(document, splits=(replace(split, blocks=(block,)),))
    split = document.splits[0]
    document = InsertBlock(split.stable_id, split.blocks[0]).apply(document)
    split = document.splits[0]
    second = split.blocks[1]
    document = InsertMetadata.from_ints(
        second.stable_id, 0, pack_u16_range(1, 10)
    ).apply(document)
    return document


class PreviewSnapshotTests(unittest.TestCase):
    def test_snapshot_retains_every_branch_without_mutating_document(self) -> None:
        document = _branched_document()
        snapshot = create_preview_snapshot(document)

        self.assertEqual(len(snapshot.splits), 1)
        self.assertEqual(len(snapshot.splits[0].blocks), 2)
        self.assertIs(
            snapshot.splits[0].blocks[0].rows, document.splits[0].blocks[0].rows
        )
        self.assertEqual(snapshot.splits[0].blocks[1].conditions[0].metadata_id, 0)

    def test_lightmap_is_diagnosed_as_non_playable(self) -> None:
        snapshot = create_preview_snapshot(parse_bytes(make_implicit_lightmap()))
        self.assertEqual(snapshot.splits[0].blocks[0].conditions, ())
        self.assertTrue(
            any(item.code == "preview.lightmap" for item in snapshot.diagnostics)
        )


class GameplayCommandTests(unittest.TestCase):
    def test_piutester_digits_are_cumulative_quarter_speed_commands(self) -> None:
        command = parse_gameplay_command("v4x88")

        self.assertEqual(command.speed, 5.0)
        self.assertTrue(command.vanish)
        self.assertTrue(command.exceed_mode)
        self.assertEqual(command.unknown, ())

    def test_command_effects_report_only_remaining_unprojected_behavior(self) -> None:
        command = parse_gameplay_command("vadenswfjx")
        self.assertEqual(command.approximate_effects, ("V", "X"))
        self.assertEqual(command.pending_effects, ())
        self.assertEqual(parse_gameplay_command("u").pending_effects, ())

    def test_chart_visibility_composes_with_nonstep_vanish_and_flash(self) -> None:
        plain = parse_gameplay_command("")
        self.assertEqual(
            plain.note_opacity(
                0, screen_y=300, screen_midline=240, time_ms=0
            ),
            0,
        )
        self.assertEqual(
            plain.note_opacity(
                1, screen_y=300, screen_midline=240, time_ms=0
            ),
            0,
        )
        self.assertEqual(
            plain.note_opacity(
                1, screen_y=200, screen_midline=240, time_ms=0
            ),
            1,
        )
        self.assertEqual(
            plain.note_opacity(
                2, screen_y=300, screen_midline=240, time_ms=0
            ),
            1,
        )
        self.assertEqual(
            plain.note_opacity(
                2, screen_y=200, screen_midline=240, time_ms=0
            ),
            0,
        )
        self.assertEqual(
            parse_gameplay_command("n").note_opacity(
                3, screen_y=300, screen_midline=240, time_ms=0
            ),
            0,
        )
        flashing = parse_gameplay_command("w")
        self.assertEqual(
            flashing.note_opacity(
                3, screen_y=300, screen_midline=240, time_ms=50
            ),
            1,
        )
        self.assertEqual(
            flashing.note_opacity(
                3, screen_y=300, screen_midline=240, time_ms=150
            ),
            0,
        )

    def test_launch_speed_overrides_legacy_cumulative_command_digits(self) -> None:
        command = parse_gameplay_command("v4x88").with_speed(7)
        self.assertEqual(command.speed, 7.0)
        with self.assertRaisesRegex(ValueError, "between 1x and 9x"):
            command.with_speed(10)

    def test_empty_command_and_lane_modifiers_are_deterministic(self) -> None:
        self.assertEqual(parse_gameplay_command("").speed, 1.0)
        command = parse_gameplay_command("mur")
        self.assertEqual(command.lane_map(5, seed=91), command.lane_map(5, seed=91))
        self.assertEqual(sorted(command.lane_map(5, seed=91)), list(range(5)))


class PreviewGeometryTests(unittest.TestCase):
    def test_double_uses_one_continuous_ten_lane_playfield(self) -> None:
        geometry = PlayfieldGeometry(960, 10)
        centres = tuple(geometry.lane_center(lane) for lane in range(10))

        self.assertEqual(centres, tuple(range(120, 841, 80)))
        self.assertEqual(centres[5] - centres[4], geometry.lane_spacing)
        self.assertEqual(
            geometry.panel_left(1) - geometry.panel_left(0),
            5 * geometry.lane_spacing,
        )
        self.assertEqual(geometry.panel_width, 5 * geometry.lane_spacing)
        self.assertEqual(
            geometry.panel_left(0) + geometry.panel_width,
            geometry.panel_left(1),
        )
        for panel in range(2):
            for local_lane in range(5):
                self.assertEqual(
                    geometry.panel_left(panel)
                    + (local_lane + 0.5) * geometry.lane_spacing,
                    geometry.lane_center(panel * 5 + local_lane),
                )

    def test_single_centres_one_native_sequence_zone_strip(self) -> None:
        single = PlayfieldGeometry(640, 5)
        double = PlayfieldGeometry(640, 10)

        self.assertAlmostEqual(single.lane_spacing, double.lane_spacing)
        self.assertAlmostEqual(single.lane_center(2), 320.0)
        self.assertAlmostEqual(
            single.panel_left(0) + single.panel_width / 2.0,
            320.0,
        )
        self.assertAlmostEqual(single.panel_width, 5 * double.lane_spacing)


class PreviewNoteSemanticsTests(unittest.TestCase):
    def test_stepedit_function_and_visibility_combinations_are_explicit(self) -> None:
        stream = RuntimeEventTests()._timed_stream()
        source = stream.events[0]
        bonus = replace(source, raw=b"\x63\x03\x00\x00")
        hidden = replace(source, raw=b"\x63\x00\x00\x00")
        ghost = replace(source, raw=b"\x23\x03\x00\x00")

        self.assertIs(bonus.function, PreviewNoteFunction.BONUS)
        self.assertIs(bonus.visibility, PreviewNoteVisibility.VISIBLE)
        self.assertTrue(bonus.registers)
        self.assertIs(hidden.visibility, PreviewNoteVisibility.INVISIBLE)
        self.assertIs(ghost.function, PreviewNoteFunction.GHOST)
        self.assertFalse(ghost.registers)


class RouteResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = create_preview_snapshot(_branched_document())
        self.split = self.snapshot.splits[0]

    def test_manual_policy_requires_and_validates_explicit_choice(self) -> None:
        missing = resolve_route(self.snapshot, RoutePolicy.MANUAL)
        self.assertFalse(missing.is_executable)
        self.assertEqual(missing.diagnostics[0].code, "route.manual-choice-required")

        selected = resolve_route(
            self.snapshot,
            RoutePolicy.MANUAL,
            manual={self.split.stable_id: self.split.blocks[1].stable_id},
        )
        self.assertTrue(selected.is_executable)
        self.assertEqual(selected.decisions[0].reason, "manual choice")

    def test_seeded_policy_is_reproducible_and_does_not_touch_global_rng(self) -> None:
        random_split = replace(
            self.snapshot.splits[0],
            random_at_start=True,
            raw_select=self.snapshot.splits[0].raw_select | 0x80,
        )
        snapshot = replace(self.snapshot, splits=(random_split,))
        first = resolve_route(snapshot, RoutePolicy.SEEDED, seed=812)
        second = resolve_route(snapshot, RoutePolicy.SEEDED, seed=812)
        self.assertEqual(first, second)
        self.assertEqual(first.seed, 812)
        with self.assertRaisesRegex(ValueError, "explicit seed"):
            resolve_route(snapshot, RoutePolicy.SEEDED)

    def test_seeded_policy_randomizes_only_splits_with_random_flags(self) -> None:
        split = replace(
            self.split,
            raw_select=self.split.raw_select & ~0xC0,
            random_at_start=False,
            random_at_trigger=False,
        )
        snapshot = replace(self.snapshot, splits=(split,))
        selected = split.blocks[1].stable_id
        route = resolve_route(
            snapshot,
            RoutePolicy.SEEDED,
            seed=98,
            manual={split.stable_id: selected},
        )
        self.assertTrue(route.is_executable)
        self.assertEqual(route.decisions[0].block_id, selected)
        self.assertEqual(route.decisions[0].reason, "active non-random Block")

    def test_random_flags_share_choices_only_with_the_same_lower_bit_bank(
        self,
    ) -> None:
        def random_split(stable_id: int, raw_select: int):
            return replace(
                self.split,
                stable_id=stable_id,
                raw_select=raw_select,
                random_at_start=bool(raw_select & 0x80),
                random_at_trigger=bool(raw_select & 0x40),
                group=raw_select & 0x1F,
            )

        snapshot = replace(
            self.snapshot,
            splits=(
                random_split(101, 0x81),
                random_split(102, 0x41),
                random_split(103, 0x82),
                random_split(104, 0x42),
            ),
        )
        route = resolve_route(snapshot, RoutePolicy.SEEDED, seed=7)
        selected_indices = [
            snapshot.splits[index].block(decision.block_id).index
            for index, decision in enumerate(route.decisions)
        ]

        self.assertEqual(selected_indices, [1, 1, 0, 0])
        self.assertIn("random bank 1", route.decisions[0].reason)
        self.assertIn("random bank 2", route.decisions[2].reason)

    def test_zero_lower_bits_are_independent_random_events(self) -> None:
        def random_split(stable_id: int, raw_select: int):
            return replace(
                self.split,
                stable_id=stable_id,
                raw_select=raw_select,
                random_at_start=bool(raw_select & 0x80),
                random_at_trigger=bool(raw_select & 0x40),
                group=0,
            )

        snapshot = replace(
            self.snapshot,
            splits=(random_split(201, 0x80), random_split(202, 0x40)),
        )
        route = resolve_route(snapshot, RoutePolicy.SEEDED, seed=4)
        selected_indices = [
            snapshot.splits[index].block(decision.block_id).index
            for index, decision in enumerate(route.decisions)
        ]

        self.assertEqual(selected_indices, [0, 1])
        self.assertEqual(
            [decision.reason for decision in route.decisions],
            ["independent random event", "independent random event"],
        )

    def test_all_perfect_selects_the_only_matching_branch_and_updates_state(
        self,
    ) -> None:
        route = resolve_route(self.snapshot, RoutePolicy.ALL_PERFECT, seed=7)
        self.assertTrue(route.is_executable)
        self.assertEqual(route.decisions[0].block_id, self.split.blocks[0].stable_id)
        self.assertEqual(route.final_metrics.perfect, 1)

    def test_all_perfect_refuses_unproven_cheer_condition(self) -> None:
        document = _branched_document()
        first = document.splits[0].blocks[0]
        document = InsertMetadata.from_ints(
            first.stable_id, 10, pack_u16_range(1, 5)
        ).apply(document)
        route = resolve_route(
            create_preview_snapshot(document), RoutePolicy.ALL_PERFECT
        )
        self.assertFalse(route.is_executable)
        self.assertEqual(route.diagnostics[0].code, "route.unsupported-condition")

    def test_all_perfect_is_explicitly_profile_gated(self) -> None:
        snapshot = replace(self.snapshot, profile="future-engine")
        route = resolve_route(snapshot, RoutePolicy.ALL_PERFECT, seed=1)
        self.assertFalse(route.is_executable)
        self.assertEqual(route.diagnostics[0].code, "route.unsupported-profile")

    def test_all_perfect_random_tie_requires_a_seed(self) -> None:
        document = parse_bytes(
            make_normal_nx20(), source="NM.NX", row_storage="compact"
        )
        split = document.splits[0]
        block = replace(
            split.blocks[0], smooth_speed=split.blocks[0].smooth_speed.with_value(0)
        )
        document = replace(document, splits=(replace(split, blocks=(block,)),))
        document = InsertBlock(split.stable_id, block).apply(document)
        split = document.splits[0]
        document = replace(
            document,
            splits=(replace(split, raw_select=split.raw_select.with_value(0x80)),),
        )
        snapshot = create_preview_snapshot(document)

        missing = resolve_route(snapshot, RoutePolicy.ALL_PERFECT)
        self.assertFalse(missing.is_executable)
        self.assertEqual(missing.diagnostics[0].code, "route.seed-required")
        self.assertEqual(
            resolve_route(snapshot, RoutePolicy.ALL_PERFECT, seed=91),
            resolve_route(snapshot, RoutePolicy.ALL_PERFECT, seed=91),
        )


class RuntimeEventTests(unittest.TestCase):
    @staticmethod
    def _timed_stream():
        document = parse_bytes(
            make_normal_nx20(), source="NM.NX", row_storage="compact"
        )
        split = document.splits[0]
        block = replace(
            split.blocks[0],
            start_time=split.blocks[0].start_time.with_value(250.0),
            bpm=split.blocks[0].bpm.with_value(150.0),
            scroll=split.blocks[0].scroll.with_value(0.25),
            speed_or_freeze=split.blocks[0].speed_or_freeze.with_value(1.0),
            smooth_speed=split.blocks[0].smooth_speed.with_value(0),
        )
        document = replace(document, splits=(replace(split, blocks=(block,)),))
        document = SetNoteAt(block.rows[1].stable_id, 0, b"\x03\x04\x00\x00").apply(
            document
        )
        snapshot = create_preview_snapshot(document)
        return build_event_stream(snapshot, resolve_route(snapshot, RoutePolicy.MANUAL))

    def test_nxa_timing_subset_uses_explicit_anchor_bpm_and_beat_split(self) -> None:
        document = parse_bytes(
            make_normal_nx20(), source="NM.NX", row_storage="compact"
        )
        split = document.splits[0]
        block = replace(
            split.blocks[0],
            start_time=split.blocks[0].start_time.with_value(250.0),
            bpm=split.blocks[0].bpm.with_value(150.0),
            scroll=split.blocks[0].scroll.with_value(1.0),
            smooth_speed=split.blocks[0].smooth_speed.with_value(0),
        )
        document = replace(document, splits=(replace(split, blocks=(block,)),))
        document = SetNoteAt(block.rows[1].stable_id, 0, b"\x03\x04\x00\x00").apply(
            document
        )
        snapshot = create_preview_snapshot(document)
        stream = build_event_stream(
            snapshot, resolve_route(snapshot, RoutePolicy.MANUAL)
        )
        later = next(event for event in stream.events if event.row_index == 1)

        self.assertEqual(later.beat, 0.25)
        self.assertEqual(later.time_ms, 350.0)

    def test_scroll_position_is_interpolated_from_runtime_timing_segments(self) -> None:
        stream = self._timed_stream()
        later = next(event for event in stream.events if event.row_index == 1)

        self.assertEqual(later.position, 0.25)
        self.assertAlmostEqual(stream.position_at(300.0), 0.125)

    def test_manual_and_autoplay_share_one_runtime_judgment_state(self) -> None:
        stream = self._timed_stream()
        event = next(event for event in stream.events if event.row_index == 1)
        manual = GameplaySession(stream, parse_gameplay_command("4"), autoplay=False)

        self.assertEqual(
            manual.press(event.lane, event.time_ms + 20.0), Judgment.PERFECT
        )
        self.assertEqual(manual.stats.perfect, 1)
        self.assertEqual(manual.stats.combo, 1)

        automatic = GameplaySession(stream, parse_gameplay_command("4"), autoplay=True)
        automatic.advance(event.time_ms + 500.0)
        self.assertGreaterEqual(automatic.stats.perfect, 1)
        self.assertEqual(
            automatic.judged_at_ms[automatic.event_key(event)], event.time_ms
        )

    @staticmethod
    def _hold_stream():
        document = parse_bytes(make_normal_nx20(), source="NM.NX")
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
        document = InsertRow(
            block.stable_id,
            block.rows[0],
            before_row_id=block.rows[1].stable_id,
        ).apply(document)
        block = document.splits[0].blocks[0]
        for row in block.rows:
            for lane in range(5):
                document = SetNoteAt(
                    row.stable_id, lane, b"\x00\x00\x00\x00"
                ).apply(document)
        rows = document.splits[0].blocks[0].rows
        for row, raw in zip(
            rows,
            (b"\x57\x03\x00\x00", b"\x5b\x03\x00\x00", b"\x5f\x03\x00\x00"),
        ):
            document = SetNoteAt(row.stable_id, 0, raw).apply(document)
        snapshot = create_preview_snapshot(document)
        return build_event_stream(
            snapshot, resolve_route(snapshot, RoutePolicy.MANUAL)
        )

    def test_hold_head_body_and_tail_each_judge_but_emit_one_stepfx(self) -> None:
        stream = self._hold_stream()
        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=True)

        for event in stream.events:
            session.advance(event.time_ms + 1.0)

        self.assertEqual(session.stats.perfect, 3)
        self.assertEqual(session.stats.combo, 3)
        self.assertEqual(len(session.judgments), 3)
        self.assertEqual(len(session.step_effect_history), 1)

    def test_chord_produces_one_normal_judgment_not_jn_per_cell(self) -> None:
        stream = self._hold_stream()
        head = stream.events[0]
        second = replace(head, lane=1)
        stream = replace(
            stream,
            events=tuple(sorted((head, second), key=lambda event: event.lane)),
        )
        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=True)

        session.advance(head.time_ms + 1.0)

        self.assertEqual(session.stats.perfect, 1)
        self.assertEqual(session.stats.combo, 1)
        self.assertEqual(len(session.judgments), 2)
        self.assertEqual(len(session.step_effect_history), 2)

    def test_manual_hold_judges_body_and_tail_while_lane_is_held(self) -> None:
        stream = self._hold_stream()
        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=False)
        head, body, tail = stream.events

        self.assertIs(session.press(0, head.time_ms), Judgment.PERFECT)
        session.advance(body.time_ms)
        session.advance(tail.time_ms)

        self.assertEqual(session.stats.perfect, 3)
        self.assertEqual(len(session.step_effect_history), 1)

    def test_seek_and_misses_do_not_replay_stepfx(self) -> None:
        stream = self._hold_stream()
        after_chart = stream.events[-1].time_ms + 1000.0
        automatic = GameplaySession(
            stream, parse_gameplay_command(""), autoplay=True
        )
        manual = GameplaySession(stream, parse_gameplay_command(""), autoplay=False)

        automatic.advance(after_chart)
        manual.advance(after_chart)

        self.assertEqual(automatic.stats.perfect, 3)
        self.assertEqual(manual.stats.miss, 3)
        self.assertEqual(automatic.step_effect_history, [])
        self.assertEqual(manual.step_effect_history, [])

    def test_events_follow_resolved_block_and_explicit_start_time(self) -> None:
        snapshot = create_preview_snapshot(_branched_document())
        split = snapshot.splits[0]
        route = resolve_route(
            snapshot,
            RoutePolicy.MANUAL,
            manual={split.stable_id: split.blocks[0].stable_id},
        )
        stream = build_event_stream(snapshot, route)

        self.assertEqual(len(stream.events), 4)
        self.assertEqual(stream.events[0].time_ms, split.blocks[0].start_time_ms)
        self.assertEqual(stream.events[-1].time_ms, split.blocks[0].start_time_ms)
        self.assertEqual(stream.events[-1].beat, 0.0)
        self.assertTrue(isnan(stream.events[0].scroll))
        self.assertEqual(stream.events[0].effective_scroll, 1.0)

    def test_div_flag_values_zero_through_three_keep_smooth_and_skip_independent(self) -> None:
        expected = {
            0: (False, False, 2.0, 125.0),
            1: (True, False, 1.5, 125.0),
            2: (False, True, 2.0, 0.0),
            3: (True, True, 2.0, 0.0),
        }

        for flags, (is_smooth, is_skip, speed, sample_ms) in expected.items():
            with self.subTest(flags=flags):
                document = parse_bytes(make_normal_nx20(), source="NM.NX")
                split = document.splits[0]
                block = replace(
                    split.blocks[0],
                    start_time=split.blocks[0].start_time.with_value(0.0),
                    speed_or_freeze=split.blocks[0].speed_or_freeze.with_value(2.0),
                    smooth_speed=split.blocks[0].smooth_speed.with_value(flags),
                )
                document = replace(
                    document,
                    splits=(replace(split, blocks=(block,)),),
                )
                snapshot = create_preview_snapshot(document)
                stream = build_event_stream(
                    snapshot, resolve_route(snapshot, RoutePolicy.MANUAL)
                )

                self.assertTrue(stream.events)
                div = stream.native_timing.blocks[0]
                self.assertIs(div.is_smooth, is_smooth)
                self.assertIs(div.is_skip, is_skip)
                self.assertAlmostEqual(stream.speed_factor_at(sample_ms), speed)

    def test_smooth_uses_previous_loaded_speed_and_current_div_end(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX")
        first_split = document.splits[0]
        first = replace(
            first_split.blocks[0],
            start_time=first_split.blocks[0].start_time.with_value(0.0),
            speed_or_freeze=first_split.blocks[0].speed_or_freeze.with_value(-3.0),
            smooth_speed=first_split.blocks[0].smooth_speed.with_value(0),
        )
        first_split = replace(
            first_split,
            raw_select=first_split.raw_select.with_value(0),
            blocks=(first,),
        )
        document = replace(document, splits=(first_split,))
        document = InsertSplit(first_split).apply(document)
        document = InsertSplit(document.splits[-1]).apply(document)

        first_split, second_split, third_split = document.splits
        second = replace(
            second_split.blocks[0],
            start_time=second_split.blocks[0].start_time.with_value(250.0),
            speed_or_freeze=second_split.blocks[0].speed_or_freeze.with_value(5.0),
            smooth_speed=second_split.blocks[0].smooth_speed.with_value(1),
        )
        third = replace(
            third_split.blocks[0],
            start_time=third_split.blocks[0].start_time.with_value(1000.0),
            speed_or_freeze=third_split.blocks[0].speed_or_freeze.with_value(1.0),
            smooth_speed=third_split.blocks[0].smooth_speed.with_value(0),
        )
        document = replace(
            document,
            splits=(
                first_split,
                replace(
                    second_split,
                    raw_select=second_split.raw_select.with_value(0),
                    blocks=(second,),
                ),
                replace(
                    third_split,
                    raw_select=third_split.raw_select.with_value(0),
                    blocks=(third,),
                ),
            ),
        )
        snapshot = create_preview_snapshot(document)
        stream = build_event_stream(
            snapshot, resolve_route(snapshot, RoutePolicy.MANUAL)
        )

        self.assertEqual(stream.native_timing.blocks[0].speed, 3.0)
        self.assertEqual(stream.speed_factor_at(250.0), 3.0)
        self.assertAlmostEqual(stream.speed_factor_at(375.0), 4.0)
        self.assertAlmostEqual(stream.speed_factor_at(499.0), 4.992, places=3)

    def test_zero_scroll_is_a_real_stationary_segment(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX")
        split = document.splits[0]
        block = replace(
            split.blocks[0],
            scroll=split.blocks[0].scroll.with_value(0.0),
            smooth_speed=split.blocks[0].smooth_speed.with_value(2),
        )
        document = replace(document, splits=(replace(split, blocks=(block,)),))
        snapshot = create_preview_snapshot(document)
        stream = build_event_stream(
            snapshot, resolve_route(snapshot, RoutePolicy.MANUAL)
        )

        self.assertEqual(stream.timing[0].start_position, stream.timing[0].end_position)

    def test_lightmap_cannot_be_promoted_to_a_runtime_stream(self) -> None:
        snapshot = create_preview_snapshot(parse_bytes(make_implicit_lightmap()))
        route = resolve_route(snapshot, RoutePolicy.MANUAL)
        with self.assertRaisesRegex(ValueError, "non-playable"):
            build_event_stream(snapshot, route)


if __name__ == "__main__":
    unittest.main()
