from __future__ import annotations

import struct
import unittest

from stepnx.codecs.nx20 import parse_bytes
from stepnx.exporters.ssc import (
    SscExportError,
    SscSongInfo,
    difficulty_for_name,
    export_chart,
    render_extension,
    render_simfile,
)

from tests.fixture_factory import f32, metadata, u32


EMPTY_ROW = bytes((0x80, 0x00, 0x00, 0x00))


def block(
    rows: list[bytes],
    *,
    start_time: float = 0.0,
    bpm: float = 120.0,
    scroll: float = 1.0,
    offset: float = 0.0,
    speed: float = 1.0,
    beat_split: int = 8,
    beat_measure: int = 4,
    smooth: int = 0,
    divisions: tuple[tuple[int, int], ...] = (),
) -> bytes:
    body = bytearray()
    body += f32(start_time) + f32(bpm) + f32(scroll) + f32(offset) + f32(speed)
    body += bytes((beat_split, beat_measure, smooth, 0))
    body += metadata(*divisions)
    body += u32(len(rows))
    body += b"".join(rows)
    return bytes(body)


def document(
    blocks_per_split: list[list[bytes]],
    *,
    columns: int = 5,
    header: tuple[tuple[int, int], ...] = ((1001, 18),),
    lightmap: int = 0,
) -> bytes:
    data = bytearray(b"NX20")
    data += u32(0) + u32(columns) + u32(lightmap)
    data += metadata(*header)
    data += u32(len(blocks_per_split))
    for blocks in blocks_per_split:
        data += bytes((0, 0)) + struct.pack("<H", 0)
        data += metadata()
        data += u32(len(blocks))
        data += b"".join(blocks)
    return bytes(data)


def note_row(*cells: bytes) -> bytes:
    return b"".join(cells)


def cell(kind: int, layer: int = 3, player: int = 0, special: int = 0) -> bytes:
    return bytes((kind, layer, player, special))


EMPTY_CELL = cell(0, 0, 0, 0)


def single_row(first: bytes, columns: int = 5) -> bytes:
    return note_row(first, *[EMPTY_CELL] * (columns - 1))


def export(raw: bytes, **kwargs):
    kwargs.setdefault("description", "CR.NX")
    return export_chart(parse_bytes(raw), **kwargs)


def first_line(chart) -> str:
    return chart.notes.splitlines()[0]


class NoteProjectionTest(unittest.TestCase):
    def test_common_notes_without_layer_or_bank_stay_plain(self) -> None:
        rows = [
            single_row(cell(0x43)),
            single_row(cell(0x57)),
            single_row(cell(0x5B)),
            single_row(cell(0x5F)),
        ]
        report = export(document([[block(rows)]]))
        lines = report.chart.notes.splitlines()[:4]
        self.assertEqual(lines, ["10000", "20000", "00000", "30000"])

    def test_layered_notes_carry_a_brace_group(self) -> None:
        rows = [
            single_row(cell(0x43, layer=1)),
            single_row(cell(0x63, layer=3)),
            single_row(cell(0x23, layer=3)),
        ]
        report = export(document([[block(rows)]]))
        lines = report.chart.notes.splitlines()[:3]
        self.assertEqual(lines, ["{101}0000", "{104}0000", "{108}0000"])

    def test_hold_bodies_are_written_as_empty_lanes(self) -> None:
        bodies = (0x2B, 0x3B, 0x4B, 0x5B, 0x6B, 0x7B)
        rows = [single_row(cell(0x43))] + [single_row(cell(kind)) for kind in bodies]
        report = export(document([[block(rows)]]))
        self.assertEqual(
            report.chart.notes.splitlines()[:7], ["10000"] + ["00000"] * 6
        )

    def test_noteskin_bank_is_declared_once(self) -> None:
        rows = [
            single_row(cell(0x43, layer=3, player=1)),
            single_row(cell(0x43, layer=3, player=2)),
        ]
        report = export(document([[block(rows)]]))
        self.assertEqual(report.chart.notes.splitlines()[:2], ["{110}0000", "{120}0000"])
        self.assertEqual(report.chart.noteskin_banks, ("perfor1", "perfor2"))
        self.assertIn("#PRELOADNOTESKIN:perfor1,perfor2;", render_extension(report.chart, "G/S"))

    def test_item_notes_use_the_item_alphabet(self) -> None:
        rows = [
            single_row(cell(0x61, layer=3, player=9, special=0xC0)),
            single_row(cell(0x21, layer=3, player=0, special=0xC0)),
            single_row(cell(0x42, layer=0, player=1, special=0xC0)),
        ]
        report = export(document([[block(rows)]]))
        self.assertEqual(
            report.chart.notes.splitlines()[:3],
            ["{h04}0000", "{z08}0000", "{W07}0000"],
        )

    def test_brain_notes_follow_the_split_trigger(self) -> None:
        rows = [
            single_row(cell(0x42, layer=0, player=0, special=0)),
            single_row(cell(0x42, layer=0, player=0, special=198)),
            single_row(cell(0x42, layer=0, player=0, special=199)),
        ]
        divisions = ((26, 2),)
        report = export(document([[block(rows, divisions=divisions)]]))
        self.assertEqual(
            report.chart.notes.splitlines()[:3],
            ["{324}0000", "{-24}0000", "{+24}0000"],
        )

    def test_a_roll_keeps_the_scoring_class_of_its_function_bits(self) -> None:
        rows = [
            single_row(cell(0x47, layer=3)),
            single_row(cell(0x47, layer=0)),
            single_row(cell(0x4F, layer=3)),
            single_row(cell(0x67, layer=3)),
        ]
        report = export(document([[block(rows)]]))
        self.assertEqual(
            report.chart.notes.splitlines()[:4],
            ["{400}0000", "{403}0000", "{300}0000", "{404}0000"],
        )
        self.assertTrue(report.lossless)

    def test_vanish_low_and_appear_low_reach_the_second_threshold_layers(self) -> None:
        rows = [
            single_row(cell(0x43, layer=4)),
            single_row(cell(0x43, layer=5)),
            single_row(cell(0x63, layer=4)),
            single_row(cell(0x63, layer=5)),
            single_row(cell(0x23, layer=4)),
            single_row(cell(0x23, layer=5)),
        ]
        report = export(document([[block(rows)]]))
        self.assertEqual(
            report.chart.notes.splitlines()[:6],
            [
                "{10d}0000",
                "{10s}0000",
                "{10j}0000",
                "{10h}0000",
                "{10w}0000",
                "{10q}0000",
            ],
        )
        self.assertTrue(report.lossless)

    def test_unknown_note_byte_is_reported_and_kept_visible(self) -> None:
        report = export(document([[block([single_row(cell(0x53))])]]))
        self.assertEqual(first_line(report.chart), "M0000")
        self.assertEqual(
            [item.code for item in report.diagnostics], ["ssc.unknown-note"]
        )

    def test_unknown_bank_falls_back_to_the_default_skin(self) -> None:
        report = export(document([[block([single_row(cell(0x43, layer=1, player=31))])]]))
        self.assertEqual(first_line(report.chart), "{101}0000")
        self.assertEqual(
            [item.code for item in report.diagnostics], ["ssc.unknown-noteskin-bank"]
        )


class TimingProjectionTest(unittest.TestCase):
    def test_bpm_is_scaled_onto_the_eighth_beat_grid(self) -> None:
        report = export(
            document([[block([EMPTY_ROW], bpm=110.0, beat_split=16, scroll=1.0)]])
        )
        self.assertEqual(report.chart.bpms, "0=220,")
        self.assertEqual(report.chart.scrolls, "0=0.5,")

    def test_matching_beat_split_leaves_bpm_untouched(self) -> None:
        report = export(document([[block([EMPTY_ROW], bpm=128.0, beat_split=8)]]))
        self.assertEqual(report.chart.bpms, "0=128,")

    def test_a_frozen_div_is_written_as_a_frozen_bpm(self) -> None:
        report = export(document([[block([EMPTY_ROW], bpm=120.0, smooth=2)]]))
        self.assertEqual(report.chart.bpms, "0=9999999,")

    def test_zero_scroll_disables_the_scroll_segment(self) -> None:
        report = export(document([[block([EMPTY_ROW], scroll=0.0)]]))
        self.assertEqual(report.chart.scrolls, "0=0,")

    def test_speed_segments_are_written_once_per_change(self) -> None:
        blocks = [
            block([EMPTY_ROW], speed=1.0),
            block([EMPTY_ROW], speed=1.0),
            block([EMPTY_ROW], speed=2.0),
        ]
        report = export(document([[item] for item in blocks]))
        self.assertEqual(report.chart.speeds, "0=1=1=1,0.25=2=1=1,")

    def test_positions_advance_by_an_eighth_beat_per_row(self) -> None:
        blocks = [
            block([EMPTY_ROW] * 8, bpm=100.0),
            block([EMPTY_ROW] * 8, bpm=200.0),
        ]
        report = export(document([[item] for item in blocks]))
        self.assertEqual(report.chart.bpms, "0=100,1=200,")

    def test_offset_comes_from_the_first_div_start_time(self) -> None:
        report = export(document([[block([EMPTY_ROW], start_time=1123.0)]]))
        self.assertEqual(report.chart.offset, -1.123)

    def test_a_later_split_delay_becomes_a_stop(self) -> None:
        blocks = [
            block([EMPTY_ROW] * 8),
            block([EMPTY_ROW] * 8, offset=250.0, speed=1.0),
        ]
        report = export(document([[item] for item in blocks]))
        self.assertEqual(report.chart.stops, "1=0.25,")
        self.assertEqual(report.chart.delays, "")

    def test_a_negative_offset_becomes_a_warp(self) -> None:
        blocks = [
            block([EMPTY_ROW] * 8, bpm=120.0),
            block([EMPTY_ROW] * 8, bpm=120.0, offset=-500.0),
        ]
        report = export(document([[item] for item in blocks]))
        self.assertEqual(report.chart.warps, "1=1,")


class MeasureLayoutTest(unittest.TestCase):
    def test_short_charts_are_padded_to_a_whole_measure(self) -> None:
        report = export(document([[block([single_row(cell(0x43))])]]))
        lines = report.chart.notes.splitlines()
        self.assertEqual(lines[0], "10000")
        self.assertEqual(len(lines), 32)
        self.assertEqual(lines[-1], "00000")
        self.assertNotIn(",", report.chart.notes)

    def test_an_aligned_chart_still_ends_on_a_blank_measure(self) -> None:
        rows = [single_row(cell(0x43))] + [EMPTY_ROW] * 31
        report = export(document([[block(rows)]]))
        measures = report.chart.notes.split(",\n")
        self.assertEqual(len(measures), 2)
        self.assertEqual(measures[1], "00000\n")

    def test_blank_measures_collapse_to_one_line(self) -> None:
        rows = [EMPTY_ROW] * 64 + [single_row(cell(0x43))]
        report = export(document([[block(rows)]]))
        measures = report.chart.notes.split(",\n")
        self.assertEqual(measures[0], "00000\n")
        self.assertEqual(measures[1], "00000\n")
        self.assertTrue(measures[2].startswith("10000\n"))


class DocumentGateTest(unittest.TestCase):
    def test_a_lightmap_document_is_refused(self) -> None:
        with self.assertRaises(SscExportError):
            export(document([[block([EMPTY_ROW])]], columns=3, lightmap=1))

    def test_an_unsupported_column_count_is_refused(self) -> None:
        with self.assertRaises(SscExportError):
            export(document([[block([EMPTY_ROW])]], columns=7))

    def test_column_count_selects_the_steps_type(self) -> None:
        for columns, steps_type in ((5, "pump-single"), (6, "pump-halfdouble"), (10, "pump-double")):
            with self.subTest(columns=columns):
                report = export(document([[block([EMPTY_ROW])]], columns=columns))
                self.assertEqual(report.chart.steps_type, steps_type)

    def test_meter_comes_from_header_metadata_1001(self) -> None:
        report = export(document([[block([EMPTY_ROW])]], header=((1001, 23),)))
        self.assertEqual(report.chart.meter, 23)

    def test_alternate_branches_are_reported_as_dropped(self) -> None:
        blocks = [block([EMPTY_ROW]), block([EMPTY_ROW])]
        report = export(document([blocks]))
        self.assertEqual(
            [item.code for item in report.diagnostics],
            ["ssc.alternate-branches-dropped"],
        )

    def test_a_single_branch_chart_reports_nothing(self) -> None:
        report = export(document([[block([EMPTY_ROW])]]))
        self.assertTrue(report.lossless)


class DifficultyTest(unittest.TestCase):
    def test_known_filenames_map_to_slots(self) -> None:
        self.assertEqual(difficulty_for_name("CR.NX"), "Challenge")
        self.assertEqual(difficulty_for_name("no.nx"), "Easy")
        self.assertEqual(difficulty_for_name("HD.nx"), "Hard")
        self.assertEqual(difficulty_for_name("PR.NX"), "Beginner")

    def test_other_filenames_fall_back_to_edit(self) -> None:
        self.assertEqual(difficulty_for_name("ac_1542_Single_21.nx"), "Edit")


class RenderTest(unittest.TestCase):
    def test_extension_matches_the_engine_layout(self) -> None:
        report = export(document([[block([single_row(cell(0x43))], bpm=110.0)]]))
        text = render_extension(report.chart, "TEST/Song")
        self.assertEqual(
            text.splitlines()[:10],
            [
                "#VERSION:0.83 xSanity Extension;",
                "#SONG:TEST/Song;",
                "",
                "//----------- (NX) CR.NX ---------",
                "#NOTEDATA:;",
                "#STEPSTYPE:pump-single;",
                "#DESCRIPTION:CR.NX;",
                "#DIFFICULTY:Challenge;",
                "#METER:18;",
                "#OFFSET:-0;",
            ],
        )
        self.assertIn("#BPMS:0=110,\n;", text)
        self.assertTrue(text.endswith(";\n"))

    def test_the_extension_header_keeps_the_three_parts_the_loader_requires(self) -> None:
        report = export(document([[block([EMPTY_ROW])]]))
        header = render_extension(report.chart, "TEST/Song").splitlines()[0]
        self.assertTrue(header.startswith("#VERSION:") and header.endswith(";"))
        parts = header[len("#VERSION:") : -1].split(" ")
        self.assertEqual(parts, ["0.83", "xSanity", "Extension"])

    def test_the_simfile_header_names_the_writing_tool(self) -> None:
        report = export(document([[block([EMPTY_ROW])]]))
        header = render_simfile([report.chart], SscSongInfo()).splitlines()[0]
        self.assertEqual(header, "#VERSION:0.83 xSanity;")

    def test_the_version_number_clears_the_split_timing_gate(self) -> None:
        report = export(document([[block([EMPTY_ROW])]]))
        for text in (
            render_extension(report.chart, "TEST/Song"),
            render_simfile([report.chart], SscSongInfo()),
        ):
            version = float(text.splitlines()[0][len("#VERSION:") : -1].split(" ")[0])
            self.assertGreaterEqual(version, 0.7)
            self.assertNotEqual(version, 0.81)

    def test_simfile_holds_every_chart(self) -> None:
        first = export(document([[block([EMPTY_ROW])]]), description="NO.NX").chart
        second = export(document([[block([EMPTY_ROW])]]), description="CR.NX").chart
        text = render_simfile([first, second], SscSongInfo(title="Song", artist="A"))
        self.assertIn("#TITLE:Song;", text)
        self.assertIn("#ARTIST:A;", text)
        self.assertEqual(text.count("#NOTEDATA:;"), 2)
        self.assertIn("#DESCRIPTION:NO.NX;", text)
        self.assertIn("#DESCRIPTION:CR.NX;", text)

    def test_an_empty_simfile_is_refused(self) -> None:
        with self.assertRaises(SscExportError):
            render_simfile([], SscSongInfo())


if __name__ == "__main__":
    unittest.main()
