from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stepnx.authoring.field import FieldGeometry, SetChartField, count_dropped_nonempty_cells
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import EmptyRow, NoteRow
from stepnx.core.validation import validate
from stepnx.workspace import (
    WorkspaceError,
    delete_nx_chart,
    execute_save_plan,
    normalize_nx_filename,
    open_folder,
    plan_create_nx_chart,
    plan_duplicate_nx_chart,
)
from tests.fixture_factory import make_implicit_lightmap, make_normal_nx20


class Phase11FieldGeometryTests(unittest.TestCase):
    def test_single_to_double_preserves_absolute_panels_and_adds_zero_cells(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False), row_storage="rich")
        source_row = document.splits[0].blocks[0].rows[0]
        self.assertIsInstance(source_row, NoteRow)
        edited = SetChartField(FieldGeometry.double()).apply(document)
        row = edited.splits[0].blocks[0].rows[0]
        self.assertEqual((edited.start_column.value, edited.columns.value), (0, 10))
        self.assertIsInstance(row, NoteRow)
        self.assertEqual(tuple(cell.raw for cell in row.cells[:5]), tuple(cell.raw for cell in source_row.cells))
        self.assertEqual(tuple(cell.raw for cell in row.cells[5:]), (b"\0\0\0\0",) * 5)
        self.assertTrue(validate(edited).is_valid)

    def test_shrinking_field_requires_explicit_note_loss(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False), row_storage="rich")
        geometry = FieldGeometry(1, 4)
        self.assertGreater(count_dropped_nonempty_cells(document, geometry), 0)
        with self.assertRaisesRegex(ModelInvariantError, "discard"):
            SetChartField(geometry).apply(document)
        edited = SetChartField(geometry, allow_note_loss=True).apply(document)
        self.assertEqual((edited.start_column.value, edited.columns.value), (1, 4))
        self.assertTrue(validate(edited).is_valid)

    def test_half_double_preset_is_columns_two_through_seven(self) -> None:
        geometry = FieldGeometry.half_double()
        self.assertEqual((geometry.start_column, geometry.columns, geometry.stop_column), (2, 6, 8))

    def test_three_columns_remain_reserved_for_lightmap(self) -> None:
        document = parse_bytes(make_normal_nx20(sized_trailer=False))
        with self.assertRaisesRegex(ValueError, "Lightmap"):
            SetChartField(FieldGeometry(0, 3)).apply(document)


class Phase11NXFileManagementTests(unittest.TestCase):
    def _folder(self, root: Path) -> None:
        (root / "LM.NX").write_bytes(make_implicit_lightmap())
        (root / "NM.NX").write_bytes(make_normal_nx20(sized_trailer=False))

    def test_create_uses_lightmap_skeleton_and_empty_note_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._folder(root)
            workspace = open_folder(root)
            plan = plan_create_nx_chart(workspace, "CR.NX", FieldGeometry.single())
            self.assertTrue(plan.is_ready)
            execute_save_plan(plan)
            created = open_folder(root).document_for(root / "CR.NX").document
            self.assertFalse(created.effective_lightmap)
            self.assertEqual((created.start_column.value, created.columns.value), (0, 5))
            self.assertEqual(created.statistics()["note_cells"], 0)
            self.assertTrue(all(isinstance(row, EmptyRow) for split in created.splits for block in split.blocks for row in block.rows))
            self.assertTrue(validate(created).is_valid)

    def test_duplicate_is_byte_exact_and_selected_chart_can_be_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._folder(root)
            workspace = open_folder(root)
            source = root / "NM.NX"
            original = source.read_bytes()
            plan = plan_duplicate_nx_chart(workspace, source, "NM_COPY.NX")
            execute_save_plan(plan)
            duplicate = root / "NM_COPY.NX"
            self.assertEqual(duplicate.read_bytes(), original)
            workspace = open_folder(root)
            removed = delete_nx_chart(workspace, duplicate)
            self.assertEqual(removed, duplicate.resolve())
            self.assertFalse(duplicate.exists())
            self.assertTrue((root / "NM.NX").exists())
            self.assertTrue((root / "LM.NX").exists())

    def test_lightmap_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._folder(root)
            workspace = open_folder(root)
            lightmap = root / "LM.NX"
            with self.assertRaisesRegex(WorkspaceError, "protected"):
                plan_duplicate_nx_chart(workspace, lightmap, "COPY.NX")
            with self.assertRaisesRegex(WorkspaceError, "protected"):
                delete_nx_chart(workspace, lightmap)
            self.assertTrue(lightmap.exists())

    def test_operations_reject_case_collision_external_change_and_bad_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._folder(root)
            workspace = open_folder(root)
            with self.assertRaises(FileExistsError):
                plan_create_nx_chart(workspace, "nm.nx", FieldGeometry.single())
            with self.assertRaises(ValueError):
                normalize_nx_filename("BAD?.NX")
            source = root / "NM.NX"
            source.write_bytes(source.read_bytes() + b"changed")
            with self.assertRaisesRegex(WorkspaceError, "changed outside"):
                plan_duplicate_nx_chart(workspace, source, "COPY.NX")


if __name__ == "__main__":
    unittest.main()
