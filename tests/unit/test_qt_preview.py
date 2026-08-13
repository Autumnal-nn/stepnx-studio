from __future__ import annotations

import os
import unittest
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QImage, QKeyEvent, QPainter
    from PySide6.QtWidgets import QApplication

    from stepnx.codecs.nx20 import parse_bytes
    from stepnx.gui.preview_dialog import (
        GameplayInitializationDialog,
        PreviewChartChoice,
    )
    from stepnx.gui.preview_widget import GameplayPreviewWidget
    from stepnx.preview import (
        RoutePolicy,
        build_event_stream,
        create_preview_snapshot,
        resolve_route,
    )
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""

from tests.fixture_factory import make_normal_nx20


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class QtGameplayPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _widget(self) -> GameplayPreviewWidget:
        document = parse_bytes(
            make_normal_nx20(), source="NM.NX", row_storage="compact"
        )
        split = document.splits[0]
        block = replace(
            split.blocks[0],
            scroll=split.blocks[0].scroll.with_value(1.0),
            smooth_speed=split.blocks[0].smooth_speed.with_value(0),
        )
        document = replace(document, splits=(replace(split, blocks=(block,)),))
        snapshot = create_preview_snapshot(document)
        route = resolve_route(snapshot, RoutePolicy.MANUAL)
        return GameplayPreviewWidget(
            build_event_stream(snapshot, route),
            columns=snapshot.columns,
            start_column=snapshot.start_column,
        )

    def test_offscreen_renderer_is_read_only_and_tracks_playback(self) -> None:
        widget = self._widget()
        try:
            widget.resize(640, 480)
            widget.show()
            self.assertGreater(len(widget.stream.events), 0)
            start = widget.stream.events[0].time_ms
            widget.set_playback_time(start)
            self.application.processEvents()

            self.assertEqual(widget.chart_time_ms, start)
            self.assertEqual(len(widget.visible_events()), len(widget.stream.events))
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

    def test_event_culling_uses_chart_time_without_mutating_stream(self) -> None:
        widget = self._widget()
        try:
            original = widget.stream
            widget.resize(400, 300)
            widget.set_playback_time(10_000_000.0)
            self.assertEqual(widget.visible_events(), ())
            self.assertIs(widget.stream, original)
        finally:
            widget.close()

    def test_runtime_keys_match_piutester_controls(self) -> None:
        widget = self._widget()
        try:
            widget.keyPressEvent(
                QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F6, Qt.NoModifier)
            )
            self.assertTrue(widget.show_debug)

            widget.keyPressEvent(
                QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F8, Qt.NoModifier)
            )
            self.assertFalse(widget.session.autoplay)

            widget.keyPressEvent(
                QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_5, Qt.NoModifier)
            )
            self.assertEqual(widget.command.speed, 5.0)

            widget.keyPressEvent(
                QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Q, Qt.NoModifier)
            )
            self.assertIn(1, widget.session.pressed_lanes)
            widget.keyReleaseEvent(
                QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Q, Qt.NoModifier)
            )
            self.assertNotIn(1, widget.session.pressed_lanes)

            exits = []
            widget.exitRequested.connect(lambda: exits.append(True))
            widget.keyPressEvent(
                QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.NoModifier)
            )
            self.assertEqual(exits, [True])
        finally:
            widget.close()

    def test_initialization_dialog_selects_chart_filename_and_launch_options(self) -> None:
        dialog = GameplayInitializationDialog(
            (
                PreviewChartChoice(2, "S17.NX"),
                PreviewChartChoice(4, "D18.NX"),
            ),
            current_document_index=4,
        )
        try:
            self.assertEqual(dialog.chart_combo.currentText(), "D18.NX")
            dialog.chart_combo.setCurrentText("S17.NX")
            dialog.speed_combo.setCurrentIndex(7)
            dialog.command_edit.setText("vm")
            options = dialog.options()
            self.assertEqual(options.document_index, 2)
            self.assertEqual(options.speed, 8)
            self.assertEqual(options.command, "vm")
        finally:
            dialog.close()

    def test_lane_geometry_centres_assets_on_native_sequence_zone_anchors(self) -> None:
        widget = self._widget()
        try:
            widget.resize(1200, 480)
            geometry = widget._geometry()

            self.assertAlmostEqual(
                geometry.left, (widget.width() - geometry.field_width) / 2
            )
            for source_lane in range(widget.columns):
                visual_lane = widget._visual_lane(source_lane)
                expected = geometry.lane_center(visual_lane)
                self.assertAlmostEqual(widget.lane_center(source_lane), expected)
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
