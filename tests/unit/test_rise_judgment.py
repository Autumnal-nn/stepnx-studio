from __future__ import annotations

import unittest
from dataclasses import replace

from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import InsertMetadata, SetNoteAt
from stepnx.preview import (
    GameplaySession,
    Judgment,
    PreviewEvent,
    RoutePolicy,
    build_event_stream,
    create_preview_snapshot,
    judge_note_decision,
    parse_gameplay_command,
    resolve_route,
    summarize_judge_line,
)
from tests.fixture_factory import make_normal_nx20


def _event(raw: bytes, *, lane: int = 0) -> PreviewEvent:
    return PreviewEvent(100.0, 0.0, 1, 2, 0, lane, raw, 0.25, 0.0, 0)


def _two_note_stream(*, second_bank: int = 0, judge_by_note: bool = False):
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
    block = document.splits[0].blocks[0]
    for row in block.rows:
        if not hasattr(row, "cells"):
            continue
        for lane in range(len(row.cells)):
            document = SetNoteAt(row.stable_id, lane, b"\0\0\0\0").apply(document)
    row = document.splits[0].blocks[0].rows[0]
    document = SetNoteAt(row.stable_id, 0, b"\x43\x03\x00\x00").apply(document)
    bank_param = second_bank << 14
    document = SetNoteAt(
        row.stable_id,
        1,
        bytes((0x43, 0x03, bank_param & 0xFF, bank_param >> 8)),
    ).apply(document)
    if judge_by_note:
        document = InsertMetadata.from_ints(document.stable_id, 68, 1).apply(document)
    snapshot = create_preview_snapshot(document)
    return build_event_stream(snapshot, resolve_route(snapshot, RoutePolicy.MANUAL))


class RiseJudgmentTests(unittest.TestCase):
    def test_preview_event_decodes_native_attribute_effect_bank_and_param(self) -> None:
        bank_param = (2 << 14) | 9
        event = _event(bytes((0x57, 0x13, bank_param & 0xFF, bank_param >> 8)))

        self.assertEqual(event.attribute, 0x57)
        self.assertEqual(event.base_note_type, 3)
        self.assertEqual(event.judge_mask, 0x40)
        self.assertTrue(event.no_rush)
        self.assertEqual(event.long_kind, 0x04)
        self.assertEqual(event.long_flags, 0x14)
        self.assertEqual(event.y_table, 3)
        self.assertEqual(event.param, 9)
        self.assertEqual(event.bank, 2)
        self.assertTrue(event.visible_for_judge)

    def test_judgeline_filters_nojudge_type_and_bank_before_counting(self) -> None:
        valid = _event(b"\x43\x03\x00\x00", lane=0)
        no_judge = _event(b"\x23\x03\x00\x00", lane=1)
        item = _event(b"\x41\x03\x00\x00", lane=2)
        other_bank = _event(b"\x43\x03\x00\x40", lane=3)

        summary = summarize_judge_line((valid, no_judge, item, other_bank), 0)

        self.assertEqual(summary.eligible, (valid,))
        self.assertEqual(summary.note_count, 1)
        self.assertEqual(summary.long_note_count, 0)
        self.assertTrue(summary.visible)
        self.assertFalse(summary.no_miss)
        self.assertTrue(summary.play_sound)

    def test_regular_norush_long_and_rush_long_take_different_paths(self) -> None:
        regular = (
            _event(b"\x57\x03\x00\x00", lane=0),
            _event(b"\x5b\x03\x00\x00", lane=0),
            _event(b"\x5f\x03\x00\x00", lane=0),
        )
        rush = _event(b"\x47\x03\x00\x00", lane=1)

        regular_summary = summarize_judge_line(regular, 0)
        rush_summary = summarize_judge_line((rush,), 0)

        self.assertEqual(regular_summary.long_note_count, 3)
        self.assertEqual(regular_summary.note_count, 0)
        self.assertEqual(regular_summary.rush_notes, ())
        self.assertTrue(regular_summary.play_sound)

        self.assertEqual(rush_summary.long_note_count, 0)
        self.assertEqual(rush_summary.note_count, 0)
        self.assertEqual(rush_summary.rush_notes, (rush,))
        self.assertFalse(rush_summary.has_judge_unit)

    def test_judgeline_alt_skin_counts_notes_while_judgenote_uses_param_div_three(self) -> None:
        event = _event(b"\x43\x03\x09\x00")

        summary = summarize_judge_line((event,), 0)
        decision = judge_note_decision(event, 0, judge_by_note=True)

        self.assertEqual(summary.alt_skin_count, 1)
        self.assertEqual(decision.alt_skin_count, 3)
        self.assertTrue(decision.routed_to_judge_unit)
        self.assertTrue(decision.judge_by_note_checked)
        self.assertEqual(decision.note_count, 1)

    def test_rush_judgenote_ignores_positive_grade_and_turns_negative_into_long_miss(self) -> None:
        rush = _event(b"\x47\x03\x00\x00")

        hit = judge_note_decision(rush, 0, judge_by_note=True)
        miss = judge_note_decision(rush, -1, judge_by_note=False)

        self.assertFalse(hit.routed_to_judge_unit)
        self.assertFalse(hit.forced_miss)
        self.assertTrue(miss.forced_miss)
        self.assertEqual(miss.note_count, 1)
        self.assertEqual(miss.long_note_count, 1)

    def test_same_row_different_banks_resolve_as_two_judgment_units(self) -> None:
        stream = _two_note_stream(second_bank=1)
        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=True)
        session.advance(stream.events[0].time_ms + 1.0)

        self.assertEqual(session.stats.perfect, 2)
        self.assertEqual(session.stats.combo, 2)
        self.assertEqual(len(session.judgments), 2)

    def test_judge_by_note_turns_same_bank_chord_into_per_note_units(self) -> None:
        line_stream = _two_note_stream(second_bank=0, judge_by_note=False)
        line_session = GameplaySession(
            line_stream, parse_gameplay_command(""), autoplay=True
        )
        line_session.advance(line_stream.events[0].time_ms + 1.0)
        self.assertEqual(line_session.stats.perfect, 1)

        note_stream = _two_note_stream(second_bank=0, judge_by_note=True)
        note_session = GameplaySession(
            note_stream, parse_gameplay_command(""), autoplay=True
        )
        note_session.advance(note_stream.events[0].time_ms + 1.0)
        self.assertTrue(note_session.runtime_modifier.judge_by_note)
        self.assertEqual(note_session.stats.perfect, 2)
        self.assertEqual(note_session.stats.combo, 2)


if __name__ == "__main__":
    unittest.main()
