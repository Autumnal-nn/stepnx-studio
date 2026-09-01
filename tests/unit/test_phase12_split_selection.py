from __future__ import annotations

import unittest

from stepnx.authoring.split_selection import SplitSelectionByte, SetSplitSelectionByte
from stepnx.authoring.tools import NoteFunction, NoteTool, NoteVisibility, note_tool_raw
from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.commands import CommandStack
from tests.fixture_factory import make_normal_nx20


class SplitSelectionByteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = parse_bytes(make_normal_nx20(sized_trailer=False))
        self.split = self.document.splits[0]

    def test_every_bit_roundtrips_through_typed_projection(self) -> None:
        for value in range(256):
            self.assertEqual(SplitSelectionByte.from_raw(value).raw, value)

    def test_c0_is_preserved_as_both_random_flags(self) -> None:
        selection = SplitSelectionByte.from_raw(0xC0)
        self.assertTrue(selection.random_at_start)
        self.assertTrue(selection.random_at_trigger)
        self.assertFalse(selection.force_select)
        self.assertEqual(selection.bank, 0)
        self.assertEqual(selection.raw, 0xC0)

    def test_split_selector_command_is_undoable_and_serializable(self) -> None:
        stack = CommandStack(self.document)
        edited = stack.execute(SetSplitSelectionByte(self.split.stable_id, 0xC5))
        self.assertEqual(edited.splits[0].raw_select.value, 0xC5)
        reparsed = parse_bytes(serialize(edited))
        self.assertEqual(reparsed.splits[0].raw_select.value, 0xC5)
        self.assertEqual(serialize(stack.undo()), serialize(self.document))

    def test_unusual_values_warn_instead_of_being_rejected(self) -> None:
        single_block = SplitSelectionByte.from_raw(0x21)
        warnings = single_block.warnings(block_count=1)
        self.assertTrue(warnings)
        self.assertEqual(single_block.raw, 0x21)


class LowVisibilityEncodingTests(unittest.TestCase):
    def test_nxa_low_visibility_names_keep_exact_values(self) -> None:
        self.assertEqual(int(NoteVisibility.VANISH_LOW), 4)
        self.assertEqual(int(NoteVisibility.APPEAR_LOW), 5)
        vanish_low = note_tool_raw(
            NoteTool.TAP, 0, NoteFunction.NORMAL, NoteVisibility.VANISH_LOW
        )
        appear_low = note_tool_raw(
            NoteTool.TAP, 0, NoteFunction.NORMAL, NoteVisibility.APPEAR_LOW
        )
        self.assertEqual(vanish_low[1] & 0x07, 4)
        self.assertEqual(appear_low[1] & 0x07, 5)


if __name__ == "__main__":
    unittest.main()
