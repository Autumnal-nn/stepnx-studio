from __future__ import annotations

import json
import struct
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from stepnx.authoring import (
    MetadataScope,
    NoteFunction,
    NoteTool,
    NoteVisibility,
    TimelineGeometry,
    TimelineLayout,
    VisualPackError,
    create_authoring_snapshot,
    load_noteskin_pack,
    load_visual_pack,
    note_tool_raw,
)
from stepnx.authoring.benchmark import benchmark_viewport
from stepnx.authoring.noteskin import NoteskinPackError, hold_atlas_plan
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.model import CompactRows
from stepnx.resources import bundled_metronome_path, bundled_noteskin_root
from tests.fixture_factory import make_large_lightmap, make_normal_nx20


class AuthoringSnapshotTests(unittest.TestCase):
    def test_snapshot_preserves_compact_rows_and_contextual_metadata(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX", row_storage="compact")
        snapshot = create_authoring_snapshot(document)

        self.assertIs(snapshot.splits[0].blocks[0].rows, document.splits[0].blocks[0].rows)
        self.assertIsInstance(snapshot.splits[0].blocks[0].rows, CompactRows)
        self.assertEqual([item.scope for item in snapshot.header_metadata], [MetadataScope.HEADER] * 3)
        self.assertEqual([item.scope for item in snapshot.splits[0].metadata], [MetadataScope.SPLIT] * 2)
        self.assertEqual(
            [item.scope for item in snapshot.splits[0].blocks[0].divisions],
            [MetadataScope.DIVISION] * 2,
        )
        self.assertEqual(snapshot.header_metadata[0].raw_value, document.header_metadata[0].value.raw)

    def test_branch_switch_changes_only_snapshot_session_state(self) -> None:
        document = parse_bytes(make_normal_nx20(), source="NM.NX", row_storage="compact")
        split = document.splits[0]
        second = replace(split.blocks[0], stable_id=document.next_stable_id)
        branched = replace(document, splits=(replace(split, blocks=(split.blocks[0], second)),))
        before = serialize(branched)

        snapshot = create_authoring_snapshot(branched)
        changed = snapshot.with_active_block(split.stable_id, second.stable_id)

        self.assertNotEqual(snapshot.active_blocks, changed.active_blocks)
        self.assertEqual(changed.active_block(split.stable_id).stable_id, second.stable_id)
        self.assertEqual(serialize(branched), before)


class TimelineLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = parse_bytes(make_large_lightmap(), source="LM.NX", row_storage="compact")
        cls.snapshot = create_authoring_snapshot(cls.document)

    def test_culling_materializes_only_a_bounded_visible_window(self) -> None:
        layout = TimelineLayout(self.snapshot)
        visible = layout.visible_segments(layout.content_height / 2, 900)
        count = sum(item.row_count for item in visible)
        self.assertGreater(count, 0)
        self.assertLess(count, 100)
        self.assertEqual(self.snapshot.splits[0].blocks[0].row_count, 267_264)

    def test_row_hit_testing_and_zoom_are_consistent(self) -> None:
        layout = TimelineLayout(self.snapshot, TimelineGeometry(row_height=20))
        segment = layout.segments[0]
        hit = layout.row_at_y(segment.rows_top + 10 * segment.row_height + 1)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1], 10)
        zoomed = TimelineLayout(self.snapshot, layout.geometry.zoomed(2))
        zoomed_segment = zoomed.segments[0]
        self.assertEqual(
            zoomed.row_at_y(
                zoomed_segment.rows_top + 10 * zoomed_segment.row_height + 1
            )[1],
            10,
        )

        cell = layout.cell_at(
            layout.geometry.ruler_width + layout.geometry.lane_width * 2 + 1,
            segment.rows_top + 10 * segment.row_height + 1,
        )
        self.assertEqual(cell[1:], (10, 2))
        self.assertIsNone(layout.cell_at(layout.geometry.ruler_width - 1, segment.rows_top + 1))
        self.assertEqual(segment.rows_top, segment.top)

    def test_zoom_supports_sixty_four_times_the_previous_ceiling(self) -> None:
        geometry = TimelineGeometry()

        self.assertEqual(geometry.row_height, geometry.lane_width)
        self.assertEqual(geometry.maximum_row_height, 96 * 64)
        self.assertEqual(geometry.zoomed(10_000).row_height, 96 * 64)
        self.assertEqual(geometry.zoomed(10_000).zoomed(2).row_height, 96 * 64)

    def test_note_artwork_stays_square_when_rows_are_compressed(self) -> None:
        compressed = TimelineGeometry(row_height=4)
        normal = TimelineGeometry(row_height=24)

        compressed_rect = compressed.note_rect(2, 100)
        normal_rect = normal.note_rect(2, 100)

        self.assertEqual(compressed_rect[2:], (44.0, 44.0))
        self.assertEqual(normal_rect[2:], (44.0, 44.0))
        self.assertEqual(compressed_rect[0], normal_rect[0])
        self.assertEqual(normal_rect[1] - compressed_rect[1], 10.0)

    def test_encoded_row_height_is_constant_across_beat_splits(self) -> None:
        source_split = self.snapshot.splits[0]

        def layout_for(beat_split: int) -> TimelineLayout:
            block = replace(source_split.blocks[0], beat_split=beat_split)
            split = replace(source_split, blocks=(block,))
            snapshot = replace(self.snapshot, splits=(split,))
            return TimelineLayout(snapshot, TimelineGeometry(row_height=4))

        split_8 = layout_for(8)
        split_128 = layout_for(128)
        distance_8 = split_8.pixels_for_beats_at_y(split_8.segments[0].rows_top + 1, 1.0)
        distance_128 = split_128.pixels_for_beats_at_y(
            split_128.segments[0].rows_top + 1, 1.0
        )

        self.assertEqual(split_8.segments[0].row_height, 4)
        self.assertEqual(split_128.segments[0].row_height, 4)
        self.assertEqual(distance_8, 32)
        self.assertEqual(distance_128, 512)

    def test_chart_time_projects_to_fractional_row_geometry(self) -> None:
        layout = TimelineLayout(self.snapshot, TimelineGeometry(row_height=20))
        segment = layout.segments[0]
        block = segment.block
        row_duration = 60_000.0 / (block.bpm * block.beat_split)

        y = layout.y_for_chart_time(block.start_time + 2.5 * row_duration)

        self.assertAlmostEqual(y, segment.rows_top + 2.5 * segment.row_height)

    def test_chart_time_clamps_to_nearest_explicit_block_endpoint(self) -> None:
        layout = TimelineLayout(self.snapshot)
        segment = layout.segments[0]
        self.assertEqual(
            layout.y_for_chart_time(segment.block.start_time - 10_000),
            segment.rows_top,
        )

    def test_playback_projection_does_not_change_fixed_authoring_rows(self) -> None:
        source_split = self.snapshot.splits[0]
        block = replace(source_split.blocks[0], scroll=0.25, beat_split=4)
        snapshot = replace(
            self.snapshot,
            splits=(replace(source_split, blocks=(block,)),),
        )

        authoring = TimelineLayout(snapshot, TimelineGeometry(row_height=20))
        playback = TimelineLayout(
            snapshot, TimelineGeometry(row_height=20), playback=True
        )

        self.assertEqual(authoring.segments[0].row_height, 20)
        self.assertEqual(playback.segments[0].row_height, 20)
        self.assertEqual(
            authoring.pixels_for_beats_at_y(authoring.segments[0].rows_top, 1),
            80,
        )
        self.assertEqual(
            playback.pixels_for_beats_at_y(playback.segments[0].rows_top, 1),
            80,
        )

    def test_zero_scroll_does_not_collapse_the_authoring_grid(self) -> None:
        source_split = self.snapshot.splits[0]
        block = replace(source_split.blocks[0], scroll=0.0)
        snapshot = replace(
            self.snapshot,
            splits=(replace(source_split, blocks=(block,)),),
        )

        authoring = TimelineLayout(snapshot, TimelineGeometry(row_height=20))
        playback = TimelineLayout(
            snapshot, TimelineGeometry(row_height=20), playback=True
        )

        self.assertGreater(authoring.segments[0].bottom, authoring.segments[0].top)
        self.assertEqual(playback.segments[0].row_height, 0)
        self.assertEqual(playback.segments[0].bottom, playback.segments[0].top)
        row_duration = 60_000.0 / (block.bpm * block.beat_split)
        middle_time = block.start_time + row_duration * (block.row_count / 2)
        self.assertEqual(
            playback.y_for_chart_time(middle_time),
            playback.segments[0].rows_top,
        )
        self.assertGreater(
            authoring.y_for_chart_time(middle_time),
            authoring.segments[0].rows_top,
        )

    def test_playback_projection_uses_scroll_times_beat_split(self) -> None:
        source_split = self.snapshot.splits[0]
        block = replace(source_split.blocks[0], scroll=0.5, beat_split=4)
        snapshot = replace(
            self.snapshot,
            splits=(replace(source_split, blocks=(block,)),),
        )

        playback = TimelineLayout(
            snapshot, TimelineGeometry(row_height=20), playback=True
        )

        self.assertEqual(playback.segments[0].row_height, 40)

    def test_smooth_speed_block_remains_in_playhead_projection(self) -> None:
        source_split = self.snapshot.splits[0]
        block = replace(source_split.blocks[0], smooth_speed=2)
        snapshot = replace(
            self.snapshot,
            splits=(replace(source_split, blocks=(block,)),),
        )

        self.assertIsNotNone(TimelineLayout(snapshot).y_for_chart_time(block.start_time))

    def test_playhead_uses_latest_started_block_when_smooth_ranges_overlap(
        self,
    ) -> None:
        source_split = self.snapshot.splits[0]
        first = replace(source_split.blocks[0], smooth_speed=2, start_time=0.0)
        second_split_id = source_split.stable_id + 100_000
        second = replace(
            source_split.blocks[0],
            stable_id=source_split.blocks[0].stable_id + 100_000,
            split_id=second_split_id,
            smooth_speed=0,
            start_time=500.0,
        )
        first_split = replace(source_split, blocks=(first,))
        second_split = replace(
            source_split,
            stable_id=second_split_id,
            index=source_split.index + 1,
            blocks=(second,),
        )
        snapshot = replace(
            self.snapshot,
            splits=(first_split, second_split),
            active_blocks=(
                (first_split.stable_id, first.stable_id),
                (second_split.stable_id, second.stable_id),
            ),
        )
        layout = TimelineLayout(snapshot, TimelineGeometry(row_height=20))

        expected = layout.segments[1].rows_top + (
            (750.0 - second.start_time)
            / (60_000.0 / (second.bpm * second.beat_split))
            * layout.segments[1].row_height
        )

        self.assertAlmostEqual(layout.y_for_chart_time(750.0), expected)

    def test_snapping_uses_musical_intervals_and_stays_inside_block(self) -> None:
        layout = TimelineLayout(self.snapshot)
        segment = layout.segments[0]
        self.assertEqual(layout.snap_row_index(segment, 3, 0.5), 3)
        self.assertEqual(layout.snap_row_index(segment, 3, 1.0), 4)
        self.assertEqual(layout.snap_row_index(segment, 1, 1.0), 2)
        self.assertEqual(layout.snap_row_index(segment, 1, 0.0), 1)
        self.assertEqual(layout.rows_per_snap(segment, 0.25), 1)
        self.assertEqual(layout.rows_per_snap(segment, 1.0), 2)

    def test_stress_fixture_exceeds_minimum_culling_budget(self) -> None:
        result = benchmark_viewport(self.snapshot, frames=180, viewport_height=900)
        self.assertGreaterEqual(result.frames_per_second, 30.0)
        self.assertLess(result.maximum_rows_per_frame, 260)


class VisualPackTests(unittest.TestCase):
    def test_local_pack_is_validated_without_copying_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glyph = root / "tap.svg"
            glyph.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
            (root / "stepnx-visual-pack.json").write_text(
                json.dumps({"name": "Local Test", "glyphs": {"tap": "tap.svg"}}),
                encoding="utf-8",
            )
            pack = load_visual_pack(root)
            self.assertEqual(pack.name, "Local Test")
            self.assertEqual(pack.path_for("tap"), glyph.resolve())

    def test_pack_rejects_unknown_and_escaping_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "stepnx-visual-pack.json"
            manifest.write_text(
                json.dumps({"name": "Bad", "glyphs": {"tap": "../tap.svg"}}),
                encoding="utf-8",
            )
            with self.assertRaises(VisualPackError):
                load_visual_pack(root)
            manifest.write_text(
                json.dumps({"name": "Bad", "glyphs": {"official-secret": "tap.svg"}}),
                encoding="utf-8",
            )
            with self.assertRaises(VisualPackError):
                load_visual_pack(root)


def _write_png_header(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
    )


class NoteskinPackTests(unittest.TestCase):
    def test_bundled_authoring_assets_are_installed_and_valid(self) -> None:
        pack = load_noteskin_pack(bundled_noteskin_root())

        self.assertEqual([bank.bank_id for bank in pack.banks], list(range(6)))
        self.assertTrue(all(len(bank.animation) == 1 for bank in pack.banks))
        self.assertIsNotNone(pack.division)
        self.assertEqual(len(pack.item_animation), 1)
        self.assertIsNone(pack.special_items)
        self.assertTrue(bundled_metronome_path().is_file())

    def test_only_hold_body_repeats_the_shaft_strip(self) -> None:
        head = hold_atlas_plan(0x7)
        body = hold_atlas_plan(0xB)
        tail = hold_atlas_plan(0xF)

        self.assertEqual(
            (head.terminal_row, head.shaft_above_terminal, head.shaft_below_terminal, head.repeat_shaft),
            (1, False, True, False),
        )
        self.assertEqual(
            (body.terminal_row, body.shaft_above_terminal, body.shaft_below_terminal, body.repeat_shaft),
            (None, False, False, True),
        )
        self.assertEqual(
            (tail.terminal_row, tail.shaft_above_terminal, tail.shaft_below_terminal, tail.repeat_shaft),
            (0, True, False, False),
        )

        with self.assertRaises(ValueError):
            hold_atlas_plan(0x3)

    def test_private_noteskin_atlases_are_validated_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for frame in range(6):
                _write_png_header(root / "00" / f"{frame}.png", 480, 288)
                _write_png_header(root / "ITEM" / f"{frame}.png", 3072, 192)
            _write_png_header(root / "00" / "6.png", 480, 192)
            _write_png_header(root / "00" / "BASE.png", 480, 192)
            _write_png_header(root / "00" / "HD1.png", 480, 192)
            _write_png_header(root / "00" / "HD2.png", 480, 192)
            for frame in range(5):
                _write_png_header(root / "00" / f"STEPFX08_{frame}.png", 512, 512)
            _write_png_header(root / "DIVISION" / "0.png", 480, 96)
            _write_png_header(root / "ITEM" / "SPECIAL.png", 3072, 288)

            pack = load_noteskin_pack(root)

            self.assertEqual([bank.bank_id for bank in pack.banks], [0])
            self.assertEqual(len(pack.banks[0].animation), 6)
            self.assertTrue(pack.banks[0].has_gameplay_feedback)
            self.assertEqual(pack.banks[0].animation[0].tile(4, 2), (384, 192, 96, 96))
            self.assertEqual(pack.division.path, (root / "DIVISION" / "0.png").resolve())
            self.assertEqual(len(pack.item_animation), 6)

    def test_single_frame_noteskin_and_item_atlases_are_static(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_png_header(root / "00" / "0.png", 480, 288)
            _write_png_header(root / "ITEM" / "0.png", 3072, 192)

            pack = load_noteskin_pack(root)

            self.assertEqual(len(pack.banks[0].animation), 1)
            self.assertEqual(len(pack.item_animation), 1)

    def test_authoring_frames_are_required_but_gameplay_feedback_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for frame in range(6):
                _write_png_header(root / "03" / f"{frame}.png", 480, 288)
            pack = load_noteskin_pack(root)
            self.assertFalse(pack.banks[0].has_gameplay_feedback)

            (root / "03" / "5.png").unlink()
            with self.assertRaisesRegex(NoteskinPackError, "missing 5.png"):
                load_noteskin_pack(root)

    def test_wrong_atlas_dimensions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for frame in range(6):
                _write_png_header(root / "00" / f"{frame}.png", 480, 288)
            _write_png_header(root / "00" / "2.png", 479, 288)
            with self.assertRaisesRegex(NoteskinPackError, "expected 480x288"):
                load_noteskin_pack(root)


class NoteToolTests(unittest.TestCase):
    def test_typed_presets_keep_value_and_orthogonal_bytes_explicit(self) -> None:
        self.assertEqual(note_tool_raw(NoteTool.TAP, 5), b"\x43\x03\x05\x00")
        self.assertEqual(note_tool_raw(NoteTool.HOLD_TAIL, 2), b"\x4f\x03\x02\x00")
        self.assertEqual(note_tool_raw(NoteTool.ITEM, 23), b"\x41\x03\x17\x00")
        self.assertEqual(note_tool_raw(NoteTool.DIVISION, 4), b"\x02\x03\x04\x00")
        self.assertEqual(note_tool_raw(NoteTool.ERASE), b"\x00\x00\x00\x00")

    def test_placement_presets_include_selected_function_and_visibility(self) -> None:
        self.assertEqual(
            note_tool_raw(
                NoteTool.TAP,
                5,
                NoteFunction.GHOST,
                NoteVisibility.APPEAR,
            ),
            b"\x23\x01\x05\x00",
        )


if __name__ == "__main__":
    unittest.main()
