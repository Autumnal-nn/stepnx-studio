from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from stepnx.authoring import (
    MetadataScope,
    TimelineGeometry,
    TimelineLayout,
    VisualPackError,
    create_authoring_snapshot,
    load_visual_pack,
)
from stepnx.authoring.benchmark import benchmark_viewport
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.model import CompactRows
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
        self.assertLess(count, 50)
        self.assertEqual(self.snapshot.splits[0].blocks[0].row_count, 267_264)

    def test_row_hit_testing_and_zoom_are_consistent(self) -> None:
        layout = TimelineLayout(self.snapshot, TimelineGeometry(row_height=20))
        segment = layout.segments[0]
        hit = layout.row_at_y(segment.rows_top + 10 * 20 + 1)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1], 10)
        zoomed = TimelineLayout(self.snapshot, layout.geometry.zoomed(2))
        self.assertEqual(zoomed.row_at_y(zoomed.segments[0].rows_top + 10 * 40 + 1)[1], 10)

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


if __name__ == "__main__":
    unittest.main()
