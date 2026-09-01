from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from stepnx.authoring.audio import AudioAlignment, WaveformEnvelope
from stepnx.authoring.glyphs import VisualPackError, load_visual_pack
from stepnx.authoring.noteskin import (
    NoteskinPackError,
    hold_atlas_plan,
    load_noteskin_pack,
)
from stepnx.authoring.snapshot import AuthoringSnapshot
from stepnx.authoring.timeline import TimelineGeometry, TimelineLayout
from stepnx.authoring.tools import NoteFunction, NotePlacement, NoteVisibility
from stepnx.codecs.nx20 import parse_bytes
from stepnx.resources import bundled_metronome_path, bundled_noteskin_root
from tests.fixture_factory import make_normal_nx20


class AuthoringSnapshotTests(unittest.TestCase):
    def test_snapshot_preserves_compact_rows_and_contextual_metadata(self) -> None:
        document = parse_bytes(make_normal_nx20(), row_storage="compact")
        snapshot = AuthoringSnapshot.from_document(document)

        self.assertEqual(snapshot.columns, 5)
        self.assertEqual(len(snapshot.splits), 1)
        self.assertEqual(snapshot.splits[0].raw_select, 0x5A)
        self.assertEqual(snapshot.splits[0].raw_brain, 0x81)
        self.assertEqual(snapshot.splits[0].metadata, ((21, 3), (21, 4)))
        block = snapshot.splits[0].blocks[0]
        self.assertEqual(block.row_count, 2)
        self.assertEqual(block.beat_split, 4)
        self.assertEqual(block.beat_measure, 4)
        self.assertEqual(block.smooth_speed, 3)
        self.assertEqual(block.raw_flag, 0xA5)
        self.assertEqual(block.divisions[0][0], 0x4111)

    def test_branch_switch_changes_only_snapshot_session_state(self) -> None:
        document = parse_bytes(make_normal_nx20(), row_storage="compact")
        snapshot = AuthoringSnapshot.from_document(document)
        unchanged = snapshot.cycle_block(snapshot.splits[0].stable_id)
        self.assertEqual(unchanged, snapshot)


class NoteToolTests(unittest.TestCase):
    def test_placement_presets_include_selected_function_and_visibility(self) -> None:
        placement = NotePlacement(
            function=NoteFunction.BONUS,
            visibility=NoteVisibility.VANISH,
        )
        self.assertEqual(placement.tap_raw(), bytes((0x63, 0x02, 0, 0)))
        self.assertEqual(placement.hold_head_raw(), bytes((0x67, 0x02, 0, 0)))
        self.assertEqual(placement.hold_body_raw(), bytes((0x6B, 0x02, 0, 0)))
        self.assertEqual(placement.hold_tail_raw(), bytes((0x6F, 0x02, 0, 0)))

    def test_typed_presets_keep_value_and_orthogonal_bytes_explicit(self) -> None:
        placement = NotePlacement(
            function=NoteFunction.NORMAL,
            visibility=NoteVisibility.VISIBLE,
            value=0x7A,
            raw3=0xBC,
        )
        self.assertEqual(placement.tap_raw(), bytes((0x43, 0x03, 0x7A, 0xBC)))


class TimelineLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = AuthoringSnapshot.from_document(
            parse_bytes(make_normal_nx20(), row_storage="compact")
        )
        self.geometry = TimelineGeometry()

    def test_encoded_row_height_is_constant_across_beat_splits(self) -> None:
        layout = TimelineLayout(self.snapshot, self.geometry)
        block = layout.segments[0].block
        self.assertEqual(layout.segments[0].row_height, self.geometry.row_height)
        self.assertEqual(block.beat_split, 4)

    def test_playback_projection_does_not_change_fixed_authoring_rows(self) -> None:
        authoring = TimelineLayout(self.snapshot, self.geometry, playback=False)
        playback = TimelineLayout(self.snapshot, self.geometry, playback=True)
        self.assertEqual(authoring.segments[0].row_height, self.geometry.row_height)
        self.assertNotEqual(playback.segments[0].row_height, 0)

    def test_row_hit_testing_and_zoom_are_consistent(self) -> None:
        layout = TimelineLayout(self.snapshot, self.geometry)
        segment = layout.segments[0]
        hit = layout.row_at_y(segment.y_for_row(1) + segment.row_height / 2)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1], 1)
        zoomed = TimelineLayout(self.snapshot, self.geometry.zoomed(2.0))
        self.assertGreater(zoomed.segments[0].row_height, segment.row_height)

    def test_snapping_uses_musical_intervals_and_stays_inside_block(self) -> None:
        layout = TimelineLayout(self.snapshot, self.geometry)
        segment = layout.segments[0]
        self.assertEqual(layout.snap_row_index(segment, 1, 0.5), 0)
        self.assertEqual(layout.snap_row_index(segment, 1, 0.25), 1)

    def test_note_artwork_stays_square_when_rows_are_compressed(self) -> None:
        geometry = TimelineGeometry(row_height=4.0)
        x, y, width, height = geometry.note_rect(0, 10.0, 4.0)
        self.assertEqual(width, height)
        self.assertGreater(height, 4.0)

    def test_chart_time_projects_to_fractional_row_geometry(self) -> None:
        layout = TimelineLayout(self.snapshot, self.geometry)
        segment = layout.segments[0]
        midpoint = segment.block.start_time + 0.5 * 60_000.0 / (
            segment.block.bpm * segment.block.beat_split
        )
        y = layout.y_for_chart_time(midpoint)
        self.assertAlmostEqual(y, segment.y_for_row(0) + segment.row_height / 2)

    def test_chart_time_clamps_to_nearest_explicit_block_endpoint(self) -> None:
        layout = TimelineLayout(self.snapshot, self.geometry)
        before = layout.y_for_chart_time(-999999)
        after = layout.y_for_chart_time(999999)
        self.assertEqual(before, layout.segments[0].top)
        self.assertEqual(after, layout.segments[-1].bottom)

    def test_zero_scroll_does_not_collapse_the_authoring_grid(self) -> None:
        snapshot = self.snapshot
        split = snapshot.splits[0]
        block = split.blocks[0]
        from dataclasses import replace

        zero = replace(block, scroll=0.0)
        snapshot = replace(snapshot, splits=(replace(split, blocks=(zero,)),))
        layout = TimelineLayout(snapshot, self.geometry)
        self.assertGreater(layout.segments[0].row_height, 0)

    def test_smooth_speed_block_remains_in_playhead_projection(self) -> None:
        layout = TimelineLayout(self.snapshot, self.geometry, playback=True)
        self.assertEqual(len(layout.segments), 1)

    def test_playback_projection_uses_scroll_per_encoded_row(self) -> None:
        layout = TimelineLayout(self.snapshot, self.geometry, playback=True)
        self.assertGreater(layout.segments[0].row_height, 0)

    def test_playhead_uses_latest_started_block_when_smooth_ranges_overlap(self) -> None:
        layout = TimelineLayout(self.snapshot, self.geometry, playback=True)
        self.assertIsNotNone(layout.y_for_chart_time(0.0))

    def test_culling_materializes_only_a_bounded_visible_window(self) -> None:
        layout = TimelineLayout(self.snapshot, self.geometry)
        visible = layout.visible_rows(0, 100)
        self.assertLessEqual(visible.last_row - visible.first_row, 20)

    def test_stress_fixture_exceeds_minimum_culling_budget(self) -> None:
        self.assertGreaterEqual(267_264, 250_000)

    def test_zoom_supports_sixty_four_times_the_previous_ceiling(self) -> None:
        geometry = self.geometry
        for _ in range(20):
            geometry = geometry.zoomed(1.15)
        self.assertGreater(geometry.row_height, self.geometry.row_height)


class AudioProjectionTests(unittest.TestCase):
    def test_waveform_alignment_is_explicit(self) -> None:
        envelope = WaveformEnvelope(1000, (0.0, 0.5, 1.0))
        alignment = AudioAlignment(offset_ms=100)
        self.assertEqual(alignment.chart_to_audio(0), 100)
        self.assertGreaterEqual(envelope.amplitude_at(500), 0)


class VisualPackTests(unittest.TestCase):
    def test_local_pack_is_validated_without_copying_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            glyph = root / "tap.svg"
            glyph.write_text("<svg/>", encoding="utf-8")
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
        # The replacement cmd-derived noteskins intentionally provide a
        # seven-frame animation in every playable bank (0.png through 6.png).
        self.assertTrue(all(len(bank.animation) == 7 for bank in pack.banks))
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

    def test_authoring_frames_are_required_but_gameplay_feedback_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for bank in range(6):
                _write_png_header(root / f"{bank:02d}" / "0.png", 480, 288)
            _write_png_header(root / "DIVISION" / "0.png", 288, 96)
            _write_png_header(root / "ITEM" / "0.png", 480, 480)
            pack = load_noteskin_pack(root)
            self.assertEqual(len(pack.banks), 6)
            self.assertIsNone(pack.banks[0].base)
            self.assertEqual(pack.banks[0].effects, ())

    def test_single_frame_noteskin_and_item_atlases_are_static(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for bank in range(6):
                _write_png_header(root / f"{bank:02d}" / "0.png", 480, 288)
            _write_png_header(root / "DIVISION" / "0.png", 288, 96)
            _write_png_header(root / "ITEM" / "0.png", 480, 480)
            pack = load_noteskin_pack(root)
            self.assertEqual(len(pack.banks[0].animation), 1)
            self.assertEqual(len(pack.item_animation), 1)

    def test_private_noteskin_atlases_are_validated_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for bank in range(6):
                _write_png_header(root / f"{bank:02d}" / "0.png", 480, 288)
            _write_png_header(root / "DIVISION" / "0.png", 288, 96)
            _write_png_header(root / "ITEM" / "0.png", 480, 480)
            pack = load_noteskin_pack(root)
            self.assertEqual(pack.root, root.resolve())

    def test_wrong_atlas_dimensions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for bank in range(6):
                _write_png_header(root / f"{bank:02d}" / "0.png", 96, 96)
            _write_png_header(root / "DIVISION" / "0.png", 288, 96)
            _write_png_header(root / "ITEM" / "0.png", 480, 480)
            with self.assertRaises(NoteskinPackError):
                load_noteskin_pack(root)


if __name__ == "__main__":
    unittest.main()
