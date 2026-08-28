from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication

    from stepnx.authoring.snapshot import create_authoring_snapshot
    from stepnx.authoring.structure import StructureTarget, insert_empty_split_after
    from stepnx.codecs.nx20 import parse_bytes, serialize
    from stepnx.core.commands import SetNoteAt
    from stepnx.core.model import EmptyRow, NoteRow
    from stepnx.core.validation import validate
    from stepnx.gui.phase10_timeline import Phase10TimelineWidget
    from stepnx.gui.phase11_fast_notes import _FastSetNoteAt
    from stepnx.gui.phase11_feedback import (
        _boundary_hit,
        _minimum_reference_rows,
        _resize_split_boundary_document,
        _snapshot_with_updated_rows,
    )
    from tests.fixture_factory import make_normal_nx20
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class Phase11FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _two_split_document(self):
        document = parse_bytes(make_normal_nx20(), row_storage="rich")
        upper = document.splits[0]
        reference = upper.blocks[0]
        command = insert_empty_split_after(
            document,
            StructureTarget(upper.stable_id, reference.stable_id),
        )
        document = command.apply(document)
        return document, upper.stable_id, reference.stable_id

    def test_indexed_note_edit_is_byte_equivalent_to_core_command(self) -> None:
        for storage in ("rich", "compact"):
            source = parse_bytes(make_normal_nx20(), row_storage=storage)
            block = source.splits[0].blocks[0]
            for row in block.rows:
                with self.subTest(storage=storage, row=row.stable_id):
                    core = SetNoteAt(
                        row.stable_id, 0, b"\x03\x03\x09\x00"
                    ).apply(source)
                    fast = _FastSetNoteAt(
                        row.stable_id, 0, b"\x03\x03\x09\x00"
                    ).apply(source)
                    self.assertEqual(serialize(fast), serialize(core))
                    self.assertEqual(fast.next_stable_id, core.next_stable_id)

    def test_fast_note_readd_preserves_compact_cell_stable_ids(self) -> None:
        source = parse_bytes(make_normal_nx20(), row_storage="compact")
        block = source.splits[0].blocks[0]
        row = block.rows[0]
        row_id = row.stable_id
        columns = int(source.columns.value)
        original_cell_ids = tuple(cell.stable_id for cell in row.cells)

        edited = source
        for lane in range(columns):
            edited = _FastSetNoteAt(row_id, lane, b"\x00\x00\x00\x00").apply(edited)

        cleared = edited.splits[0].blocks[0].rows[0]
        self.assertIsInstance(cleared, EmptyRow)

        raw = b"\x03\x03\x09\x00"
        edited = _FastSetNoteAt(row_id, 0, raw).apply(edited)
        restored = edited.splits[0].blocks[0].rows[0]
        self.assertIsInstance(restored, NoteRow)
        self.assertEqual(
            tuple(cell.stable_id for cell in restored.cells),
            original_cell_ids,
        )
        self.assertEqual(
            tuple(cell.raw for cell in restored.cells),
            (raw,) + (b"\x00\x00\x00\x00",) * (columns - 1),
        )
        self.assertFalse(validate(edited).errors)
        serialize(edited)

    def test_fast_snapshot_patch_replaces_only_changed_block_rows(self) -> None:
        document = parse_bytes(make_normal_nx20(), row_storage="rich")
        snapshot = create_authoring_snapshot(document)
        block = document.splits[0].blocks[0]
        row = block.rows[0]
        updated = SetNoteAt(row.stable_id, 0, b"\x03\x03\x09\x00").apply(document)

        patched = _snapshot_with_updated_rows(snapshot, updated, block.stable_id)
        updated_block = updated.splits[0].blocks[0]
        self.assertEqual(patched.splits[0].blocks[0].rows, updated_block.rows)
        self.assertEqual(patched.active_blocks, snapshot.active_blocks)
        self.assertEqual(patched.diagnostics, snapshot.diagnostics)

    def test_boundary_hit_uses_real_layout_geometry_without_blocking_mouse_input(self) -> None:
        document, split_id, _block_id = self._two_split_document()
        widget = Phase10TimelineWidget(create_authoring_snapshot(document))

        class Event:
            def __init__(self, x: float, y: float) -> None:
                self._position = QPointF(x, y)

            def position(self):
                return self._position

        try:
            layout = widget._layout
            segment = layout.segments[0]
            geometry = layout.geometry
            x_scroll = widget.horizontalScrollBar().value()
            y_scroll = widget.verticalScrollBar().value()

            inside = Event(
                geometry.ruler_width + geometry.lane_width / 2 - x_scroll,
                segment.bottom - y_scroll,
            )
            hit = _boundary_hit(widget, inside)
            self.assertIsNotNone(hit)
            self.assertEqual(hit[0].split_id, split_id)

            gutter = Event(
                layout.chart_width + 10 - x_scroll,
                segment.bottom - y_scroll,
            )
            self.assertIsNone(_boundary_hit(widget, gutter))
        finally:
            widget.deleteLater()

    def test_boundary_shrink_is_clamped_after_last_nonempty_row(self) -> None:
        document, split_id, block_id = self._two_split_document()
        minimum = _minimum_reference_rows(document, split_id, block_id)
        self.assertGreaterEqual(minimum, 1)

        resized, actual = _resize_split_boundary_document(
            document, split_id, block_id, 0
        )
        self.assertEqual(actual, minimum)
        self.assertEqual(len(resized.splits[0].blocks[0].rows), minimum)

    def test_boundary_growth_shifts_lower_split_start_time(self) -> None:
        document, split_id, block_id = self._two_split_document()
        upper = document.splits[0].blocks[0]
        lower_before = float(document.splits[1].blocks[0].start_time.value)
        requested = len(upper.rows) + 2

        resized, actual = _resize_split_boundary_document(
            document, split_id, block_id, requested
        )
        self.assertEqual(actual, requested)
        self.assertEqual(len(resized.splits[0].blocks[0].rows), requested)

        expected_delta = 2 * 60_000.0 / (
            float(upper.bpm.value) * int(upper.beat_split.value)
        )
        lower_after = float(resized.splits[1].blocks[0].start_time.value)
        self.assertAlmostEqual(lower_after, lower_before + expected_delta, places=4)


if __name__ == "__main__":
    unittest.main()
