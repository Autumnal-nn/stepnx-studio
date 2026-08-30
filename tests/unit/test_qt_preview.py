from __future__ import annotations

import os
import unittest
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QImage, QKeyEvent, QPainter, QTransform
    from PySide6.QtWidgets import QApplication

    from stepnx.codecs.nx20 import parse_bytes
    from stepnx.gui.preview_dialog import (
        GameplayInitializationDialog,
        PreviewChartChoice,
    )
    from stepnx.gui.preview_widget import GameplayPreviewWidget
    from stepnx.preview import (
        COMMAND_FLAGS,
        AccDecMode,
        PlayfieldStyle,
        RoutePolicy,
        SequenceZoneTransform,
        StepParam,
        build_event_stream,
        create_preview_snapshot,
        legacy_acc_dec_distance,
        parse_gameplay_command,
        prime2_snake_path_lane_position,
        resolve_route,
    )
    from stepnx.preview.legacy_render import (
        legacy_nx_project_point,
        legacy_visibility_gradient_stops,
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

    def _widget(self, command="") -> GameplayPreviewWidget:
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
            command=parse_gameplay_command(command),
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

    def test_legacy_visibility_uses_native_screen_mask(self) -> None:
        widget = self._widget("v")
        try:
            widget.resize(640, 480)
            self.assertEqual(widget._effective_visibility(widget.stream.events[0]), 2)
            stops = legacy_visibility_gradient_stops(2)
            self.assertAlmostEqual(stops[1][0] * 480.0, 224.5, places=5)
            self.assertAlmostEqual(stops[2][0] * 480.0, 256.375, places=5)
        finally:
            widget.close()

    def test_nx_mode_qtransform_matches_all_recovered_native_branches(self) -> None:
        cases = (
            ("^", False, False),
            ("^!", True, False),
            ("^u", False, True),
            ("^u!", True, True),
        )
        for command, drop, under_attack in cases:
            widget = self._widget(command)
            try:
                widget.resize(640, 480)
                self.assertTrue(widget._effective_nx_mode())
                transform = widget._playfield_transform()
                for point in (QPointF(320.0, 82.0), QPointF(200.0, 300.0)):
                    mapped = transform.map(point)
                    expected_x, expected_y = legacy_nx_project_point(
                        point.x(),
                        point.y(),
                        640.0,
                        480.0,
                        drop=drop,
                        under_attack=under_attack,
                    )
                    self.assertAlmostEqual(mapped.x(), expected_x, places=5)
                    self.assertAlmostEqual(mapped.y(), expected_y, places=5)
                # Every native NX branch keeps the receptor on the central horizon.
                receptor = transform.map(QPointF(320.0, 82.0))
                self.assertLess(abs(receptor.y() - 240.0), 1.0)
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

    def test_initialization_dialog_uses_semantic_modifier_labels(self) -> None:
        dialog = GameplayInitializationDialog(
            (
                PreviewChartChoice(2, "S17.NX"),
                PreviewChartChoice(4, "D18.NX"),
            ),
            current_document_index=4,
        )
        try:
            self.assertEqual(dialog.chart_combo.currentText(), "D18.NX")
            self.assertEqual(dialog.command_list.count(), len(COMMAND_FLAGS))
            self.assertGreaterEqual(
                dialog.command_list.minimumHeight(), len(COMMAND_FLAGS) * 22
            )
            self.assertEqual(
                tuple(dialog.command_items),
                tuple(flag.code for flag in COMMAND_FLAGS),
            )
            self.assertEqual(
                tuple(dialog.command_list.item(i).text() for i in range(dialog.command_list.count())),
                tuple(flag.label for flag in COMMAND_FLAGS),
            )
            self.assertEqual(dialog.command_items["^"].text(), "NX Mode")

            dialog.chart_combo.setCurrentText("S17.NX")
            dialog.speed_combo.setCurrentIndex(7)
            dialog.command_items["v"].setCheckState(Qt.CheckState.Checked)
            dialog.command_items["m"].setCheckState(Qt.CheckState.Checked)
            dialog.command_items["^"].setCheckState(Qt.CheckState.Checked)
            options = dialog.options()
            self.assertEqual(options.document_index, 2)
            self.assertEqual(options.speed, 8)
            self.assertEqual(options.command, "vm^")
        finally:
            dialog.close()

    def test_command_selector_enforces_only_true_exclusivity(self) -> None:
        dialog = GameplayInitializationDialog((PreviewChartChoice(0, "S17.NX"),))
        try:
            dialog.command_items["d"].setCheckState(Qt.CheckState.Checked)
            dialog.command_items["a"].setCheckState(Qt.CheckState.Checked)
            self.assertEqual(
                dialog.command_items["d"].checkState(),
                Qt.CheckState.Unchecked,
            )
            self.assertEqual(
                dialog.command_items["a"].checkState(),
                Qt.CheckState.Checked,
            )

            dialog.command_items["s"].setCheckState(Qt.CheckState.Checked)
            dialog.command_items["e"].setCheckState(Qt.CheckState.Checked)
            self.assertEqual(
                dialog.command_items["s"].checkState(),
                Qt.CheckState.Unchecked,
            )
            self.assertEqual(
                dialog.command_items["e"].checkState(),
                Qt.CheckState.Checked,
            )

            # UA and Drop are independent bits and must compose.
            dialog.command_items["u"].setCheckState(Qt.CheckState.Checked)
            dialog.command_items["!"].setCheckState(Qt.CheckState.Checked)
            self.assertEqual(
                dialog.command_items["u"].checkState(), Qt.CheckState.Checked
            )
            self.assertEqual(
                dialog.command_items["!"].checkState(), Qt.CheckState.Checked
            )
            self.assertEqual(dialog.options().command, "u!ae")
        finally:
            dialog.close()

    def test_sequence_transform_affects_playfield_and_input_not_lane_map(self) -> None:
        ua = self._widget("u")
        drop = self._widget("!")
        both = self._widget("u!")
        try:
            for widget in (ua, drop, both):
                widget.resize(640, 480)

            self.assertEqual(
                ua._sequence_transform(), SequenceZoneTransform.UNDER_ATTACK
            )
            self.assertEqual(ua._sequence_affine(), (-1.0, -1.0, 640.0, 480.0))
            self.assertEqual(drop._sequence_affine(), (1.0, -1.0, 0.0, 480.0))
            self.assertEqual(both._sequence_affine(), (-1.0, 1.0, 640.0, 0.0))

            # UA's X reflection changes which source lane a physical screen lane
            # addresses. Drop never changes horizontal input mapping.
            self.assertEqual(ua._screen_lane_to_source(0), 4)
            self.assertEqual(drop._screen_lane_to_source(0), 0)
            self.assertEqual(both._screen_lane_to_source(0), 4)
        finally:
            ua.close()
            drop.close()
            both.close()

    def test_under_attack_rotates_note_coordinates_with_the_playfield(self) -> None:
        widget = self._widget("u")
        try:
            widget.resize(640, 480)
            event = widget.stream.events[0]
            local = QPoint(
                round(widget.lane_center(event.lane)),
                round(widget._event_y(event)),
            )
            sx, sy, tx, ty = widget._sequence_affine()
            mapped = QTransform(sx, 0.0, 0.0, sy, tx, ty).map(local)
            self.assertEqual(mapped.x(), widget.width() - local.x())
            self.assertEqual(mapped.y(), widget.height() - local.y())
            # The same QPainter transform is active while drawPixmap runs, so
            # note artwork rotates with its position instead of only moving the bar.
        finally:
            widget.close()

    def test_legacy_command_accdec_uses_prime_nxa_curve_not_rise_header_curve(self) -> None:
        acceleration = self._widget("a")
        deceleration = self._widget("d")
        try:
            for widget, mode in (
                (acceleration, AccDecMode.ACCELERATION),
                (deceleration, AccDecMode.DECELERATION),
            ):
                widget.resize(640, 480)
                distance = 100.0 / 60.0
                expected = widget._receptor_y() + legacy_acc_dec_distance(
                    distance,
                    widget.session.high_speed,
                    widget._geometry().path_unit,
                    mode,
                )
                self.assertAlmostEqual(
                    widget._screen_y_for_beat_distance(distance), expected, places=5
                )
        finally:
            acceleration.close()
            deceleration.close()

    def test_single_exceed_keeps_one_player_side_even_for_centre_lane(self) -> None:
        p1 = self._widget("x")
        p2_base = self._widget("x")
        p2 = GameplayPreviewWidget(
            p2_base.stream,
            columns=5,
            start_column=5,
            command=parse_gameplay_command("x"),
        )
        try:
            for widget in (p1, p2):
                widget.resize(640, 480)
                event = replace(widget.stream.events[0], lane=2)
                # A centred lane is still diagonal: P1 approaches from the
                # right, P2 from the left.
                distance = widget._event_beat_distance(event)
                expected = abs(distance) * widget.session.high_speed * widget._geometry().path_unit
                vertical = widget._event_y(event) - widget._receptor_y()
                self.assertAlmostEqual(vertical, expected)
                if widget is p1:
                    self.assertAlmostEqual(widget._event_x_offset(event), expected)
                    self.assertAlmostEqual(widget._event_x_offset(event), vertical)
                else:
                    self.assertAlmostEqual(widget._event_x_offset(event), -expected)
                    self.assertAlmostEqual(widget._event_x_offset(event), -vertical)
        finally:
            p1.close()
            p2.close()
            p2_base.close()

    def test_double_exceed_offsets_native_five_lane_banks_without_clamp(self) -> None:
        base = self._widget("x")
        widget = GameplayPreviewWidget(
            base.stream,
            columns=10,
            start_column=0,
            command=parse_gameplay_command("x"),
        )
        try:
            widget.resize(640, 480)
            source = widget.stream.events[0]
            current_position = widget.stream.position_at(widget.chart_time_ms)
            # Four beats at 2x is deliberately farther than the old half-field
            # cap, reproducing EF029's off-screen diagonal entry condition.
            widget.session.select_speed(2)
            p1 = replace(source, lane=2, native_block_index=-1, position=current_position + 4.0)
            p2 = replace(source, lane=7, native_block_index=-1, position=current_position + 4.0)
            expected = 4.0 * widget.session.high_speed * widget._geometry().path_unit
            self.assertGreater(expected, widget._geometry().field_width * 0.5)
            self.assertAlmostEqual(widget._event_x_offset(p1), expected)
            self.assertAlmostEqual(widget._event_x_offset(p2), -expected)
            # path_exeed uses that same d for its vertical travel. The native
            # trajectory is therefore 1:1 in rendered X/Y path units.
            self.assertAlmostEqual(
                widget._screen_y_for_beat_distance(4.0) - widget._receptor_y(),
                expected,
            )
            self.assertAlmostEqual(
                widget._event_x_offset(p1),
                widget._screen_y_for_beat_distance(4.0) - widget._receptor_y(),
            )
        finally:
            widget.close()
            base.close()

    def test_division_200_selects_all_four_prime_render_styles(self) -> None:
        base = self._widget()
        try:
            timing = base.stream.native_timing
            self.assertIsNotNone(timing)
            block_id = timing.blocks[0].block_id
            expected = {
                0: (PlayfieldStyle.SINGLE, 160.0, 160.0),
                1: (PlayfieldStyle.DOUBLE, 194.0, 446.0),
                2: (PlayfieldStyle.VERSUS, 160.0, 480.0),
                3: (PlayfieldStyle.CENTERED, 320.0, 320.0),
            }
            for raw_value, (style, p1, p2) in expected.items():
                stream = replace(
                    base.stream,
                    block_step_params=((block_id, (StepParam(200, raw_value),)),),
                )
                widget = GameplayPreviewWidget(
                    stream,
                    columns=10,
                    start_column=0,
                    command=parse_gameplay_command(""),
                )
                try:
                    widget.resize(640, 480)
                    self.assertIs(widget._active_playfield_style(), style)
                    self.assertEqual(widget._geometry().lane_center(2), p1)
                    self.assertEqual(widget._geometry().lane_center(7), p2)
                finally:
                    widget.close()
        finally:
            base.close()

    def test_missing_division_200_uses_chart_width_defaults(self) -> None:
        five = self._widget()
        ten_base = self._widget()
        ten = GameplayPreviewWidget(
            ten_base.stream,
            columns=10,
            start_column=0,
            command=parse_gameplay_command(""),
        )
        try:
            five.resize(640, 480)
            ten.resize(640, 480)
            self.assertIs(five._active_playfield_style(), PlayfieldStyle.CENTERED)
            self.assertIs(ten._active_playfield_style(), PlayfieldStyle.DOUBLE)
        finally:
            five.close()
            ten.close()
            ten_base.close()

    def test_throw_projects_depth_instead_of_adding_y_offset(self) -> None:
        sink = self._widget("(")
        try:
            sink.resize(640, 480)
            event = sink.stream.events[0]
            base_y = sink._event_y(event)
            _, projected_y, rendered_size = sink._event_render_geometry(event)
            self.assertAlmostEqual(
                sink._screen_y_for_beat_distance(sink._event_beat_distance(event)),
                base_y,
            )
            # Perspective changes both position about screen centre and sprite
            # size. A fake vertical offset could not satisfy this invariant.
            if abs(sink._event_beat_distance(event)) > 1e-6:
                self.assertNotAlmostEqual(projected_y, base_y)
                self.assertNotAlmostEqual(rendered_size, sink._geometry().note_size)
        finally:
            sink.close()

    def test_single_exceed_keeps_one_player_side_even_for_centre_lane(self) -> None:
        p1 = self._widget("x")
        p2_base = self._widget("x")
        p2 = GameplayPreviewWidget(
            p2_base.stream,
            columns=5,
            start_column=5,
            command=parse_gameplay_command("x"),
        )
        try:
            for widget in (p1, p2):
                widget.resize(640, 480)
                # Row zero is exactly at the receptor in this fixture. Use the
                # next native row so Exceed has non-zero travel to project.
                event = replace(widget.stream.events[0], lane=2, row_index=1)
                if widget is p1:
                    self.assertGreater(widget._event_x_offset(event), 0.0)
                else:
                    self.assertLess(widget._event_x_offset(event), 0.0)
        finally:
            p1.close()
            p2.close()
            p2_base.close()

    def test_throw_projects_depth_instead_of_adding_y_offset(self) -> None:
        sink = self._widget("(")
        try:
            sink.resize(640, 480)
            event = replace(sink.stream.events[0], row_index=1)
            base_y = sink._event_y(event)
            _, projected_y, rendered_size = sink._event_render_geometry(event)
            self.assertAlmostEqual(
                sink._screen_y_for_beat_distance(sink._event_beat_distance(event)),
                base_y,
            )
            self.assertNotAlmostEqual(projected_y, base_y)
            self.assertNotAlmostEqual(rendered_size, sink._geometry().note_size)
        finally:
            sink.close()

    def test_visual_effect_snake_path_reads_block_221_222_without_header_snake(self) -> None:
        widget = self._widget()
        try:
            widget.resize(640, 480)
            base = widget.stream.events[0]
            widget.stream = replace(
                widget.stream,
                block_step_params=((
                    base.block_id,
                    (StepParam(221, 2), StepParam(222, 3)),
                ),),
            )
            current_position = widget.stream.position_at(widget.chart_time_ms)
            seed = widget.stream.route.seed or 0
            candidates = [
                (lane, prime2_snake_path_lane_position(
                    lane, 4.0, widget.columns, seed, start=3.0, interval=2.0
                ))
                for lane in range(widget.columns)
            ]
            moving_lane, expected_lane = next(
                (lane, position)
                for lane, position in candidates
                if abs(position - float(lane)) > 1e-9
            )
            plain = replace(
                base,
                lane=moving_lane,
                raw=b"\x03\x03\x00\x00",
                native_block_index=-1,
                position=current_position + 4.0,
            )
            snake = replace(plain, raw=b"\x03\x13\x00\x00")

            self.assertFalse(plain.snake_path)
            self.assertTrue(snake.snake_path)
            self.assertEqual(widget._event_x_offset(plain), 0.0)
            expected = (
                widget._lane_position_x(expected_lane)
                - widget.lane_center(moving_lane)
            )
            self.assertNotEqual(expected, 0.0)
            self.assertAlmostEqual(widget._event_x_offset(snake), expected)
        finally:
            widget.close()

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
