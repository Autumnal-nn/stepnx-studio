from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QImage, QPainter, QWheelEvent
    from PySide6.QtWidgets import QApplication, QMainWindow, QSpinBox, QTabWidget, QWidget

    from stepnx.authoring.editor_controller import EditorController, InteractionTool
    from stepnx.authoring.tools import NoteFunction, NoteVisibility
    from stepnx.codecs.nx20 import parse_bytes, serialize
    from stepnx.core.commands import CommandStack, InsertBlock, SetNoteAt
    from stepnx.gui.stepedit_experimental_dialog import (
        StepEditExperimentalDialog,
        install_stepedit_experimental,
    )
    from stepnx.gui.stepedit_experimental_viewport import StepEditExperimentalViewport
    from stepnx.gui.stepedit_visual_style import (
        ATLAS_TILE_PIXELS, EDITOR_ZOOM_PRESETS,
        NOTE_BACKGROUND, INDICATOR_BACKGROUND, SELECTION_BACKGROUND,
        VERTICAL_GRID, MINOR_GRID, MAJOR_GRID, LANE_BOUNDARY,
        StepEditAtlasArtist, split_background, scaled_editor_geometry,
        wheel_notch_pixels,
    )
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""

from tests.fixture_factory import make_large_playable, make_normal_nx20


_RAW = b"\x43\x03\x00\x00"


@unittest.skipIf(QApplication is None, f"Qt unavailable: {QT_UNAVAILABLE}")
class ExperimentalQtViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.doc = parse_bytes(make_large_playable(rows=64), row_storage="compact")
        self.stack = CommandStack(self.doc)
        self.controller = EditorController(self.stack)
        self.widget = StepEditExperimentalViewport(
            self.controller, tap_raw=lambda: _RAW
        )
        self.widget.resize(720, 580)
        self.widget.show()
        self.application.processEvents()
        self.split = self.doc.splits[0]
        self.block = self.split.blocks[0]
        self.x = int(self.widget.layout_model.x_for_lane(1))
        self.y = int(self.widget.layout_model.y_for_row(self.split.stable_id, 2, center=True))

    def tearDown(self) -> None:
        self.widget.close()
        self.application.processEvents()

    def test_toggle_click_places_and_removes_exact_tap(self) -> None:
        target = QPoint(self.x, self.y)
        original = serialize(self.doc)
        QTest.mouseClick(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=target)
        self.assertEqual(
            self.controller.document.splits[0].blocks[0].rows[2].cells[1].raw,
            _RAW,
        )
        QTest.mouseClick(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=target)
        self.assertEqual(serialize(self.controller.document), original)
        self.assertTrue(self.stack.can_undo)

    def test_paint_stroke_commits_once_and_undoes_all_cells(self) -> None:
        self.widget.set_tool(InteractionTool.ADD)
        p1 = QPoint(self.x, self.y)
        y2 = int(self.widget.layout_model.y_for_row(self.split.stable_id, 4, center=True))
        p2 = QPoint(self.x, y2)
        original = serialize(self.doc)
        QTest.mousePress(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=p1)
        QTest.mouseMove(self.widget.viewport(), p2)
        self.assertEqual(serialize(self.stack.current), original)
        QTest.mouseRelease(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=p2)
        self.assertNotEqual(serialize(self.stack.current), original)
        self.assertEqual(self.controller.document.splits[0].blocks[0].rows[2].cells[1].raw, _RAW)
        self.assertEqual(self.controller.document.splits[0].blocks[0].rows[4].cells[1].raw, _RAW)
        self.widget.undo()
        self.assertEqual(serialize(self.stack.current), original)
        self.assertFalse(self.stack.can_undo)

    def test_fast_paint_does_not_skip_intermediate_rows(self) -> None:
        self.widget.set_tool(InteractionTool.ADD)
        p0 = QPoint(self.x, self.y)
        p1 = QPoint(
            self.x, int(self.widget.layout_model.y_for_row(self.split.stable_id, 6, center=True))
        )
        QTest.mousePress(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=p0)
        QTest.mouseMove(self.widget.viewport(), p1)
        QTest.mouseRelease(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=p1)
        block = self.controller.document.splits[0].blocks[0]
        self.assertEqual(
            [_RAW for _ in range(5)],
            [block.rows[row].cells[1].raw for row in range(2, 7)],
        )

    def test_crossing_hold_cancels_entire_paint_stroke(self) -> None:
        row = self.doc.splits[0].blocks[0].rows[4]
        self.stack.execute(SetNoteAt(row.stable_id, 1, b"\x57\x03\x00\x00"))
        self.controller.sync_external_change()
        self.widget._rebuild_layout()
        self.widget.set_tool(InteractionTool.ADD)
        before = serialize(self.stack.current)
        QTest.mousePress(
            self.widget.viewport(), Qt.MouseButton.LeftButton,
            pos=QPoint(self.x, self.y),
        )
        endpoint = QPoint(
            self.x, int(self.widget.layout_model.y_for_row(self.split.stable_id, 6, center=True))
        )
        QTest.mouseMove(self.widget.viewport(), endpoint)
        QTest.mouseRelease(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=endpoint)
        self.assertEqual(serialize(self.stack.current), before)

    def test_toggle_does_not_erase_unknown_type_zero_payload(self) -> None:
        row = self.doc.splits[0].blocks[0].rows[2]
        self.stack.execute(SetNoteAt(row.stable_id, 1, b"\x00\x02\x03\x04"))
        self.controller.sync_external_change()
        self.widget._rebuild_layout()
        before = serialize(self.stack.current)
        QTest.mouseClick(
            self.widget.viewport(), Qt.MouseButton.LeftButton,
            pos=QPoint(self.x, self.y),
        )
        self.assertEqual(serialize(self.stack.current), before)

    def test_toggle_drag_creates_complete_hold_and_body_click_erases_it(self) -> None:
        source = serialize(self.stack.current)
        start = QPoint(self.x, self.y)
        mid = QPoint(
            self.x, int(self.widget.layout_model.y_for_row(self.split.stable_id, 4, center=True)),
        )
        stop = QPoint(
            self.x, int(self.widget.layout_model.y_for_row(self.split.stable_id, 6, center=True)),
        )
        QTest.mousePress(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.widget.viewport(), stop)
        self.assertEqual(serialize(self.stack.current), source)
        QTest.mouseRelease(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=stop)
        block = self.controller.document.splits[0].blocks[0]
        self.assertEqual(
            [block.rows[index].cells[1].raw[0] & 0x0F for index in range(2, 7)],
            [7, 0xB, 0xB, 0xB, 0xF],
        )
        self.assertEqual(self.controller._stack.can_undo, True)
        QTest.mouseClick(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=mid)
        self.assertEqual(serialize(self.controller.document), source)
        self.widget.undo()
        self.assertNotEqual(serialize(self.controller.document), source)
        self.widget.undo()
        self.assertEqual(serialize(self.controller.document), source)

    def test_toggle_hold_drag_over_existing_cell_is_non_destructive(self) -> None:
        row = self.doc.splits[0].blocks[0].rows[4]
        self.stack.execute(SetNoteAt(row.stable_id, 1, _RAW))
        self.controller.sync_external_change()
        self.widget._rebuild_layout()
        before = serialize(self.stack.current)
        start = QPoint(self.x, self.y)
        stop = QPoint(
            self.x, int(self.widget.layout_model.y_for_row(self.split.stable_id, 6, center=True)),
        )
        QTest.mousePress(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.widget.viewport(), stop)
        QTest.mouseRelease(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=stop)
        self.assertEqual(serialize(self.stack.current), before)

    def test_toggle_hold_escape_cancels_preview_without_commit(self) -> None:
        original = serialize(self.doc)
        start = QPoint(self.x, self.y)
        stop = QPoint(
            self.x, int(self.widget.layout_model.y_for_row(self.split.stable_id, 6, center=True)),
        )
        QTest.mousePress(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.widget.viewport(), stop)
        self.assertIsNotNone(self.widget._hold_preview_hit)
        self.widget._cancel_interaction()
        QTest.mouseRelease(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=stop)
        self.assertEqual(serialize(self.stack.current), original)

    def test_explicit_hold_tool_creates_span_and_does_not_add_taps_on_click(self) -> None:
        self.widget.set_tool(InteractionTool.HOLD)
        before = serialize(self.stack.current)
        x = self.x
        first = QPoint(x, self.y)
        QTest.mouseClick(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=first)
        self.assertEqual(serialize(self.stack.current), before)
        target = QPoint(
            x, int(self.widget.layout_model.y_for_row(self.split.stable_id, 6, center=True))
        )
        QTest.mousePress(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=first)
        QTest.mouseMove(self.widget.viewport(), target)
        QTest.mouseRelease(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=target)
        self.assertEqual(
            [self.controller.document.splits[0].blocks[0].rows[row].cells[1].raw[0] & 0x0F
             for row in range(2, 7)],
            [7, 11, 11, 11, 15],
        )

    def test_hold_rendering_draws_shaft_once_per_cell_and_two_terminals(self) -> None:
        self.widget.set_tool(InteractionTool.HOLD)
        from stepnx.authoring.stepedit_hold import plan_hold_creation
        from stepnx.authoring.tools import NoteTool, note_tool_raw
        type_map = {7: NoteTool.HOLD_HEAD, 11: NoteTool.HOLD_BODY, 15: NoteTool.HOLD_TAIL}
        block = self.controller.document.splits[0].blocks[0]
        scope = self.controller.capture_scope(self.split.stable_id, block.stable_id)
        edits = plan_hold_creation(
            block, 1, 2, 8, lambda kind: note_tool_raw(type_map[kind]),
        )
        self.controller.apply_note_batch(scope, edits)
        self.widget._rebuild_layout()
        seg = self.widget.layout_model.segment(self.split.stable_id)
        canvas = QImage(1200, 1000, QImage.Format.Format_ARGB32)
        canvas.fill(0)
        painter = QPainter(canvas)
        try:
            with (
                patch.object(self.widget._artist, "draw_hold_shaft",
                             wraps=self.widget._artist.draw_hold_shaft) as shaft,
                patch.object(self.widget._artist, "draw",
                             wraps=self.widget._artist.draw) as terminal,
            ):
                self.widget._draw_notes(painter, seg, 2, 9, 0)
            self.assertEqual(shaft.call_count, 7)
            self.assertEqual(terminal.call_count, 2)
            self.assertEqual(
                [c.args[4][0] & 0x0F for c in terminal.call_args_list],
                [7, 15],
            )
        finally:
            painter.end()

    def test_shift_rectangle_selects_without_mutating(self) -> None:
        before = serialize(self.doc)
        x_other = int(self.widget.layout_model.x_for_lane(2))
        y_other = int(self.widget.layout_model.y_for_row(self.split.stable_id, 4, center=True))
        QTest.mousePress(
            self.widget.viewport(), Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier, QPoint(self.x, self.y)
        )
        QTest.mouseMove(self.widget.viewport(), QPoint(x_other, y_other))
        QTest.mouseRelease(
            self.widget.viewport(), Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.ShiftModifier, QPoint(x_other, y_other)
        )
        self.assertEqual(len(self.controller.session.selection.targets), 6)
        self.assertEqual(serialize(self.stack.current), before)

    def test_escape_cancels_paint_and_invalid_mouse_release_does_not_commit(self) -> None:
        self.widget.set_tool(InteractionTool.ADD)
        source = serialize(self.doc)
        point = QPoint(self.x, self.y)
        QTest.mousePress(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.widget._cancel_interaction()
        QTest.mouseRelease(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(serialize(self.stack.current), source)
        self.assertFalse(self.stack.can_undo)

    def test_route_switch_prevents_stale_note_target(self) -> None:
        doc = InsertBlock(self.split.stable_id, self.block).apply(self.doc)
        self.widget.close()
        self.controller = EditorController(CommandStack(doc))
        self.widget = StepEditExperimentalViewport(self.controller, tap_raw=lambda: _RAW)
        self.widget.resize(720, 580)
        self.widget.show()
        self.application.processEvents()
        initial = serialize(doc)
        self.widget.cycle_block(self.split.stable_id)
        self.assertEqual(
            self.widget.layout_model.segment(self.split.stable_id).block_id,
            doc.splits[0].blocks[1].stable_id,
        )
        self.assertEqual(serialize(self.controller.document), initial)

    def test_dense_chart_render_and_cull_have_bounded_row_materialization(self) -> None:
        self.widget.close()
        doc = parse_bytes(
            make_large_playable(rows=200_000, columns=10),
            row_storage="compact",
        )
        self.controller = EditorController(CommandStack(doc))
        self.widget = StepEditExperimentalViewport(self.controller)
        self.widget.resize(720, 540)
        self.widget.show()
        self.application.processEvents()
        seg = self.widget.layout_model.segments[0]
        self.widget.verticalScrollBar().setValue(
            int((100_000 * seg.row_pitch) / self.widget._scroll_scale)
        )
        views = self.widget.layout_model.visible_segments(
            self.widget._scroll_y(), self.widget.viewport().height()
        )
        self.assertEqual(len(views), 1)
        self.assertLess(views[0].row_count, 100)
        self.widget.viewport().repaint()

    def test_wheel_uses_native_24_zoom_line_step_and_system_line_count(self) -> None:
        bar = self.widget.verticalScrollBar()
        bar.setValue(700)
        start = bar.value()
        lines = int(QApplication.wheelScrollLines())
        expected = round(wheel_notch_pixels(
            4, lines, self.widget.viewport().height()
        ))
        event = QWheelEvent(
            QPointF(150, 100), QPointF(150, 100),
            QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
        )
        self.widget.wheelEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(bar.value(), max(0, start - expected))

    def test_wheel_precision_accumulates_partial_detents(self) -> None:
        bar = self.widget.verticalScrollBar()
        bar.setValue(700)
        start = bar.value()
        lines = int(QApplication.wheelScrollLines())
        for _ in range(4):
            event = QWheelEvent(
                QPointF(150, 100), QPointF(150, 100),
                QPoint(), QPoint(0, 30), Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
            )
            self.widget.wheelEvent(event)
        self.assertEqual(
            bar.value(),
            max(0, start - round(wheel_notch_pixels(
                4, lines, self.widget.viewport().height()
            ))),
        )

    def test_existing_atlas_tap_is_top_aligned_and_scales_only_with_field_zoom(self) -> None:
        self.stack.execute(SetNoteAt(self.block.rows[2].stable_id, 1, _RAW))
        self.controller.sync_external_change()
        self.widget._rebuild_layout()
        for percent in EDITOR_ZOOM_PRESETS:
            with self.subTest(percent=percent):
                self.widget.set_zoom(percent)
                seg = self.widget.layout_model.segment(self.split.stable_id)
                canvas = QImage(1200, 1200, QImage.Format.Format_ARGB32)
                canvas.fill(0)
                painter = QPainter(canvas)
                try:
                    with patch.object(self.widget._artist, "draw",
                                      wraps=self.widget._artist.draw) as spy:
                        self.widget._draw_notes(painter, seg, 2, 3, scroll=0)
                    self.assertEqual(spy.call_count, 1)
                    dest = spy.call_args.args[1]
                    self.assertAlmostEqual(dest.x(), self.widget.layout_model.x_for_lane(1, center=False))
                    self.assertAlmostEqual(dest.y(), seg.y_for_row(2))
                    self.assertEqual(dest.width(), ATLAS_TILE_PIXELS * percent / 100)
                    self.assertEqual(dest.height(), ATLAS_TILE_PIXELS * percent / 100)
                    self.assertNotAlmostEqual(dest.y(), seg.y_for_row(2, center=True))
                    self.assertLessEqual(seg.row_pitch, dest.height())
                finally:
                    painter.end()

    def test_default_renderer_uses_bundled_existing_noteskin(self) -> None:
        artist = self.widget._artist
        self.assertIsInstance(artist, StepEditAtlasArtist)
        self.assertIsNotNone(artist.pack.bank(0))
        atlas = artist.pack.bank(0).animation[0]
        self.assertEqual(atlas.tile(1, 1)[2:], (96, 96))
        canvas = QImage(240, 240, QImage.Format.Format_ARGB32)
        canvas.fill(0)
        painter = QPainter(canvas)
        try:
            with patch.object(artist, "_tile", wraps=artist._tile) as spy:
                drawn = artist.draw(
                    painter, QRectF(0, 0, 96, 96), 1, _RAW, 48,
                )
            self.assertTrue(drawn)
            self.assertEqual(spy.call_args.args[2:4], (1, 1))
        finally:
            painter.end()

    def test_split_background_cycles_exactly_four_colors(self) -> None:
        expected = ("#ffffeb", "#ebffff", "#ebffeb", "#ffebff")
        self.assertEqual(
            tuple(split_background(index).name() for index in range(8)),
            expected + expected,
        )
        self.assertEqual(SELECTION_BACKGROUND.name(), "#c8c8c8")

    def test_selected_empty_cell_paints_gray_under_grid_lines(self) -> None:
        from stepnx.authoring.selection import CellTarget, CellSelection
        target = CellTarget(self.block.rows[2].stable_id, 1)
        self.controller.session.selection = CellSelection(frozenset({target}), target)
        canvas = QImage(650, 420, QImage.Format.Format_ARGB32)
        canvas.fill(0)
        painter = QPainter(canvas)
        try:
            view = self.widget.layout_model.visible_segments(0, 420)[0]
            self.widget._draw_grid(painter, view, 0)
        finally:
            painter.end()
        x = round(self.widget.layout_model.x_for_lane(1))
        y = round(self.widget.layout_model.y_for_row(self.split.stable_id, 2) + 12)
        self.assertEqual(canvas.pixelColor(x, y).name(), "#c8c8c8")
        self.assertEqual(canvas.pixelColor(x + 120, y).name(), "#ffffeb")

    def test_zoom_preset_preserves_linear_temporal_spacing(self) -> None:
        self.assertEqual(EDITOR_ZOOM_PRESETS, (25, 50, 75, 100, 125, 150, 175, 200))
        original = scaled_editor_geometry(100)
        for percent in EDITOR_ZOOM_PRESETS:
            with self.subTest(percent=percent):
                g = scaled_editor_geometry(percent)
                self.assertAlmostEqual(g.lane_pitch, 96 * percent / 100)
                self.assertEqual(g.beat_height, original.beat_height)
                self.assertAlmostEqual(g.vertical_zoom, percent / 100)
        with self.assertRaises(ValueError):
            scaled_editor_geometry(225)

    def test_palette_matches_stepedit_reference_screenshot(self) -> None:
        self.assertEqual(NOTE_BACKGROUND.name().lower(), "#ffffeb")
        self.assertEqual(INDICATOR_BACKGROUND.name().lower(), "#d4d0c8")
        self.assertEqual(VERTICAL_GRID.name().lower(), "#005494")
        self.assertEqual(MINOR_GRID.name().lower(), "#b2d7eb")
        self.assertEqual(MAJOR_GRID.name().lower(), "#005494")
        self.assertEqual(LANE_BOUNDARY.name().lower(), "#ff0000")

    def test_modal_window_exposes_controllers_and_zoom(self) -> None:
        dialog = StepEditExperimentalDialog(self.controller, tap_raw=lambda: _RAW)
        try:
            self.assertEqual(dialog.viewport_widget.controller, self.controller)
            idx = dialog.zoom_combo.findData(200)
            dialog.zoom_combo.setCurrentIndex(idx)
            self.assertEqual(dialog.viewport_widget.layout_model.geometry.vertical_zoom, 2.0)
            self.assertEqual(dialog.viewport_widget.layout_model.geometry.lane_pitch, 192)
            self.assertEqual(dialog.split_combo.count(), 1)
            self.assertEqual(dialog.block_combo.count(), 1)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_main_window_menu_launch_synchronizes_workspace_once(self) -> None:
        class FakeWindow(QMainWindow):
            def __init__(self, doc):
                super().__init__()
                self.setWindowTitle("StepNX Studio")
                self.sessions = {0: CommandStack(doc)}
                self.tabs = QTabWidget(self)
                self.source = QWidget()
                self.source.snapshot = __import__(
                    "stepnx.authoring.snapshot", fromlist=["create_authoring_snapshot"]
                ).create_authoring_snapshot(doc)
                self.tabs.addTab(self.source, "NM.NX")
                self.tool_value = QSpinBox()
                self.tool_value.setValue(0)
                self.updated = []
                self.menuBar().addMenu("&Preview")
            def _current_document_index(self):
                return 0
            def _selected_function(self):
                return NoteFunction.NORMAL
            def _selected_visibility(self):
                return NoteVisibility.VISIBLE
            def _apply_document(self, index, source, document):
                self.updated.append((index, source, document))

        win = FakeWindow(self.doc)
        try:
            install_stepedit_experimental(win)
            def edit_inside_dialog(dialog):
                view = dialog.viewport_widget
                split = view.controller.document.splits[0]
                block = split.blocks[0]
                scope = view.controller.capture_scope(split.stable_id, block.stable_id)
                from stepnx.authoring.selection import CellTarget
                view.controller.set_note(scope, CellTarget(block.rows[0].stable_id, 0), _RAW)
                return 1
            with patch.object(StepEditExperimentalDialog, "exec", edit_inside_dialog):
                win.stepedit_experimental_action.trigger()
            self.assertEqual(len(win.updated), 1)
            self.assertIs(win.updated[0][2], win.sessions[0].current)
            self.assertEqual(win.sessions[0].current.splits[0].blocks[0].rows[0].cells[0].raw, _RAW)
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
