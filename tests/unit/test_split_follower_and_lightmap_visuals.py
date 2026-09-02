from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from stepnx.authoring.split_selection import SplitSelectionByte
from stepnx.authoring.timeline import TimelineGeometry
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import InsertBlock
from stepnx.gui.lightmap_visual_polish import lightmap_alpha, lightmap_rect
from stepnx.preview import RoutePolicy, create_preview_snapshot, resolve_route
from tests.fixture_factory import make_normal_nx20


class SplitFollowerSemanticsTests(unittest.TestCase):
    def _two_block_snapshot(self):
        document = parse_bytes(
            make_normal_nx20(), source="Follower.NX", row_storage="compact"
        )
        split = document.splits[0]
        document = InsertBlock(split.stable_id, split.blocks[0]).apply(document)
        return create_preview_snapshot(document)

    def test_banked_condition_selector_is_valid_without_random_flag(self) -> None:
        selection = SplitSelectionByte.from_raw(0x01)
        self.assertEqual(selection.mode_label, "ordered, bank 1")
        self.assertEqual(selection.warnings(block_count=4), ())

    def test_0x40_fallback_and_0x41_follower_are_distinct(self) -> None:
        unbanked = SplitSelectionByte.from_raw(0x40)
        self.assertFalse(unbanked.has_bank)
        self.assertFalse(unbanked.follower)
        self.assertTrue(unbanked.random_at_block_start)
        self.assertEqual(unbanked.mode_label, "random at block start")
        self.assertEqual(unbanked.raw, 0x40)

        banked = SplitSelectionByte.from_raw(0x41)
        self.assertTrue(banked.has_bank)
        self.assertTrue(banked.follower)
        self.assertFalse(banked.random_at_block_start)
        self.assertEqual(banked.mode_label, "follower block, bank 1")
        self.assertNotIn("random", banked.mode_label)

        load_random = SplitSelectionByte.from_raw(0x80)
        self.assertEqual(load_random.mode_label, "random at chart load")

        # Timing is semantically observable. Even though the 0x40 Split appears
        # first in chart order, every 0x80 choice consumes its RNG state at load
        # before the 0x40 fallback is evaluated at Split entry. With seed 7 the
        # first two binary draws are 1, 0, so decisions become [0, 1], not [1, 0].
        snapshot = self._two_block_snapshot()
        base = snapshot.splits[0]
        runtime_random = replace(
            base,
            stable_id=201,
            raw_select=0x40,
            random_at_start=False,
            random_at_trigger=True,
            group=0,
        )
        preloaded_random = replace(
            base,
            stable_id=202,
            raw_select=0x80,
            random_at_start=True,
            random_at_trigger=False,
            group=0,
        )
        snapshot = replace(snapshot, splits=(runtime_random, preloaded_random))
        route = resolve_route(snapshot, RoutePolicy.SEEDED, seed=7)
        self.assertEqual(
            [
                split.block(decision.block_id).index
                for split, decision in zip(snapshot.splits, route.decisions)
            ],
            [0, 1],
        )

    def test_manual_or_condition_candidate_feeds_following_bank(self) -> None:
        snapshot = self._two_block_snapshot()
        base = snapshot.splits[0]
        selector = replace(
            base,
            stable_id=101,
            raw_select=0x01,
            random_at_start=False,
            random_at_trigger=False,
            group=1,
        )
        follower = replace(
            base,
            stable_id=102,
            raw_select=0x41,
            random_at_start=False,
            random_at_trigger=True,
            group=1,
        )
        snapshot = replace(snapshot, splits=(selector, follower))
        selected = selector.blocks[1].stable_id
        route = resolve_route(
            snapshot,
            RoutePolicy.SEEDED,
            seed=17,
            manual={selector.stable_id: selected},
        )
        self.assertTrue(route.is_executable)
        self.assertEqual(
            [
                split.block(decision.block_id).index
                for split, decision in zip(snapshot.splits, route.decisions)
            ],
            [1, 1],
        )
        self.assertIn("follower bank 1", route.decisions[1].reason)


class LightmapVisualPolishTests(unittest.TestCase):
    def test_lightmap_opacity_is_fixed_at_twenty_and_eighty_percent(self) -> None:
        self.assertEqual(lightmap_alpha(0), 51)
        self.assertEqual(lightmap_alpha(1), 204)
        self.assertEqual(lightmap_alpha(255), 204)

    def test_selection_rect_is_the_same_zoomable_light_lane_geometry(self) -> None:
        baseline = SimpleNamespace(_geometry=TimelineGeometry())
        enlarged = SimpleNamespace(
            _geometry=TimelineGeometry(
                row_height=96.0,
                lane_width=96.0,
                ruler_width=184.0,
                block_info_width=600.0,
                footer_height=48.0,
            )
        )
        small = lightmap_rect(baseline, 1, 48.0, 48.0)
        large = lightmap_rect(enlarged, 1, 96.0, 96.0)
        self.assertEqual((small.width(), small.height()), (44.0, 44.0))
        self.assertEqual((large.width(), large.height()), (92.0, 92.0))
        self.assertGreater(large.width(), small.width())
        self.assertGreater(large.height(), small.height())


if __name__ == "__main__":
    unittest.main()
