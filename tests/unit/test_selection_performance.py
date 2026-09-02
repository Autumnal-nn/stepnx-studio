from __future__ import annotations

import struct
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from stepnx.authoring import (
    CellSelection,
    CellTarget,
    copy_selection,
    cut_selection,
    flip_horizontal_selection,
    flip_vertical_selection,
    mirror_selection,
    paste_clipboard,
    replace_selection_type,
    set_selection_raw,
)
from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.model import CompactRows, OverlayRows


_TOTAL_ROWS = 200_000
_COLUMNS = 10
_SOURCE_START = 80_000
_SOURCE_NOTE_ROWS = 2_000
_DESTINATION_START = 140_000
_SELECTION_SIZES = (50, 500, 5_000)


def _u32(value: int) -> bytes:
    return struct.pack("<I", value)


def _f32(value: float) -> bytes:
    return struct.pack("<f", value)


def _large_source_backed_chart() -> bytes:
    """Build a large compact chart with one dense source-backed note window."""

    data = bytearray(b"NX20")
    data += _u32(0) + _u32(_COLUMNS) + _u32(0)
    data += _u32(0)  # Header metadata count.
    data += _u32(1)  # Split count.
    data += b"\x00\x00\x00\x00"
    data += _u32(0)  # Split metadata count.
    data += _u32(1)  # Block count.
    data += _f32(0.0) + _f32(120.0) + _f32(0.5) + _f32(0.0) + _f32(1.0)
    data += bytes((4, 4, 0, 0))
    data += _u32(0)  # Division metadata count.
    data += _u32(_TOTAL_ROWS)

    empty_row = b"\x80\x00\x00\x00"
    note_row = b"\x43\x03\x00\x00" * _COLUMNS
    suffix_rows = _TOTAL_ROWS - _SOURCE_START - _SOURCE_NOTE_ROWS
    data += empty_row * _SOURCE_START
    data += note_row * _SOURCE_NOTE_ROWS
    data += empty_row * suffix_rows
    return bytes(data)


class SelectionPerformanceRegressionTests(unittest.TestCase):
    """Protect 0.9.4 sparse bulk-note paths from whole-chart regressions.

    Wall-clock assertions are intentionally not the primary gate. CI host speed
    varies; row materialization behavior does not. These tests reject iteration
    of CompactRows/OverlayRows and cap indexed CompactRows reads as a function of
    the selected cells/rows rather than the 200,000-row chart size.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.document = parse_bytes(
            _large_source_backed_chart(),
            source="PERF.NX",
            row_storage="compact",
        )
        cls.rows = cls.document.splits[0].blocks[0].rows
        if not isinstance(cls.rows, CompactRows):
            raise AssertionError("performance fixture must remain CompactRows-backed")

    @classmethod
    def _selection(cls, cell_count: int) -> CellSelection:
        if cell_count % _COLUMNS:
            raise ValueError("performance selection must fill complete rows")
        row_count = cell_count // _COLUMNS
        targets = frozenset(
            CellTarget(int(cls.rows._row_ids[_SOURCE_START + row]), lane)
            for row in range(row_count)
            for lane in range(_COLUMNS)
        )
        anchor = CellTarget(int(cls.rows._row_ids[_SOURCE_START]), 0)
        return CellSelection(targets, anchor)

    @staticmethod
    def _row_count(cell_count: int) -> int:
        return cell_count // _COLUMNS

    @staticmethod
    def _read_budget(cell_count: int) -> int:
        # The generous selected-work allowance tolerates several indexed passes
        # over selected rows/cells while still making a whole-chart scan fail by
        # more than an order of magnitude for every tested selection size.
        selected_rows = cell_count // _COLUMNS
        return cell_count + selected_rows * 12 + 64

    @contextmanager
    def _guard_sparse_rows(self, cell_count: int, operation: str):
        original_compact_getitem = CompactRows.__getitem__
        reads = 0
        budget = self._read_budget(cell_count)

        def guarded_getitem(rows, index):
            nonlocal reads
            reads += 1
            if reads > budget:
                self.fail(
                    f"{operation} materialized too many source rows: "
                    f"{reads} reads for {cell_count} selected cells "
                    f"(budget {budget}, chart {_TOTAL_ROWS} rows)"
                )
            return original_compact_getitem(rows, index)

        def forbid_compact_iteration(_rows):
            self.fail(f"{operation} iterated the complete CompactRows table")
            yield None

        def forbid_overlay_iteration(_rows):
            self.fail(f"{operation} iterated the complete OverlayRows table")
            yield None

        with (
            patch.object(CompactRows, "__getitem__", guarded_getitem),
            patch.object(CompactRows, "__iter__", forbid_compact_iteration),
            patch.object(OverlayRows, "__iter__", forbid_overlay_iteration),
        ):
            yield lambda: reads

    def test_copy_scales_with_selection_not_chart(self) -> None:
        for cell_count in _SELECTION_SIZES:
            with self.subTest(cells=cell_count):
                selection = self._selection(cell_count)
                with self._guard_sparse_rows(cell_count, "copy") as read_count:
                    clipboard = copy_selection(self.document, selection)
                self.assertEqual(len(clipboard.cells), cell_count)
                self.assertLess(read_count(), _TOTAL_ROWS // 10)

    def test_cut_scales_with_selection_not_chart(self) -> None:
        for cell_count in _SELECTION_SIZES:
            with self.subTest(cells=cell_count):
                selection = self._selection(cell_count)
                with self._guard_sparse_rows(cell_count, "cut"):
                    clipboard, command = cut_selection(self.document, selection)
                    edited = command.apply(self.document)
                self.assertEqual(len(clipboard.cells), cell_count)
                rows = edited.splits[0].blocks[0].rows
                self.assertIsInstance(rows, OverlayRows)
                self.assertEqual(len(rows.replacements), self._row_count(cell_count))

    def test_paste_scales_with_selection_not_chart(self) -> None:
        for cell_count in _SELECTION_SIZES:
            with self.subTest(cells=cell_count):
                selection = self._selection(cell_count)
                clipboard = copy_selection(self.document, selection)
                anchor = CellTarget(
                    int(self.rows._row_ids[_DESTINATION_START]),
                    0,
                )
                with self._guard_sparse_rows(cell_count, "paste"):
                    command, pasted_selection = paste_clipboard(
                        self.document,
                        clipboard,
                        anchor,
                    )
                    edited = command.apply(self.document)
                self.assertEqual(len(pasted_selection.targets), cell_count)
                rows = edited.splits[0].blocks[0].rows
                self.assertIsInstance(rows, OverlayRows)
                self.assertEqual(len(rows.replacements), self._row_count(cell_count))

    def test_horizontal_flip_scales_with_selection_not_chart(self) -> None:
        self._assert_transform_sparse("horizontal flip", flip_horizontal_selection)

    def test_vertical_flip_scales_with_selection_not_chart(self) -> None:
        self._assert_transform_sparse("vertical flip", flip_vertical_selection)

    def test_mirror_scales_with_selection_not_chart(self) -> None:
        self._assert_transform_sparse("mirror", mirror_selection)

    def _assert_transform_sparse(self, label, transform) -> None:
        for cell_count in _SELECTION_SIZES:
            with self.subTest(operation=label, cells=cell_count):
                selection = self._selection(cell_count)
                with self._guard_sparse_rows(cell_count, label):
                    command, transformed_selection = transform(
                        self.document,
                        selection,
                    )
                    edited = command.apply(self.document)
                self.assertEqual(transformed_selection.targets, selection.targets)
                rows = edited.splits[0].blocks[0].rows
                self.assertIsInstance(rows, OverlayRows)
                self.assertEqual(len(rows.replacements), self._row_count(cell_count))

    def test_erase_scales_with_selection_not_chart(self) -> None:
        for cell_count in _SELECTION_SIZES:
            with self.subTest(cells=cell_count):
                selection = self._selection(cell_count)
                with self._guard_sparse_rows(cell_count, "erase"):
                    edited = set_selection_raw(
                        selection,
                        b"\x00\x00\x00\x00",
                    ).apply(self.document)
                rows = edited.splits[0].blocks[0].rows
                self.assertIsInstance(rows, OverlayRows)
                self.assertEqual(len(rows.replacements), self._row_count(cell_count))

    def test_filtered_replace_scales_with_selection_not_chart(self) -> None:
        for cell_count in _SELECTION_SIZES:
            with self.subTest(cells=cell_count):
                selection = self._selection(cell_count)
                with self._guard_sparse_rows(cell_count, "filtered replace"):
                    command = replace_selection_type(
                        self.document,
                        selection,
                        3,
                        b"\x41\x03\x17\x00",
                    )
                    edited = command.apply(self.document)
                self.assertEqual(len(command.edits), cell_count)
                rows = edited.splits[0].blocks[0].rows
                self.assertIsInstance(rows, OverlayRows)
                self.assertEqual(len(rows.replacements), self._row_count(cell_count))

    def test_bulk_placement_scales_with_selection_not_chart(self) -> None:
        for cell_count in _SELECTION_SIZES:
            with self.subTest(cells=cell_count):
                selection = self._selection(cell_count)
                with self._guard_sparse_rows(cell_count, "bulk placement"):
                    edited = set_selection_raw(
                        selection,
                        b"\x41\x03\x23\x00",
                    ).apply(self.document)
                rows = edited.splits[0].blocks[0].rows
                self.assertIsInstance(rows, OverlayRows)
                self.assertEqual(len(rows.replacements), self._row_count(cell_count))


if __name__ == "__main__":
    unittest.main()
