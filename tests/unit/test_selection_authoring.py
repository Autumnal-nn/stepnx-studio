from __future__ import annotations

import unittest

from stepnx.authoring import (
    CellSelection,
    CellTarget,
    NoteFunction,
    NoteVisibility,
    copy_selection,
    mirror_selection,
    modify_selection_notes,
    paste_clipboard,
    replace_selection_type,
    set_selection_raw,
)
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.commands import SetNoteAt
from tests.fixture_factory import make_normal_nx20


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

    def test_mirror_moves_raw_notes_and_selection(self) -> None:
        document = SetNoteAt(self.row.stable_id, 0, b"\x43\x03\x05\x00").apply(
            self.document
        )
        selection = CellSelection(
            frozenset((CellTarget(self.row.stable_id, 0),)),
            CellTarget(self.row.stable_id, 0),
        )
        command, mirrored_selection = mirror_selection(document, selection)
        mirrored = command.apply(document)
        row = mirrored.splits[0].blocks[0].rows[0]

        self.assertEqual(row.cells[0].raw, b"\x00\x00\x00\x00")
        self.assertEqual(row.cells[4].raw, b"\x43\x03\x05\x00")
        self.assertEqual(
            mirrored_selection.targets,
            frozenset((CellTarget(self.row.stable_id, 4),)),
        )

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
            document, selection, NoteFunction.HIDDEN, NoteVisibility.APPEAR
        )
        edited = command.apply(document).splits[0].blocks[0].rows[0]

        self.assertEqual(len(command.edits), 4)
        for lane, note_type in enumerate((0x1, 0x5, 0x9, 0xD)):
            self.assertEqual(
                edited.cells[lane].raw,
                bytes((0x60 | note_type, 0x01, lane, 0xA0)),
            )


if __name__ == "__main__":
    unittest.main()
