from pathlib import Path

path = Path("src/stepnx/gui/preview_widget.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one match, found {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)


replace_once(
    "from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPainterPath, QPen, QPixmap\n",
    "from PySide6.QtGui import (\n"
    "    QColor,\n"
    "    QKeyEvent,\n"
    "    QPainter,\n"
    "    QPainterPath,\n"
    "    QPen,\n"
    "    QPixmap,\n"
    "    QTransform,\n"
    ")\n",
)
replace_once(
    "from stepnx.preview.modifiers import AccDecMode\n",
    "from stepnx.preview.modifiers import AccDecMode, SequenceZoneTransform\n",
)
replace_once(
    "    native_line_y,\n    native_screen_y,\n    native_snake_x_offset,\n",
    "    native_line_local_y,\n    native_line_y,\n    native_screen_y,\n"
    "    native_snake_x_offset,\n    sequence_zone_affine,\n",
)

replace_once(
    """        self.stream = stream
        self.columns = int(columns)
        self.start_column = int(start_column)
        self.field_mode = \"SINGLE\" if self.columns <= 5 else \"DOUBLE\"
        self.session = GameplaySession(
            stream, command or parse_gameplay_command(\"\"), autoplay=True
        )
""",
    """        resolved_command = command or parse_gameplay_command(\"\")
        header_random = bool(
            stream.effective_modifier is not None and stream.effective_modifier.random
        )
        if resolved_command.randomize and not header_random:
            stream = stream.with_randomized_lanes(seed=stream.route.seed or 0)
        self.stream = stream
        self.columns = int(columns)
        self.start_column = int(start_column)
        self.field_mode = \"SINGLE\" if self.columns <= 5 else \"DOUBLE\"
        self.session = GameplaySession(stream, resolved_command, autoplay=True)
""",
)

replace_once(
    """    def _is_upside_down(self) -> bool:
        return self.command.upside_down or self.session.runtime_modifier.upside_down

    def _receptor_y(self) -> float:
        return float(self.height() - 82) if self._is_upside_down() else 82.0

    def _lane_map(self) -> tuple[int, ...]:
        return self.command.lane_map(self.columns, seed=self.stream.route.seed or 0)
""",
    """    def _sequence_transform(self) -> SequenceZoneTransform:
        transform = self.session.runtime_modifier.sequence_transform
        if self.command.under_attack:
            transform |= SequenceZoneTransform.UNDER_ATTACK
        if self.command.drop:
            transform |= SequenceZoneTransform.DROP
        return transform

    def _receptor_y(self) -> float:
        # UA/Drop/Mid transform the complete playfield afterward. Keep one
        # canonical local receptor anchor instead of baking Drop into note Y.
        return 82.0

    def _sequence_affine(self) -> tuple[float, float, float, float]:
        return sequence_zone_affine(
            self._sequence_transform(),
            float(self.width()),
            float(self.height()),
            normal_receptor_y=self._receptor_y(),
        )

    def _lane_map(self) -> tuple[int, ...]:
        return self.command.lane_map(self.columns, seed=self.stream.route.seed or 0)

    def _screen_lane_to_source(self, visual_lane: int) -> int:
        lane = int(visual_lane)
        if self._sequence_transform() & SequenceZoneTransform.UNDER_ATTACK:
            lane = self.columns - 1 - lane
        return self._lane_map()[lane]
""",
)

replace_once(
    """    def _event_native_y(self, event: PreviewEvent) -> float:
        distance = self.stream.beat_distance_at(event, self._chart_time_ms)
        return native_line_y(
            distance,
            self.session.high_speed,
            self._effective_acc_dec(),
        )

    def _event_y(self, event: PreviewEvent) -> float:
        geometry = self._geometry()
        return native_screen_y(
            self._event_native_y(event),
            self._receptor_y(),
            geometry.note_size,
            upside_down=self._is_upside_down(),
        )
""",
    """    def _event_local_y(self, event: PreviewEvent) -> float:
        distance = self.stream.beat_distance_at(event, self._chart_time_ms)
        return native_line_local_y(distance, self._effective_acc_dec())

    def _event_native_y(self, event: PreviewEvent) -> float:
        distance = self.stream.beat_distance_at(event, self._chart_time_ms)
        return native_line_y(
            distance,
            self.session.high_speed,
            self._effective_acc_dec(),
        )

    def _event_y(self, event: PreviewEvent) -> float:
        geometry = self._geometry()
        return native_screen_y(
            self._event_native_y(event),
            self._receptor_y(),
            geometry.note_size,
        )
""",
)
replace_once(
    """        return native_snake_x_offset(
            self._event_native_y(event),
            self._geometry().note_size,
        )
""",
    """        return native_snake_x_offset(
            self._event_local_y(event),
            self._geometry().note_size,
        )
""",
)
replace_once(
    """        margin = 130.0 + abs(LINE_BASE_ACC_OFFSET) * (
            geometry.note_size / 72.0
        )
""",
    """        margin = 130.0 + abs(LINE_BASE_ACC_OFFSET) * (
            geometry.note_size / 72.0
        )
        if self._sequence_transform() & SequenceZoneTransform.MID:
            margin += abs(float(self.height()) / 2.0 - self._receptor_y())
""",
)

old_paint = """        receptor_y = self._receptor_y()
        if self._show_guide:
            painter.setPen(QPen(QColor(\"#ffd166\"), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(
                QPointF(left, receptor_y), QPointF(left + field_width, receptor_y)
            )
        self._draw_sequence_zone(painter, geometry, receptor_y)
        note_size = geometry.note_size
        self._draw_hold_shafts(painter, note_size)
        for note in self.visible_events():
            if note.note_type == 0xB:
                continue
            key = self.session.event_key(note)
            if (
                key in self.session.judgments
                and note.time_ms < self._chart_time_ms - 80
            ):
                continue
            centre_x = self.lane_center(note.lane) + self._event_x_offset(note)
            centre_y = self._event_y(note)
            rect = QRectF(
                centre_x - note_size / 2,
                centre_y - note_size / 2,
                note_size,
                note_size,
            )
            painter.save()
            painter.setOpacity(self._event_opacity(note))
            if not self._draw_asset(painter, note, rect):
                self._fallback_note(painter, note.note_type, rect)
            painter.restore()
        self._draw_pad_feedback(painter, geometry)
"""
new_paint = """        receptor_y = self._receptor_y()
        sx, sy, tx, ty = self._sequence_affine()
        painter.save()
        painter.setTransform(QTransform(sx, 0.0, 0.0, sy, tx, ty), True)
        if self._show_guide:
            painter.setPen(QPen(QColor(\"#ffd166\"), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(
                QPointF(left, receptor_y), QPointF(left + field_width, receptor_y)
            )
        self._draw_sequence_zone(painter, geometry, receptor_y)
        note_size = geometry.note_size
        self._draw_hold_shafts(painter, note_size)
        for note in self.visible_events():
            if note.note_type == 0xB:
                continue
            key = self.session.event_key(note)
            if (
                key in self.session.judgments
                and note.time_ms < self._chart_time_ms - 80
            ):
                continue
            centre_x = self.lane_center(note.lane) + self._event_x_offset(note)
            centre_y = self._event_y(note)
            rect = QRectF(
                centre_x - note_size / 2,
                centre_y - note_size / 2,
                note_size,
                note_size,
            )
            painter.save()
            painter.setOpacity(self._event_opacity(note))
            if not self._draw_asset(painter, note, rect):
                self._fallback_note(painter, note.note_type, rect)
            painter.restore()
        self._draw_pad_feedback(painter, geometry)
        painter.restore()
"""
replace_once(old_paint, new_paint)

replace_once(
    """            visual_lane = global_lane - self.start_column
            if 0 <= visual_lane < self.columns:
                self.session.release(self._lane_map()[visual_lane])
                self.update()
""",
    """            visual_lane = global_lane - self.start_column
            if 0 <= visual_lane < self.columns:
                self.session.release(self._screen_lane_to_source(visual_lane))
                self.update()
""",
)
replace_once(
    """        visual_lane = global_lane - self.start_column
        if 0 <= visual_lane < self.columns:
            self.session.press(
                self._lane_map()[visual_lane], self._chart_time_ms
            )
""",
    """        visual_lane = global_lane - self.start_column
        if 0 <= visual_lane < self.columns:
            self.session.press(
                self._screen_lane_to_source(visual_lane), self._chart_time_ms
            )
""",
)

path.write_text(text, encoding="utf-8")
