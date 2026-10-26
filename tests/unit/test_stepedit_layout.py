from __future__ import annotations

import math
import unittest
from dataclasses import replace

from stepnx.authoring.snapshot import create_authoring_snapshot
from stepnx.authoring.stepedit_layout import (
    STEPEDIT_VERTICAL_ZOOMS,
    StepEditGeometry,
    StepEditGridLayout,
    StepEditRegion,
)
from stepnx.authoring.structure import StructureTarget, insert_empty_split_after
from stepnx.codecs.nx20 import parse_bytes, serialize
from tests.fixture_factory import make_large_playable, make_normal_nx20


class StepEditGeometryTests(unittest.TestCase):
    def _layout(
        self, *, beat_split: int = 4, zoom: float = 1,
        columns: int = 5, start_column: int = 0, rows: int = 24,
    ):
        doc = parse_bytes(
            make_large_playable(rows=rows, columns=columns, start_column=start_column),
            row_storage="compact",
        )
        snapshot = create_authoring_snapshot(doc)
        split = snapshot.splits[0]
        block = replace(split.blocks[0], beat_split=beat_split)
        snapshot = replace(snapshot, splits=(replace(split, blocks=(block,)),))
        return doc, StepEditGridLayout(snapshot, StepEditGeometry(vertical_zoom=zoom))

    def test_zoom_presets_match_inspected_stepedit_values(self) -> None:
        self.assertEqual(STEPEDIT_VERTICAL_ZOOMS, (1, 2, 3, 4, 6, 8, 12, 16))

    def test_row_pitch_depends_on_zoom_and_beat_split_not_scroll_or_bpm(self) -> None:
        for zoom in STEPEDIT_VERTICAL_ZOOMS:
            for beat_split in (2, 4, 8, 16, 32, 64, 128):
                with self.subTest(zoom=zoom, beat_split=beat_split):
                    _, layout = self._layout(beat_split=beat_split, zoom=zoom)
                    self.assertAlmostEqual(
                        layout.segments[0].row_pitch, 48.0 * zoom / beat_split
                    )

    def test_hittest_roundtrips_row_centers_across_modes(self) -> None:
        for columns, start_column in ((3, 0), (5, 0), (6, 2), (10, 0)):
            for bs in (4, 8, 16, 32, 64, 128):
                with self.subTest(columns=columns, bs=bs):
                    _, layout = self._layout(
                        columns=columns, start_column=start_column,
                        beat_split=bs, zoom=16, rows=32,
                    )
                    segment = layout.segments[0]
                    for row in (0, 1, 10, 30, 31):
                        for lane in (0, columns // 2, columns - 1):
                            hit = layout.hit_test(
                                layout.x_for_lane(lane),
                                segment.y_for_row(row, center=True),
                            )
                            self.assertEqual(hit.region, StepEditRegion.BODY)
                            self.assertEqual(hit.row_index, row)
                            self.assertEqual(hit.lane, lane)
                            self.assertEqual(hit.source_lane, lane + start_column)
                            self.assertEqual(hit.block_id, segment.block_id)

    def test_hit_regions_and_terminal_boundary(self) -> None:
        _, layout = self._layout(rows=20, beat_split=4)
        segment = layout.segments[0]
        y = segment.y_for_row(4, center=True)
        self.assertEqual(layout.hit_test(0, y).region, StepEditRegion.INDICATOR)
        self.assertEqual(
            layout.hit_test(layout.grid_right + 3, y).region,
            StepEditRegion.PROPERTIES,
        )
        self.assertEqual(
            layout.hit_test(layout.x_for_lane(0), segment.bottom - 0.2).region,
            StepEditRegion.RESIZE,
        )
        self.assertEqual(
            layout.hit_test(layout.x_for_lane(0), segment.bottom).region,
            StepEditRegion.GROUND,
        )
        self.assertEqual(layout.hit_test(-1, y).region, StepEditRegion.GROUND)
        self.assertEqual(
            layout.hit_test(layout.content_width + 1, y).region, StepEditRegion.GROUND
        )
        self.assertEqual(layout.hit_test(10, -1).region, StepEditRegion.GROUND)

    def test_viewport_scroll_offsets_logical_y_without_changing_target(self) -> None:
        _, layout = self._layout(rows=40)
        x = layout.x_for_lane(2)
        y = layout.y_for_row(layout.segments[0].split_id, 20, center=True)
        hit = layout.hit_test(x, y - 120, scroll_y=120)
        self.assertEqual((hit.row_index, hit.lane), (20, 2))

    def test_dense_grid_resize_band_does_not_mask_last_row_center(self) -> None:
        _, layout = self._layout(rows=16, beat_split=128, zoom=1)
        segment = layout.segments[0]
        hit = layout.hit_test(layout.x_for_lane(1), segment.y_for_row(15, center=True))
        self.assertEqual(hit.region, StepEditRegion.BODY)
        self.assertEqual(hit.row_index, 15)
        self.assertGreater(
            layout.required_zoom_for_pixel_rows(segment.split_id), 1
        )

    def test_zoom_preserves_anchor_position_via_scroll_projection(self) -> None:
        _, old = self._layout(rows=64, beat_split=8, zoom=2)
        _, new = self._layout(rows=64, beat_split=8, zoom=6)
        split_id = old.segments[0].split_id
        row = 45
        client_y = 220.0
        new_scroll = new.scroll_for_anchor(old, split_id, row, client_y)
        self.assertAlmostEqual(
            new.y_for_row(split_id, row, center=True) - new_scroll,
            client_y,
        )
        hit = new.hit_test(new.x_for_lane(1), client_y, scroll_y=new_scroll)
        self.assertEqual(hit.row_index, row)

    def test_culling_limits_large_chart_to_visible_rows(self) -> None:
        _, layout = self._layout(rows=200_000, beat_split=4)
        pitch = layout.segments[0].row_pitch
        view = layout.visible_segments(100_000 * pitch, 720)
        self.assertEqual(len(view), 1)
        self.assertGreater(view[0].row_count, 0)
        self.assertLess(view[0].row_count, 100)

    def test_split_alternatives_use_only_selected_block_pitch(self) -> None:
        from stepnx.core.commands import InsertBlock
        doc = parse_bytes(make_normal_nx20(), row_storage="compact")
        split = doc.splits[0]
        doc = InsertBlock(split.stable_id, split.blocks[0]).apply(doc)
        snapshot = create_authoring_snapshot(doc)
        first = snapshot.splits[0].blocks[0]
        second = replace(snapshot.splits[0].blocks[1], beat_split=8)
        snap_split = replace(snapshot.splits[0], blocks=(first, second))
        snapshot = replace(snapshot, splits=(snap_split,))
        before = StepEditGridLayout(snapshot)
        after = StepEditGridLayout(snapshot.with_active_block(split.stable_id, second.stable_id))
        self.assertEqual(before.segments[0].row_pitch, 48 / first.beat_split)
        self.assertEqual(after.segments[0].row_pitch, 6.0)
        self.assertEqual(serialize(doc), serialize(doc))

    def test_multiple_splits_stack_in_chart_order(self) -> None:
        doc = parse_bytes(make_normal_nx20(), row_storage="compact")
        split = doc.splits[0]
        doc = insert_empty_split_after(
            doc, StructureTarget(split.stable_id, split.blocks[0].stable_id)
        ).apply(doc)
        layout = StepEditGridLayout(create_authoring_snapshot(doc))
        self.assertEqual(len(layout.segments), 2)
        self.assertEqual(layout.segments[0].bottom, layout.segments[1].top)
        second = layout.segments[1]
        hit = layout.hit_test(layout.x_for_lane(0), second.y_for_row(0, center=True))
        self.assertEqual(hit.split_id, second.split_id)

    def test_projection_never_serializes_or_mutates_source(self) -> None:
        data = make_normal_nx20(opaque_tail=True)
        doc = parse_bytes(data, row_storage="compact")
        before = serialize(doc)
        snap = create_authoring_snapshot(doc)
        layout = StepEditGridLayout(snap, StepEditGeometry(vertical_zoom=12))
        layout.hit_test(layout.x_for_lane(2), layout.y_for_row(snap.splits[0].stable_id, 0))
        self.assertEqual(serialize(doc), before)
        self.assertEqual(before, data)

    def test_invalid_geometry_rejected(self) -> None:
        for bad in (0, -1, math.inf, math.nan):
            with self.subTest(zoom=bad), self.assertRaises(ValueError):
                StepEditGeometry(vertical_zoom=bad)
        _, layout = self._layout()
        with self.assertRaises(ValueError):
            layout.required_zoom_for_pixel_rows(layout.segments[0].split_id, minimum_pixels=0)
        self.assertEqual(layout.hit_test(math.nan, 100).region, StepEditRegion.GROUND)


if __name__ == "__main__":
    unittest.main()
