from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from stepnx.authoring.selection import CellSelection, CellTarget
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.scalars import RawF32
from stepnx.gui.editor_ux_cleanup import (
    _clipboard_compatible,
    _selected_document,
    _structure_actions,
    inspector_context_exists,
    inspector_context_signature,
    selection_summary,
    selection_transform_state,
)
from stepnx.gui.phase10_timeline import context_menu_capabilities
from stepnx.gui.selection_lightmap_workflow import GridClipboard
from stepnx.gui.split_follower_ui import route_mode_label
from tests.fixture_factory import make_normal_nx20


class _Row:
    def __init__(self, stable_id: int) -> None:
        self.stable_id = stable_id


class _Block:
    def __init__(self, stable_id: int, row_ids) -> None:
        self.stable_id = stable_id
        self.rows = tuple(_Row(value) for value in row_ids)
        self.row_count = len(self.rows)


class _Segment:
    def __init__(self, block: _Block) -> None:
        self.block = block


class _TreeItem:
    def __init__(self, payload) -> None:
        self.payload = payload

    def data(self, *_args):
        return self.payload


class EditorUxCleanupTests(unittest.TestCase):
    @staticmethod
    def _route(raw: int):
        return SimpleNamespace(
            random_at_start=bool(raw & 0x80),
            random_at_trigger=bool(raw & 0x40),
            force_select=bool(raw & 0x20),
            group=raw & 0x1F,
        )

    @staticmethod
    def _widget(targets, *, lightmap=False, columns=5):
        return SimpleNamespace(
            selection=CellSelection(frozenset(targets), next(iter(targets), None)),
            snapshot=SimpleNamespace(effective_lightmap=lightmap, columns=columns),
            _layout=SimpleNamespace(
                segments=(
                    _Segment(_Block(10, (1, 2))),
                    _Segment(_Block(20, (3, 4))),
                )
            ),
        )

    @staticmethod
    def _document():
        return parse_bytes(make_normal_nx20(), row_storage="rich")

    def test_route_labels_are_rendered_from_selector_semantics(self) -> None:
        self.assertEqual(route_mode_label(self._route(0x80)), "random at chart load")
        self.assertEqual(route_mode_label(self._route(0x40)), "random at block start")
        self.assertEqual(route_mode_label(self._route(0x41)), "follower block, bank 1")
        self.assertNotIn("random trigger", route_mode_label(self._route(0x41)))
        self.assertNotIn("group", route_mode_label(self._route(0x41)))

    def test_route_label_keeps_recalculate_flag_in_decoded_semantics(self) -> None:
        self.assertEqual(route_mode_label(self._route(0x21)), "force select, bank 1")

    def test_rectangular_selection_summary_reports_rows_lanes_and_blocks(self) -> None:
        targets = {CellTarget(row_id, lane) for row_id in (2, 3) for lane in (0, 1)}
        self.assertEqual(
            selection_summary(self._widget(targets)),
            "4 cells selected · 2 rows × 2 lanes · across 2 Blocks",
        )

    def test_sparse_selection_summary_does_not_claim_rectangle(self) -> None:
        targets = {CellTarget(1, 0), CellTarget(3, 2)}
        self.assertEqual(
            selection_summary(self._widget(targets)),
            "2 cells selected · 2 rows · 2 lanes · across 2 Blocks",
        )

    def test_lightmap_selection_summary_uses_light_cell_noun(self) -> None:
        targets = {CellTarget(1, 0), CellTarget(1, 1), CellTarget(1, 2)}
        self.assertEqual(
            selection_summary(self._widget(targets, lightmap=True, columns=3)),
            "3 light cells selected · 1 row × 3 lanes",
        )

    def test_single_lightmap_selection_has_nonempty_feedback(self) -> None:
        self.assertEqual(
            selection_summary(self._widget({CellTarget(1, 0)}, lightmap=True, columns=3)),
            "1 light cell selected",
        )

    def test_clipboard_compatibility_rejects_cross_document_kind(self) -> None:
        note_clipboard = GridClipboard("notes", 1, 1, ((0, 0, b"\0\0\0\0"),))
        light_clipboard = GridClipboard("lightmap", 1, 1, ((0, 0, b"\x01"),))
        note_widget = self._widget({CellTarget(1, 0)})
        light_widget = self._widget({CellTarget(1, 0)}, lightmap=True, columns=3)
        self.assertTrue(_clipboard_compatible(note_widget, note_clipboard))
        self.assertTrue(_clipboard_compatible(light_widget, light_clipboard))
        self.assertFalse(_clipboard_compatible(note_widget, light_clipboard))
        self.assertFalse(_clipboard_compatible(light_widget, note_clipboard))

    def test_split_context_reuses_canonical_actions(self) -> None:
        actions = {name: object() for name in (
            "insert_split_action",
            "remove_split_action",
            "move_split_up_action",
            "move_split_down_action",
            "phase12_edit_split_selection_action",
        )}
        groups = _structure_actions(SimpleNamespace(**actions), "split")
        self.assertEqual(groups[0], tuple(actions[name] for name in (
            "insert_split_action",
            "remove_split_action",
            "move_split_up_action",
            "move_split_down_action",
        )))
        self.assertEqual(groups[1], (actions["phase12_edit_split_selection_action"],))

    def test_block_context_reuses_edit_and_structure_actions(self) -> None:
        actions = {name: object() for name in (
            "insert_block_action",
            "remove_block_action",
            "move_block_up_action",
            "move_block_down_action",
            "edit_timing_action",
            "phase12_edit_split_selection_action",
            "phase11_division_metadata_action",
        )}
        groups = _structure_actions(SimpleNamespace(**actions), "block")
        self.assertEqual(
            tuple(action for group in groups for action in group),
            tuple(actions.values()),
        )

    def test_inspector_context_detects_existing_and_missing_blocks(self) -> None:
        document = self._document()
        split = document.splits[0]
        block = split.blocks[0]
        context = ("block", 0, split.stable_id, block.stable_id)
        self.assertTrue(inspector_context_exists(document, context))
        self.assertFalse(
            inspector_context_exists(
                document,
                ("block", 0, split.stable_id, block.stable_id + 999999),
            )
        )

    def test_inspector_signature_ignores_row_only_edits(self) -> None:
        document = self._document()
        split = document.splits[0]
        block = split.blocks[0]
        context = ("block", 0, split.stable_id, block.stable_id)
        before = inspector_context_signature(document, context)
        reversed_block = replace(block, rows=tuple(reversed(block.rows)))
        edited = replace(
            document,
            splits=(replace(split, blocks=(reversed_block, *split.blocks[1:])), *document.splits[1:]),
        )
        self.assertEqual(inspector_context_signature(edited, context), before)

    def test_inspector_signature_changes_with_visible_timing(self) -> None:
        document = self._document()
        split = document.splits[0]
        block = split.blocks[0]
        context = ("block", 0, split.stable_id, block.stable_id)
        before = inspector_context_signature(document, context)
        changed_block = replace(block, bpm=RawF32.from_value(float(block.bpm.value) + 1.0))
        edited = replace(
            document,
            splits=(replace(split, blocks=(changed_block, *split.blocks[1:])), *document.splits[1:]),
        )
        self.assertNotEqual(inspector_context_signature(edited, context), before)

    def test_rectangular_note_selection_enables_flip_but_not_partial_mirror(self) -> None:
        targets = {CellTarget(row, lane) for row in (1, 2) for lane in (0, 1)}
        self.assertEqual(selection_transform_state(self._widget(targets)), (True, False))

    def test_sparse_selection_disables_rectangular_transforms(self) -> None:
        widget = self._widget({CellTarget(1, 0), CellTarget(2, 1)})
        self.assertEqual(selection_transform_state(widget), (False, False))

    def test_full_single_field_enables_stepedit_mirror(self) -> None:
        targets = {CellTarget(1, lane) for lane in range(5)}
        self.assertEqual(selection_transform_state(self._widget(targets)), (True, True))

    def test_lightmap_disables_note_transforms(self) -> None:
        targets = {CellTarget(1, lane) for lane in range(3)}
        self.assertEqual(
            selection_transform_state(self._widget(targets, lightmap=True, columns=3)),
            (False, False),
        )

    def test_timeline_context_disables_removing_the_only_block(self) -> None:
        one = SimpleNamespace(stable_id=10, blocks=(object(),))
        two = SimpleNamespace(stable_id=20, blocks=(object(), object()))
        snapshot = SimpleNamespace(splits=(one, two))
        self.assertFalse(context_menu_capabilities(snapshot, 10, 1)["remove_block"])
        self.assertTrue(context_menu_capabilities(snapshot, 20, 1)["remove_block"])
        self.assertFalse(context_menu_capabilities(snapshot, 10, 0)["split_here"])
        self.assertTrue(context_menu_capabilities(snapshot, 10, 1)["split_here"])
        self.assertTrue(context_menu_capabilities(snapshot, 10, 1)["merge_splits"])
        self.assertFalse(context_menu_capabilities(snapshot, 20, 1)["merge_splits"])

    def test_field_action_target_follows_workspace_tree_selection(self) -> None:
        chart = SimpleNamespace(effective_lightmap=False)
        lightmap = SimpleNamespace(effective_lightmap=True)
        workspace = SimpleNamespace(
            documents=(SimpleNamespace(document=chart), SimpleNamespace(document=lightmap))
        )
        window = SimpleNamespace(
            workspace=workspace,
            tree=SimpleNamespace(currentItem=lambda: _TreeItem(("document", 1, None, None))),
            _current_document_index=lambda: 0,
        )
        self.assertIs(_selected_document(window), lightmap)


if __name__ == "__main__":
    unittest.main()
