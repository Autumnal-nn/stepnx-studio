from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from stepnx.authoring import (
        MetadataDraft,
        create_authoring_snapshot,
        load_noteskin_pack,
    )
    from stepnx.codecs.nx20 import parse_bytes
    from stepnx.core.model import NoteCell, NoteRow
    from stepnx.core.profiles import MetadataScope
    from stepnx.gui.audio_transport import AudioTransport
    from stepnx.gui.metadata_dialog import MetadataCollectionDialog
    from stepnx.gui.timeline_widget import TimelineWidget
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""

from tests.fixture_factory import make_large_lightmap, make_normal_nx20


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class QtViewportSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_offscreen_widget_culls_and_renders_large_chart(self) -> None:
        document = parse_bytes(
            make_large_lightmap(), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(900, 640)
            widget.show()
            self.application.processEvents()

            self.assertGreater(widget.verticalScrollBar().maximum(), 1_000_000)
            image = QImage(widget.size(), QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            try:
                widget.render(painter, QPoint())
            finally:
                painter.end()
            self.assertNotEqual(image.pixelColor(10, 10).rgba(), 0)
        finally:
            widget.close()

    def test_audio_transport_accepts_qmediaplayer_integer_signals(self) -> None:
        transport = AudioTransport()
        positions = []
        durations = []
        transport.positionChanged.connect(positions.append)
        transport.durationChanged.connect(durations.append)
        try:
            transport.player.positionChanged.emit(1234)
            transport.player.durationChanged.emit(5678)

            self.assertEqual(positions, [1234])
            self.assertEqual(durations, [5678])
        finally:
            transport.player.stop()
            transport.deleteLater()
            self.application.processEvents()

    def test_brain_dialog_preserves_non_brain_rows_as_read_only(self) -> None:
        dialog = MetadataCollectionDialog(
            (
                MetadataDraft(111, 7, 100),
                MetadataDraft(11, 0x0014000A, 101),
                MetadataDraft(900, 3, 102),
            ),
            "nxa-step5-patched",
            MetadataScope.DIVISION,
            brain_only=True,
        )
        try:
            self.assertEqual(dialog.table.rowCount(), 3)
            self.assertFalse(dialog._is_editable(dialog.drafts()[0]))
            self.assertTrue(dialog._is_editable(dialog.drafts()[1]))
            self.assertFalse(dialog._is_editable(dialog.drafts()[2]))

            dialog.table.selectRow(0)
            dialog._remove()
            self.assertEqual([item.meta_id for item in dialog.drafts()], [111, 11, 900])

            dialog.table.selectRow(1)
            dialog._move(-1)
            self.assertEqual([item.meta_id for item in dialog.drafts()], [111, 11, 900])
        finally:
            dialog.close()

    def test_playback_time_moves_the_following_viewport(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=200), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(500, 300)
            widget.show()
            self.application.processEvents()
            block = widget.snapshot.splits[0].blocks[0]
            row_duration = 60_000.0 / (block.bpm * block.beat_split)

            widget.set_playback_time(
                block.start_time + 100 * row_duration,
                follow=True,
            )

            expected_y = 100 * widget._layout.segments[0].row_height
            self.assertAlmostEqual(
                widget.verticalScrollBar().value(),
                expected_y - widget.viewport().height() * 0.07,
                delta=2,
            )
        finally:
            widget.close()

    def test_blank_tail_keeps_playhead_at_anchor_at_chart_end(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=20), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(500, 300)
            widget.show()
            self.application.processEvents()
            segment = widget._layout.segments[0]
            block = segment.block
            row_duration = 60_000.0 / (block.bpm * block.beat_split)

            widget.set_playback_time(
                block.start_time + block.row_count * row_duration,
                follow=True,
            )

            anchor = widget.viewport().height() * 0.07
            self.assertAlmostEqual(
                segment.bottom - widget.verticalScrollBar().value(),
                anchor,
                delta=2,
            )
            self.assertGreater(
                widget.verticalScrollBar().maximum(),
                round(segment.bottom - widget.viewport().height()),
            )
            self.assertIsNone(
                widget._layout.row_at_y(segment.bottom + widget.viewport().height() / 2)
            )
        finally:
            widget.close()

    def test_collapsed_long_draws_head_as_top_terminal_in_editor(self) -> None:
        document = parse_bytes(
            make_normal_nx20(), source="short-long.NX", row_storage="rich"
        )
        split = document.splits[0]
        block = split.blocks[0]
        row = block.rows[0]
        cells = list(row.cells)
        cells[0] = replace(cells[0], raw=bytes((0x07, 0x03, 0, 0)))
        cells[3] = replace(cells[3], raw=bytes((0x0F, 0x03, 0, 0)))
        row = replace(row, cells=tuple(cells))
        block = replace(block, rows=(row,) + tuple(block.rows[1:]))
        document = replace(document, splits=(replace(split, blocks=(block,)),))
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(640, 360)
            visible = widget._layout.visible_segments(
                0.0, float(widget.viewport().height()), overscan_rows=2
            )[0]
            image = QImage(widget.viewport().size(), QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            order = []
            original = widget._draw_note

            def record(painter_arg, lane, y, row_height, raw):
                order.append(raw[0] & 0x0F)
                return original(painter_arg, lane, y, row_height, raw)

            try:
                with patch.object(widget, "_draw_note", side_effect=record):
                    widget._draw_segment(painter, visible)
            finally:
                painter.end()
            self.assertIn(0x0F, order)
            self.assertEqual(order[-1], 0x07)
            self.assertLess(order.index(0x0F), order.index(0x07))
        finally:
            widget.close()


    def test_dense_playback_bodies_coalesce_into_one_raster_shaft(self) -> None:
        document = parse_bytes(
            make_normal_nx20(), source="dense-body.NX", row_storage="rich"
        )
        split = document.splits[0]
        block = split.blocks[0]
        rows = list(block.rows)
        body_count = 2
        self.assertGreaterEqual(len(rows), body_count)
        next_id = document.next_stable_id
        for index in range(body_count):
            row = rows[index]
            if hasattr(row, "cells"):
                cells = list(row.cells)
                cells[0] = replace(cells[0], raw=bytes((0x0B, 0x03, 0, 0)))
            else:
                cells = []
                for lane in range(int(document.columns.value)):
                    raw = bytes((0x0B, 0x03, 0, 0)) if lane == 0 else bytes(4)
                    cells.append(NoteCell(next_id, raw, None))
                    next_id += 1
            rows[index] = NoteRow(row.stable_id, tuple(cells), None)
        block = replace(block, rows=tuple(rows))
        document = replace(
            document,
            splits=(replace(split, blocks=(block,)),),
            next_stable_id=next_id,
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(640, 900)
            widget.set_playback_active(True)
            visible = widget._layout.visible_segments(
                0.0, float(widget.viewport().height()), overscan_rows=2
            )[0]
            image = QImage(widget.viewport().size(), QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            spans = []
            notes = []
            original_span = widget._draw_hold_body_span
            original_note = widget._draw_note

            def record_span(painter_arg, lane, y, span_height, raw):
                spans.append((lane, y, span_height, raw))
                return original_span(painter_arg, lane, y, span_height, raw)

            def record_note(painter_arg, lane, y, row_height, raw):
                notes.append(raw[0] & 0x0F)
                return original_note(painter_arg, lane, y, row_height, raw)

            try:
                with patch.object(widget, "_draw_hold_body_span", side_effect=record_span), patch.object(
                    widget, "_draw_note", side_effect=record_note
                ):
                    widget._draw_segment(painter, visible)
            finally:
                painter.end()
            self.assertEqual(len(spans), 1)
            self.assertEqual(spans[0][0], 0)
            self.assertNotIn(0x0B, notes)

            widget.set_playback_active(False)
            visible = widget._layout.visible_segments(
                0.0, float(widget.viewport().height()), overscan_rows=2
            )[0]
            image = QImage(widget.viewport().size(), QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            paused_notes = []
            try:
                def record_paused(painter_arg, lane, y, row_height, raw):
                    paused_notes.append(raw[0] & 0x0F)
                    return original_note(painter_arg, lane, y, row_height, raw)

                with patch.object(widget, "_draw_note", side_effect=record_paused):
                    widget._draw_segment(painter, visible)
            finally:
                painter.end()
            self.assertEqual(paused_notes.count(0x0B), body_count)
        finally:
            widget.close()

    def test_hold_terminals_do_not_bake_shaft_into_head_artwork(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=4), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            with tempfile.TemporaryDirectory() as temporary:
                bank = Path(temporary) / "00"
                bank.mkdir()
                atlas = QImage(480, 288, QImage.Format.Format_ARGB32)
                atlas.fill(Qt.GlobalColor.transparent)
                atlas_painter = QPainter(atlas)
                try:
                    atlas_painter.fillRect(QRectF(0, 0, 96, 8), QColor("#00ff00"))
                    atlas_painter.fillRect(
                        QRectF(0, 96 + 20, 96, 31), QColor("#0000ff")
                    )
                finally:
                    atlas_painter.end()
                for frame in range(6):
                    self.assertTrue(atlas.save(str(bank / f"{frame}.png")))
                widget.set_noteskin_pack(load_noteskin_pack(temporary))
                canvas = QImage(96, 96, QImage.Format.Format_ARGB32)
                canvas.fill(Qt.GlobalColor.transparent)
                painter = QPainter(canvas)
                try:
                    self.assertTrue(
                        widget._draw_noteskin_note(
                            painter,
                            0,
                            0.0,
                            24.0,
                            bytes((0x07, 0, 0, 0)),
                            QRectF(0, 0, 96, 96),
                        )
                    )
                finally:
                    painter.end()
                self.assertEqual(canvas.pixelColor(48, 35), QColor("#0000ff"))
                self.assertEqual(canvas.pixelColor(48, 70).alpha(), 0)
        finally:
            widget.close()

    def test_low_projection_keeps_tail_and_uses_head_last_order_in_editor(self) -> None:
        document = parse_bytes(
            make_normal_nx20(), source="collapsed.NX", row_storage="rich"
        )
        split = document.splits[0]
        block = split.blocks[0]
        rows = list(block.rows)
        next_id = document.next_stable_id
        while len(rows) < 3:
            row_id = next_id
            next_id += 1
            cells = []
            for lane in range(int(document.columns.value)):
                cells.append(NoteCell(next_id, bytes(4), None))
                next_id += 1
            rows.append(NoteRow(row_id, tuple(cells), None))
        for index, note_type in enumerate((0x07, 0x0B, 0x0F)):
            row = rows[index]
            if hasattr(row, "cells"):
                cells = list(row.cells)
                cells[0] = replace(cells[0], raw=bytes((note_type, 0x03, 0, 0)))
            else:
                cells = []
                for lane in range(int(document.columns.value)):
                    raw = bytes((note_type, 0x03, 0, 0)) if lane == 0 else bytes(4)
                    cells.append(NoteCell(next_id, raw, None))
                    next_id += 1
            rows[index] = NoteRow(row.stable_id, tuple(cells), None)
        block = replace(block, rows=tuple(rows), scroll=block.scroll.with_value(0.1))
        document = replace(
            document,
            splits=(replace(split, blocks=(block,)),),
            next_stable_id=next_id,
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(640, 900)
            widget.set_playback_active(True)
            visible = widget._layout.visible_segments(
                0.0, float(widget.viewport().height()), overscan_rows=2
            )[0]
            image = QImage(widget.viewport().size(), QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            notes = []
            spans = []
            original_note = widget._draw_note
            original_span = widget._draw_hold_body_span
            try:
                def record_note(painter_arg, lane, y, row_height, raw):
                    notes.append(raw[0] & 0x0F)
                    return original_note(painter_arg, lane, y, row_height, raw)

                def record_span(painter_arg, lane, y, span_height, raw):
                    spans.append((lane, y, span_height))
                    return original_span(painter_arg, lane, y, span_height, raw)

                with patch.object(widget, "_draw_note", side_effect=record_note), patch.object(
                    widget, "_draw_hold_body_span", side_effect=record_span
                ):
                    widget._draw_segment(painter, visible)
            finally:
                painter.end()
            self.assertIn(0x07, notes)
            self.assertIn(0x0F, notes)
            self.assertEqual(notes[-1], 0x07)
            self.assertLess(notes.index(0x0F), notes.index(0x07))
        finally:
            widget.close()

    def test_playback_geometry_is_restored_on_pause(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=20), source="LM.NX", row_storage="compact"
        )
        snapshot = create_authoring_snapshot(document)
        source_split = snapshot.splits[0]
        playback_block = replace(
            source_split.blocks[0], scroll=0.125, beat_split=8
        )
        snapshot = replace(
            snapshot,
            splits=(replace(source_split, blocks=(playback_block,)),),
        )
        widget = TimelineWidget(snapshot)
        try:
            authoring_height = widget._layout.segments[0].row_height
            widget.set_playback_active(True)
            playback_height = widget._layout.segments[0].row_height
            widget.set_playback_active(False)

            self.assertEqual(playback_height, authoring_height)
            self.assertEqual(widget._layout.segments[0].row_height, authoring_height)
        finally:
            widget.close()

    def test_play_pause_preserves_the_exact_viewport_position(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=80), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(420, 300)
            widget.show()
            self.application.processEvents()
            widget._sync_scrollbars()
            self.assertGreaterEqual(widget.horizontalScrollBar().maximum(), 12)
            widget.verticalScrollBar().setValue(700)
            widget.horizontalScrollBar().setValue(12)

            widget.set_playback_active(True)
            self.assertEqual(widget.verticalScrollBar().value(), 700)
            self.assertEqual(widget.horizontalScrollBar().value(), 12)
            widget.set_playback_active(False)

            self.assertEqual(widget.verticalScrollBar().value(), 700)
            self.assertEqual(widget.horizontalScrollBar().value(), 12)
        finally:
            widget.close()

    def test_play_pause_preserves_playhead_viewport_anchor_across_projection(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=80), source="LM.NX", row_storage="compact"
        )
        snapshot = create_authoring_snapshot(document)
        source_split = snapshot.splits[0]
        block = replace(source_split.blocks[0], scroll=0.5, beat_split=4)
        snapshot = replace(
            snapshot,
            splits=(replace(source_split, blocks=(block,)),),
        )
        widget = TimelineWidget(snapshot)
        try:
            widget.resize(420, 300)
            row_duration = 60_000.0 / (block.bpm * block.beat_split)
            widget.set_playback_time(block.start_time + 30 * row_duration)
            widget.verticalScrollBar().setValue(round(widget._playback_y - 80))
            before = widget._playback_y - widget.verticalScrollBar().value()

            widget.set_playback_active(True)
            during = widget._playback_y - widget.verticalScrollBar().value()
            widget.set_playback_active(False)
            after = widget._playback_y - widget.verticalScrollBar().value()

            self.assertAlmostEqual(during, before, delta=1)
            self.assertAlmostEqual(after, before, delta=1)
        finally:
            widget.close()

    def test_cell_click_emits_stable_row_and_lane(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=4), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        received = []
        widget.noteEditRequested.connect(
            lambda row_id, lane: received.append((row_id, lane))
        )
        try:
            widget.resize(500, 300)
            widget.show()
            self.application.processEvents()
            QTest.mouseClick(
                widget.viewport(),
                Qt.MouseButton.LeftButton,
                pos=QPoint(92 + 48 + 5, 5),
            )
            self.assertEqual(
                received, [(document.splits[0].blocks[0].rows[0].stable_id, 1)]
            )
        finally:
            widget.close()

    def test_mouse_wheel_scrolls_by_half_the_active_split_beat(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=100), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(500, 300)
            widget.show()
            self.application.processEvents()
            scrollbar = widget.verticalScrollBar()
            scrollbar.setValue(200)
            before = scrollbar.value()
            segment = widget._layout.segment_at_y(before + 120)
            self.assertIsNotNone(segment)
            expected_distance = round(
                0.5 * segment.block.beat_split * segment.row_height
            )
            self.assertGreater(expected_distance, 0)
            event = QWheelEvent(
                QPointF(200, 120),
                QPointF(200, 120),
                QPoint(),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            )

            widget.wheelEvent(event)

            self.assertEqual(
                scrollbar.value(),
                before - expected_distance,
            )
        finally:
            widget.close()

    def test_shift_drag_selection_uses_stable_rows(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=20), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(500, 400)
            widget.show()
            self.application.processEvents()
            row_height = widget._layout.segments[0].row_height
            QTest.mouseClick(
                widget.viewport(),
                Qt.MouseButton.LeftButton,
                pos=QPoint(92 + 5, 5),
            )
            QTest.mouseClick(
                widget.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.ShiftModifier,
                pos=QPoint(92 + 2 * 48 + 5, round(2 * row_height + 1)),
            )
            self.assertEqual(len(widget.selection.targets), 9)
        finally:
            widget.close()

    def test_click_is_snapped_by_active_block_beat_split(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=20), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        received = []
        widget.noteEditRequested.connect(
            lambda row_id, lane: received.append((row_id, lane))
        )
        try:
            widget.set_snap_beats(1.0)
            widget.resize(500, 400)
            widget.show()
            self.application.processEvents()
            row_height = widget._layout.segments[0].row_height
            QTest.mouseClick(
                widget.viewport(),
                Qt.MouseButton.LeftButton,
                pos=QPoint(92 + 5, round(3 * row_height + 1)),
            )
            expected = document.splits[0].blocks[0].rows[4].stable_id
            self.assertEqual(received, [(expected, 0)])
        finally:
            widget.close()

    def test_viewport_play_start_uses_preceding_beat_at_playhead(self) -> None:
        document = parse_bytes(
            make_large_lightmap(rows=100), source="LM.NX", row_storage="compact"
        )
        widget = TimelineWidget(create_authoring_snapshot(document))
        try:
            widget.resize(500, 300)
            widget.show()
            self.application.processEvents()
            row_height = widget._layout.segments[0].row_height
            playhead_offset = widget.viewport().height() * 0.07
            widget.verticalScrollBar().setValue(
                round(5 * row_height - playhead_offset + 1)
            )

            # 7% of a 300 px viewport adds 21 px, placing the playhead in row
            # five. Beat Split is two, so playback seeks to row four.
            self.assertAlmostEqual(widget.chart_time_at_viewport_beat(0.07), 1000.0)
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
