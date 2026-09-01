from __future__ import annotations

import unittest
from time import perf_counter

from stepnx.authoring import (
    CellSelection,
    CellTarget,
    NoteFunction,
    NoteVisibility,
    copy_selection,
    cut_selection,
    flip_horizontal_selection,
    flip_vertical_selection,
    mirror_selection,
    modify_selection_notes,
    paste_clipboard,
    replace_selection_type,
    set_selection_raw,
)
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import NoteEdit, SetNoteAt, SetNotesAt
from stepnx.core.model import OverlayRows
from tests.fixture_factory import make_large_playable, make_normal_nx20


class CellSelectionTests(unittest.TestCase):
    def test_rectangle_uses_stable_rows_and_inclusive_lanes(self) -> None:
        rows = (10, 20, 30, 40)
        selection = CellSelection().replace(CellTarget(20, 1))
        selection = selection.rectangle(rows, CellTarget(40, 3))

        self.assertEqual(len(selection.targets), 9)
        self.assertIn(CellTarget(30, 2), selection.targets)

    def test_toggle_and_clear_are_deterministic(self) -> None:
        target = CellTarget(10, 1)
        selection = CellSelection().toggle(target).toggle(target)
        self.assertFalse(selection.targets)
        self.assertFalse(selection.clear().targets)


class BulkSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = parse_bytes(make_normal_nx20(), source="NM.NX")
        self.row = self.document.splits[0].blocks[0].rows[0]

    def test_apply_raw_is_one_atomic_command(self) -> None:
        selection = CellSelection(
            frozenset((CellTarget(self.row.stable_id, 0), CellTarget(self.row.stable_id, 4)))
        )
        edited = set_selection_raw(selection, b"\x43\x03\x02\x00").apply(self.document)
        row = edited.splits[0].blocks[0].rows[0]
        self.assertEqual(row.cells[0].raw, b"\x43\x03\x02\x00")
        self.assertEqual(row.cells[4].raw, b"\x43\x03\x02\x00")

    @staticmethod
    def _numbered_document(columns: int, rows: int = 2):
        document = parse_bytes(
            make_large_playable(rows=rows, columns=columns), row_storage="compact"
        )
        block_rows = document.splits[0].blocks[0].rows
        edits = tuple(
            NoteEdit(
                row.stable_id,
                lane,
                bytes((0x43, 0x03, row_index * 16 + lane, 0x00)),
            )
            for row_index, row in enumerate(block_rows)
            for lane in range(columns)
        )
        return SetNotesAt(edits).apply(document)

    @staticmethod
    def _rectangle(document, row_indexes, lanes):
        rows = document.splits[0].blocks[0].rows
        targets = frozenset(
            CellTarget(rows[row_index].stable_id, lane)
            for row_index in row_indexes
            for lane in lanes
        )
        return CellSelection(targets, min(targets))

    def test_flip_horizontal_is_bounded_by_selected_columns(self) -> None:
        document = self._numbered_document(5)
        selection = self._rectangle(document, (0,), (1, 2, 3))

        command, transformed_selection = flip_horizontal_selection(
            document, selection
        )
        transformed = command.apply(document).splits[0].blocks[0].rows[0]

        self.assertEqual([cell.raw[2] for cell in transformed.cells], [0, 3, 2, 1, 4])
        self.assertEqual(transformed_selection.targets, selection.targets)

    def test_flip_vertical_reverses_rows_only_inside_selected_columns(self) -> None:
        document = self._numbered_document(5)
        selection = self._rectangle(document, (0, 1), (1, 2, 3))

        command, _ = flip_vertical_selection(document, selection)
        transformed = command.apply(document).splits[0].blocks[0].rows

        self.assertEqual(
            [cell.raw[2] for cell in transformed[0].cells], [0, 17, 18, 19, 4]
        )
        self.assertEqual(
            [cell.raw[2] for cell in transformed[1].cells], [16, 1, 2, 3, 20]
        )

    def test_mirror_uses_stepedit_single_half_double_and_double_permutations(
        self,
    ) -> None:
        cases = (
            (5, tuple(range(5)), [3, 4, 2, 0, 1]),
            (6, tuple(range(6)), [5, 3, 4, 1, 2, 0]),
            (10, tuple(range(10)), [8, 9, 7, 5, 6, 3, 4, 2, 0, 1]),
            (10, tuple(range(5)), [3, 4, 2, 0, 1, 5, 6, 7, 8, 9]),
            (10, tuple(range(5, 10)), [0, 1, 2, 3, 4, 8, 9, 7, 5, 6]),
        )
        for columns, lanes, expected in cases:
            with self.subTest(columns=columns, lanes=lanes):
                document = self._numbered_document(columns)
                selection = self._rectangle(document, (0,), lanes)

                command, _ = mirror_selection(document, selection)
                transformed = command.apply(document).splits[0].blocks[0].rows[0]

                self.assertEqual([cell.raw[2] for cell in transformed.cells], expected)

    def test_mirror_rejects_a_five_column_slice_between_double_pads(self) -> None:
        document = self._numbered_document(10)
        selection = self._rectangle(document, (0,), (1, 2, 3, 4, 5))

        with self.assertRaisesRegex(ValueError, "Mirror requires"):
            mirror_selection(document, selection)

    def test_transform_rejects_non_rectangular_selection(self) -> None:
        document = self._numbered_document(5)
        rows = document.splits[0].blocks[0].rows
        selection = CellSelection(
            frozenset(
                (
                    CellTarget(rows[0].stable_id, 0),
                    CellTarget(rows[0].stable_id, 1),
                    CellTarget(rows[1].stable_id, 0),
                )
            )
        )

        with self.assertRaisesRegex(ValueError, "rectangular"):
            flip_horizontal_selection(document, selection)

    def test_copy_and_paste_preserve_raw_cells_and_refuse_boundary_crossing(self) -> None:
        document = SetNoteAt(self.row.stable_id, 0, b"\x43\x03\x05\x00").apply(
            self.document
        )
        selection = CellSelection(
            frozenset((CellTarget(self.row.stable_id, 0),)),
            CellTarget(self.row.stable_id, 0),
        )
        clipboard = copy_selection(document, selection)
        command, pasted_selection = paste_clipboard(
            document, clipboard, CellTarget(self.row.stable_id, 4)
        )
        pasted = command.apply(document).splits[0].blocks[0].rows[0]
        self.assertEqual(pasted.cells[4].raw, b"\x43\x03\x05\x00")
        self.assertIn(CellTarget(self.row.stable_id, 4), pasted_selection.targets)

        with self.assertRaisesRegex(ValueError, "lane boundary"):
            paste_clipboard(document, clipboard, CellTarget(self.row.stable_id, 5))

    def test_cut_copies_then_clears_the_selection(self) -> None:
        document = self._numbered_document(5)
        selection = self._rectangle(document, (0,), (1, 2, 3))

        clipboard, command = cut_selection(document, selection)
        cut = command.apply(document).splits[0].blocks[0].rows[0]

        self.assertEqual([cell[2][2] for cell in clipboard.cells], [1, 2, 3])
        self.assertEqual(
            [cell.raw for cell in cut.cells[1:4]],
            [b"\x00\x00\x00\x00"] * 3,
        )

    def test_replace_filters_by_low_nibble_type(self) -> None:
        selection = CellSelection(
            frozenset(
                (CellTarget(self.row.stable_id, 0), CellTarget(self.row.stable_id, 1))
            )
        )
        command = replace_selection_type(
            self.document, selection, 3, b"\x41\x03\x17\x00"
        )
        edited = command.apply(self.document).splits[0].blocks[0].rows[0]
        self.assertEqual(edited.cells[0].raw, b"\x41\x03\x17\x00")
        self.assertNotEqual(edited.cells[1].raw, b"\x41\x03\x17\x00")

    def test_note_flags_preserve_type_bank_slot_and_brain_shower(self) -> None:
        document = SetNoteAt(
            self.row.stable_id, 0, b"\x43\x93\x05\xC7"
        ).apply(self.document)
        selection = CellSelection(
            frozenset((CellTarget(self.row.stable_id, 0),))
        )

        command = modify_selection_notes(
            document, selection, NoteFunction.GHOST, NoteVisibility.VANISH
        )
        raw = command.apply(document).splits[0].blocks[0].rows[0].cells[0].raw

        self.assertEqual(raw, b"\x23\x92\x05\xC7")

    def test_note_flags_do_not_repurpose_division_trigger_bit(self) -> None:
        document = SetNoteAt(
            self.row.stable_id, 0, b"\x62\x03\x01\x00"
        ).apply(self.document)
        selection = CellSelection(
            frozenset((CellTarget(self.row.stable_id, 0),))
        )
        with self.assertRaisesRegex(ValueError, "no editable notes"):
            modify_selection_notes(
                document, selection, NoteFunction.GHOST, NoteVisibility.INVISIBLE
            )

    def test_note_flags_cover_all_odd_note_variants_in_one_command(self) -> None:
        document = self.document
        for lane, note_type in enumerate((0x1, 0x5, 0x9, 0xD)):
            document = SetNoteAt(
                self.row.stable_id, lane, bytes((0x40 | note_type, 0x03, lane, 0xA0))
            ).apply(document)
        selection = CellSelection(
            frozenset(CellTarget(self.row.stable_id, lane) for lane in range(4))
        )

        command = modify_selection_notes(
            document, selection, NoteFunction.BONUS, NoteVisibility.APPEAR
        )
        edited = command.apply(document).splits[0].blocks[0].rows[0]

        self.assertEqual(len(command.edits), 4)
        for lane, note_type in enumerate((0x1, 0x5, 0x9, 0xD)):
            self.assertEqual(
                edited.cells[lane].raw,
                bytes((0x60 | note_type, 0x01, lane, 0xA0)),
            )

    def test_fifty_note_copy_and_paste_stays_sparse_on_a_large_chart(self) -> None:
        document = parse_bytes(
            make_large_playable(rows=200_000), row_storage="compact"
        )
        rows = document.splits[0].blocks[0].rows
        selection = CellSelection(
            frozenset(
                CellTarget(rows[index].stable_id, 0)
                for index in range(100_000, 100_050)
            )
        )

        started = perf_counter()
        source = set_selection_raw(selection, b"\x43\x03\x00\x00").apply(document)
        clipboard = copy_selection(source, selection)
        command, _ = paste_clipboard(
            source, clipboard, CellTarget(rows[150_000].stable_id, 1)
        )
        pasted = command.apply(source)
        elapsed = perf_counter() - started

        pasted_rows = pasted.splits[0].blocks[0].rows
        self.assertIsInstance(pasted_rows, OverlayRows)
        self.assertEqual(len(pasted_rows.replacements), 100)
        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()
