from __future__ import annotations

import os
import unittest
from dataclasses import replace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    from stepnx.authoring.lightmap import LightmapEdit, SetLightmapCells
    from stepnx.authoring.selection import CellSelection, CellTarget
    from stepnx.authoring.snapshot import create_authoring_snapshot
    from stepnx.codecs.nx20 import parse_bytes
    from stepnx.core.commands import NoteEdit, SetNotesAt
    from stepnx.core.model import CompactRows, EmptyRow, LightmapRow, OverlayRows, PackedNoteRow
    from stepnx.core.scalars import RawF32, RawU8, RawU32
    from stepnx.gui.selection_lightmap_workflow import (
        GridClipboard,
        _draw_three_channel_lightmap_row,
        _lightmap_toggle_command,
        _selection_between,
        copy_visible_selection,
        erase_visible_selection,
        paste_visible_clipboard,
        transform_visible_selection,
    )
    from stepnx.gui.timeline_widget import TimelineWidget
    from tests.fixture_factory import make_implicit_lightmap, make_large_lightmap, make_large_playable
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


def _raw(row, lane: int) -> bytes:
    if isinstance(row, EmptyRow):
        return b"\x00\x00\x00\x00"
    if isinstance(row, PackedNoteRow):
        return row.cell(lane).raw
    return row.cells[lane].raw


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class SelectionAndLightmapWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _twelve_row_document(self):
        document = parse_bytes(make_large_playable(rows=4, columns=5), row_storage="compact")
        first_split = document.splits[0]
        first_block = first_split.blocks[0]
        first_ids = tuple(int(value) for value in first_block.rows._row_ids)

        next_id = document.next_stable_id
        second_rows = tuple(
            EmptyRow(next_id + index, b"\x80\x00\x00\x00", None)
            for index in range(8)
        )
        second_ids = tuple(row.stable_id for row in second_rows)
        next_id += len(second_rows)
        second_block = replace(
            first_block,
            stable_id=next_id,
            start_time=RawF32.from_value(2000.0),
            beat_split=RawU8.from_value(32),
            row_count=RawU32.from_value(8),
            rows=second_rows,
            span=None,
        )
        next_id += 1
        second_split = replace(
            first_split,
            stable_id=next_id,
            blocks=(second_block,),
            block_count=RawU32.from_value(1),
            span=None,
        )
        next_id += 1
        document = replace(
            document,
            splits=(first_split, second_split),
            split_count=RawU32.from_value(2),
            next_stable_id=next_id,
        )

        all_ids = first_ids + second_ids
        document = SetNotesAt(
            tuple(
                NoteEdit(row_id, 0, bytes((0x43, 0x03, ordinal + 1, 0x00)))
                for ordinal, row_id in enumerate(all_ids)
            )
        ).apply(document)
        return document, all_ids

    def _twelve_row_widget(self):
        document, row_ids = self._twelve_row_document()
        widget = TimelineWidget(create_authoring_snapshot(document))
        return document, row_ids, widget

    def test_lightmap_cell_command_preserves_uneditable_fourth_byte(self) -> None:
        document = parse_bytes(make_implicit_lightmap(), row_storage="compact")
        row_id = int(document.splits[0].blocks[0].rows._row_ids[0])
        updated = SetLightmapCells((LightmapEdit(row_id, 1, 0),)).apply(document)
        row = updated.splits[0].blocks[0].rows[0]

        self.assertIsInstance(row, LightmapRow)
        self.assertEqual(row.raw_channels, b"\x01\x00\x03\x04")

    def test_large_lightmap_edit_stays_sparse_without_row_table_iteration(self) -> None:
        document = parse_bytes(make_large_lightmap(rows=20_000), row_storage="compact")
        rows = document.splits[0].blocks[0].rows
        row_id = int(rows._row_ids[15_000])

        with mock.patch.object(
            CompactRows,
            "__iter__",
            side_effect=AssertionError("Lightmap edit materialized the row table"),
        ):
            updated = SetLightmapCells((LightmapEdit(row_id, 2, 1),)).apply(document)

        edited_rows = updated.splits[0].blocks[0].rows
        self.assertIsInstance(edited_rows, OverlayRows)
        self.assertEqual(len(edited_rows.replacements), 1)
        self.assertEqual(edited_rows[15_000].raw_channels, b"\x01\x00\x01\x00")

    def test_cross_block_copy_counts_four_plus_eight_rows_not_ticks(self) -> None:
        _document, row_ids, widget = self._twelve_row_widget()
        selection = CellSelection(
            frozenset(CellTarget(row_id, 0) for row_id in row_ids),
            CellTarget(row_ids[0], 0),
        )
        widget.set_selection(selection)

        clipboard = copy_visible_selection(widget)

        self.assertEqual(clipboard.kind, "notes")
        self.assertEqual(clipboard.width, 1)
        self.assertEqual(clipboard.height, 12)
        self.assertEqual(len(clipboard.cells), 12)
        self.assertEqual(int(widget._layout.segments[0].block.beat_split), 4)
        self.assertEqual(int(widget._layout.segments[1].block.beat_split), 32)

    def test_shift_rectangle_can_span_the_complete_active_route(self) -> None:
        _document, row_ids, widget = self._twelve_row_widget()
        widget.set_selection(
            CellSelection(
                frozenset((CellTarget(row_ids[0], 1),)),
                CellTarget(row_ids[0], 1),
            )
        )
        selection = _selection_between(widget, CellTarget(row_ids[-1], 2))

        self.assertEqual(len({target.row_id for target in selection.targets}), 12)
        self.assertEqual(len(selection.targets), 24)
        self.assertEqual({target.lane for target in selection.targets}, {1, 2})

    def test_paste_continues_from_last_row_of_one_split_into_the_next(self) -> None:
        _document, row_ids, widget = self._twelve_row_widget()
        clipboard = GridClipboard(
            "notes",
            1,
            3,
            (
                (0, 0, b"\x43\x03\x51\x00"),
                (1, 0, b"\x43\x03\x52\x00"),
                (2, 0, b"\x43\x03\x53\x00"),
            ),
        )
        anchor = CellTarget(row_ids[3], 0)

        command, selection = paste_visible_clipboard(widget, clipboard, anchor)
        self.assertEqual(
            {edit.row_id for edit in command.edits},
            {row_ids[3], row_ids[4], row_ids[5]},
        )
        self.assertEqual(
            {target.row_id for target in selection.targets},
            {row_ids[3], row_ids[4], row_ids[5]},
        )

    def test_vertical_flip_reverses_encoded_rows_across_split_boundary(self) -> None:
        document, row_ids, widget = self._twelve_row_widget()
        widget.set_selection(
            CellSelection(
                frozenset(CellTarget(row_id, 0) for row_id in row_ids),
                CellTarget(row_ids[0], 0),
            )
        )

        command, _selection = transform_visible_selection(widget, "vertical")
        updated = command.apply(document)
        observed = []
        for split in updated.splits:
            block = split.blocks[0]
            observed.extend(_raw(row, 0)[2] for row in block.rows)

        self.assertEqual(observed, list(range(12, 0, -1)))

    def test_lightmap_toggle_copy_delete_and_paste_touch_only_three_channels(self) -> None:
        document = parse_bytes(make_large_lightmap(rows=4), row_storage="compact")
        widget = TimelineWidget(create_authoring_snapshot(document))
        rows = widget._layout.segments[0].block.rows
        row_ids = tuple(int(value) for value in rows._row_ids)
        widget.set_selection(
            CellSelection(
                frozenset(
                    (
                        CellTarget(row_ids[0], 0),
                        CellTarget(row_ids[0], 1),
                    )
                ),
                CellTarget(row_ids[0], 0),
            )
        )

        toggled = _lightmap_toggle_command(widget).apply(document)
        self.assertEqual(
            toggled.splits[0].blocks[0].rows[0].raw_channels,
            b"\x00\x01\x00\x00",
        )

        clipboard = copy_visible_selection(widget)
        self.assertEqual(clipboard.kind, "lightmap")
        self.assertEqual([raw for _r, _l, raw in clipboard.cells], [b"\x01", b"\x00"])

        erased = erase_visible_selection(widget).apply(document)
        self.assertEqual(
            erased.splits[0].blocks[0].rows[0].raw_channels,
            b"\x00\x00\x00\x00",
        )

        destination = CellTarget(row_ids[2], 1)
        paste, pasted_selection = paste_visible_clipboard(widget, clipboard, destination)
        pasted = paste.apply(document)
        self.assertEqual(
            pasted.splits[0].blocks[0].rows[2].raw_channels,
            b"\x01\x01\x00\x00",
        )
        self.assertEqual(
            pasted_selection.targets,
            frozenset((CellTarget(row_ids[2], 1), CellTarget(row_ids[2], 2))),
        )

    def test_lightmap_and_note_clipboards_cannot_cross_document_kinds(self) -> None:
        document = parse_bytes(make_large_lightmap(rows=2), row_storage="compact")
        widget = TimelineWidget(create_authoring_snapshot(document))
        row_id = int(widget._layout.segments[0].block.rows._row_ids[0])
        clipboard = GridClipboard("notes", 1, 1, ((0, 0, b"\x43\x03\x00\x00"),))

        with self.assertRaisesRegex(ValueError, "not interchangeable"):
            paste_visible_clipboard(widget, clipboard, CellTarget(row_id, 0))

    def test_lightmap_renderer_uses_exactly_three_lane_widths_and_ignores_byte_four(self) -> None:
        class Geometry:
            ruler_width = 80.0
            lane_width = 44.0

        class Widget:
            _geometry = Geometry()

        class Painter:
            def __init__(self):
                self.rects = []

            def fillRect(self, rect, color):
                self.rects.append((rect, color))

        painter = Painter()
        _draw_three_channel_lightmap_row(
            Widget(), painter, b"\x01\x01\x01\xFF", 10.0, 24.0
        )

        self.assertEqual(len(painter.rects), 3)
        self.assertEqual([round(rect.x()) for rect, _color in painter.rects], [82, 126, 170])
        self.assertEqual([round(rect.width()) for rect, _color in painter.rects], [40, 40, 40])


if __name__ == "__main__":
    unittest.main()
