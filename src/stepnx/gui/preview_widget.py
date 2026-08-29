from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import deque
from time import perf_counter

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import QWidget

from stepnx.authoring.noteskin import LocalNoteskinPack, PngAtlas
from stepnx.preview.commands import GameplayCommand, parse_gameplay_command
from stepnx.preview.events import (
    PreviewEvent,
    RuntimeEventStream,
)
from stepnx.preview.geometry import PlayfieldGeometry
from stepnx.preview.modifiers import AccDecMode, SequenceZoneTransform, ThrowMode
from stepnx.preview.session import GameplaySession, Judgment
from stepnx.preview.speed import native_base_velocity_pixels
from stepnx.preview.visuals import (
    LINE_BASE_ACC_OFFSET,
    legacy_exceed_x_offset,
    native_line_local_y,
    native_line_y,
    native_screen_y,
    native_snake_x_offset,
    prime2_snake_x_offset,
    prime2_throw_y_offset,
    sequence_zone_affine,
)

_FALLBACK_COLORS = {
    0x1: QColor("#df8b42"),
    0x2: QColor("#b76dd8"),
    0x3: QColor("#62b8ff"),
    0x7: QColor("#8bc7ff"),
    0xB: QColor("#5f91cf"),
    0xF: QColor("#8bc7ff"),
}

_PAD_KEYS = {
    Qt.Key.Key_Z: 0,
    Qt.Key.Key_Q: 1,
    Qt.Key.Key_S: 2,
    Qt.Key.Key_E: 3,
    Qt.Key.Key_C: 4,
    Qt.Key.Key_End: 5,
    Qt.Key.Key_Home: 6,
    Qt.Key.Key_PageUp: 8,
    Qt.Key.Key_PageDown: 9,
}


class GameplayPreviewWidget(QWidget):
    """Interactive, document-independent gameplay simulation surface."""

    seekRequested = Signal(float)
    statusChanged = Signal(str)
    exitRequested = Signal()

    def __init__(
        self,
        stream: RuntimeEventStream,
        *,
        columns: int,
        start_column: int,
        command: GameplayCommand | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if columns <= 0:
            raise ValueError("gameplay preview requires at least one column")
        resolved_command = command or parse_gameplay_command("")
        header_random = bool(
            stream.effective_modifier is not None and stream.effective_modifier.random
        )
        if resolved_command.randomize and not header_random:
            stream = stream.with_randomized_lanes(seed=stream.route.seed or 0)
        self.stream = stream
        self.columns = int(columns)
        self.start_column = int(start_column)
        self.field_mode = "SINGLE" if self.columns <= 5 else "DOUBLE"
        self.session = GameplaySession(stream, resolved_command, autoplay=True)
        self._chart_time_ms = 0.0
        self._noteskin_pack: LocalNoteskinPack | None = None
        self._pixmaps: dict[str, QPixmap] = {}
        self._show_debug = False
        self._show_guide = False
        self._world_tour = False
        self._event_times = tuple(event.time_ms for event in stream.events)
        self._hold_pairs = self._pair_holds(stream.events)
        self._paint_timestamps: deque[float] = deque(maxlen=120)
        self._paint_cost_ms = 0.0
        self.setMinimumSize(420, 360)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._refresh_tooltip()

    @property
    def chart_time_ms(self) -> float:
        return self._chart_time_ms

    @property
    def command(self) -> GameplayCommand:
        return self.session.command

    @property
    def show_debug(self) -> bool:
        return self._show_debug

    @property
    def show_guide(self) -> bool:
        return self._show_guide

    @property
    def world_tour(self) -> bool:
        return self._world_tour

    def _refresh_tooltip(self) -> None:
        route = self.stream.route
        self.setToolTip(
            f"Read-only runtime · {route.policy.value} route · "
            f"{self.field_mode} · COMMAND={self.command.raw or '(none)'} · "
            f"{len(self.stream.events)} events"
        )

    def set_playback_time(self, chart_time_ms: float) -> None:
        if not math.isfinite(chart_time_ms):
            raise ValueError("playback time must be finite")
        self._chart_time_ms = float(chart_time_ms)
        self.session.advance(self._chart_time_ms)
        self.update()

    def set_noteskin_pack(self, pack: LocalNoteskinPack | None) -> None:
        self._noteskin_pack = pack
        self._pixmaps.clear()
        if pack is not None:
            # Decode optional STEPFX before playback. Disk I/O and PNG decoding
            # inside paintEvent causes a visible hitch on the first judgment.
            for bank in pack.banks:
                for path in bank.step_effects:
                    pixmap = QPixmap(str(path))
                    if not pixmap.isNull():
                        self._pixmaps[str(path)] = pixmap
        self.update()

    def _geometry(self) -> PlayfieldGeometry:
        return PlayfieldGeometry(max(1.0, float(self.width())), self.columns)

    def _sequence_transform(self) -> SequenceZoneTransform:
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

    def _visual_lane(self, source_lane: int) -> int:
        try:
            return self._lane_map().index(source_lane)
        except ValueError:
            return source_lane

    def lane_center(self, source_lane: int) -> float:
        """Return the shared horizontal centre for one source lane."""
        return self._geometry().lane_center(self._visual_lane(source_lane))

    def _effective_acc_dec(self) -> AccDecMode:
        mode = self.session.runtime_modifier.acc_dec
        # COMMAND D/A target the same mutually-exclusive mode. Preserve input
        # order for non-UI callers; the launch selector prevents both at once.
        for character in self.command.raw:
            if character == "d":
                mode = AccDecMode.DECELERATION
            elif character == "a":
                mode = AccDecMode.ACCELERATION
        return mode

    def _effective_throw(self) -> ThrowMode:
        mode = self.session.runtime_modifier.throw
        # Historical COMMAND Sink/Rise target the same three-state path family.
        for character in self.command.raw:
            if character == "(":
                mode = ThrowMode.SINK
            elif character == ")":
                mode = ThrowMode.RISE
        return mode

    def _event_beat_distance(self, event: PreviewEvent) -> float:
        return self.stream.beat_distance_at(event, self._chart_time_ms)

    def _event_local_y(self, event: PreviewEvent) -> float:
        return native_line_local_y(
            self._event_beat_distance(event), self._effective_acc_dec()
        )

    def _event_native_y(self, event: PreviewEvent) -> float:
        return native_line_y(
            self._event_beat_distance(event),
            self.session.high_speed,
            self._effective_acc_dec(),
        )

    def _event_throw_y_offset(self, event: PreviewEvent) -> float:
        mode = self._effective_throw()
        if mode is ThrowMode.FLAT:
            return 0.0
        return prime2_throw_y_offset(
            self._event_beat_distance(event),
            self.session.high_speed,
            self._geometry().note_size,
            rise=mode is ThrowMode.RISE,
        )

    def _event_y(self, event: PreviewEvent) -> float:
        geometry = self._geometry()
        return native_screen_y(
            self._event_native_y(event),
            self._receptor_y(),
            geometry.note_size,
        ) + self._event_throw_y_offset(event)

    def _event_x_offset(self, event: PreviewEvent) -> float:
        geometry = self._geometry()
        offset = 0.0

        # R!SE Header Snake is source-exact and uses a 20-unit LineBase sine.
        if self.session.runtime_modifier.snake:
            offset += native_snake_x_offset(
                self._event_local_y(event),
                geometry.note_size,
            )

        # The legacy/NX2 Snake path is distinct. Prime 2 establishes the final
        # amplitude as 60 * 0.5 = 30 units, so do not reuse R!SE's 20 here.
        if self.command.snake:
            offset += prime2_snake_x_offset(
                self._event_beat_distance(event),
                geometry.note_size,
            )

        # Exceed's exact coefficient remains unrecovered. Keep its historical
        # diagonal semantics isolated as an explicit approximation rather than
        # folding it into Mirror, UA, or lane mapping.
        if self.command.exceed_mode or self.session.runtime_modifier.exceed:
            centre_lane = (self.columns - 1) / 2.0
            if event.lane != centre_lane:
                offset += legacy_exceed_x_offset(
                    self._event_y(event) - self._receptor_y(),
                    geometry.field_width,
                    from_right=event.lane < centre_lane,
                    travel_height=float(self.height()),
                )
        return offset

    def _event_opacity(self, event: PreviewEvent) -> float:
        distance = abs(self._event_y(event) - self._receptor_y())
        return self.command.note_opacity(
            int(event.visibility),
            distance=distance,
            fade_distance=max(1.0, self.height() * 0.42),
            time_ms=self._chart_time_ms,
        )

    def visible_events(self) -> tuple[PreviewEvent, ...]:
        geometry = self._geometry()
        # Accel/Decel can add up to 200 native Y units outside the linear
        # projection. Include that exact bound in culling so transformed notes
        # are not discarded before _event_y() evaluates them.
        margin = 130.0 + abs(LINE_BASE_ACC_OFFSET) * (
            geometry.note_size / 72.0
        )
        if self._effective_throw() is not ThrowMode.FLAT:
            margin += 100.0 * (geometry.note_size / 72.0)
        if self._sequence_transform() & SequenceZoneTransform.MID:
            margin += abs(float(self.height()) / 2.0 - self._receptor_y())
        timing = self.stream.timing
        if not timing or not self.stream.events:
            return ()
        # The native position axis clamps after the route endpoint. Keep the
        # explicit time-domain guard so the last notes cannot reappear forever.
        if self._chart_time_ms > self.stream.duration_ms + 250.0:
            return ()
        current_position = self.stream.position_at(self._chart_time_ms)
        multiplier = max(0.001, abs(self.session.high_speed))
        base_velocity = native_base_velocity_pixels(geometry.note_size)
        visible_position = (self.height() + margin + abs(self._receptor_y())) / (
            base_velocity * multiplier
        )
        positions = (
            current_position - visible_position,
            current_position + visible_position,
        )
        time_bounds: list[float] = []
        for segment in timing:
            span = segment.end_position - segment.start_position
            if span == 0.0:
                if positions[0] <= segment.start_position <= positions[1]:
                    time_bounds.extend((segment.start_time_ms, segment.end_time_ms))
                continue
            segment_positions = sorted(
                (segment.start_position, segment.end_position)
            )
            if (
                segment_positions[1] < positions[0]
                or segment_positions[0] > positions[1]
            ):
                continue
            for position in positions:
                ratio = (position - segment.start_position) / span
                ratio = min(1.0, max(0.0, ratio))
                time_bounds.append(
                    segment.start_time_ms
                    + ratio * (segment.end_time_ms - segment.start_time_ms)
                )
        if not time_bounds:
            return ()
        first = bisect_left(self._event_times, min(time_bounds) - 250.0)
        last = bisect_right(self._event_times, max(time_bounds) + 250.0)
        return tuple(
            event
            for event in self.stream.events[first:last]
            if -margin <= self._event_y(event) <= self.height() + margin
        )

    @staticmethod
    def _pair_holds(
        events: tuple[PreviewEvent, ...],
    ) -> tuple[tuple[PreviewEvent, PreviewEvent], ...]:
        # RuntimeEventStream already contains one resolved route, so a Split or
        # Block boundary is not a break in hold identity. Native NX20 charts
        # routinely continue a long note into the next sequential Split. Keep
        # one open head per lane instead of incorrectly scoping it to block_id.
        open_heads: dict[int, PreviewEvent] = {}
        pairs: list[tuple[PreviewEvent, PreviewEvent]] = []
        for event in events:
            lane = event.lane
            if event.note_type == 0x7:
                open_heads[lane] = event
            elif event.note_type == 0xF and lane in open_heads:
                pairs.append((open_heads.pop(lane), event))
        return tuple(pairs)

    def _pixmap(self, atlas: PngAtlas) -> QPixmap | None:
        key = str(atlas.path)
        if key not in self._pixmaps:
            pixmap = QPixmap(key)
            if not pixmap.isNull():
                self._pixmaps[key] = pixmap
        return self._pixmaps.get(key)

    def _draw_atlas(
        self, painter: QPainter, atlas: PngAtlas, column: int, row: int, target: QRectF
    ) -> bool:
        pixmap = self._pixmap(atlas)
        if pixmap is None:
            return False
        painter.drawPixmap(target, pixmap, QRectF(*atlas.tile(column, row)))
        return True

    def _draw_asset(self, painter: QPainter, event: PreviewEvent, rect: QRectF) -> bool:
        pack = self._noteskin_pack
        if pack is None:
            return False
        note_type = event.note_type
        subtype = event.raw[2]
        atlas_lane = (self.start_column + self._visual_lane(event.lane)) % 5
        if note_type in (0x3, 0x7, 0xB, 0xF):
            bank = pack.bank(subtype)
            if bank is None:
                return False
            frame = int(max(0.0, self._chart_time_ms) // 80) % len(bank.animation)
            atlas = bank.animation[frame]
            row = {
                0x3: 2 if (event.raw[0] & 0x60) == 0x20 else 1,
                0x7: 1,
                0xB: 0,
                0xF: 0,
            }[note_type]
            return self._draw_atlas(painter, atlas, atlas_lane, row, rect)
        if note_type == 0x1 and pack.item_animation and subtype < 32:
            frame = int(max(0.0, self._chart_time_ms) // 80) % len(pack.item_animation)
            return self._draw_atlas(
                painter, pack.item_animation[frame], subtype, 0, rect
            )
        if note_type == 0x2 and pack.division is not None and subtype < 5:
            return self._draw_atlas(painter, pack.division, subtype, 0, rect)
        return False

    def _draw_pad_feedback(
        self, painter: QPainter, geometry: PlayfieldGeometry
    ) -> None:
        pack = self._noteskin_pack
        receptor_y = self._receptor_y()
        note_size = geometry.note_size
        for lane in range(self.columns):
            visual_lane = self._visual_lane(lane)
            centre = self.lane_center(lane)
            rect = QRectF(
                centre - note_size / 2,
                receptor_y - note_size / 2,
                note_size,
                note_size,
            )
            bank = None if pack is None else pack.bank(0)
            if (
                lane in self.session.pressed_lanes
                and bank is not None
                and bank.press_overlay is not None
            ):
                self._draw_atlas(
                    painter,
                    bank.press_overlay,
                    (self.start_column + visual_lane) % 5,
                    0,
                    rect,
                )

        for effect in reversed(self.session.step_effect_history):
            age = self._chart_time_ms - effect.time_ms
            if age >= 250.0:
                break
            if age < 0.0:
                continue
            bank = None if pack is None else pack.bank(effect.bank_id)
            if bank is None or len(bank.step_effects) != 5:
                continue
            frame = min(4, int(age // 50.0))
            pixmap = self._pixmaps.get(str(bank.step_effects[frame]))
            if pixmap is None:
                pixmap = QPixmap(str(bank.step_effects[frame]))
                if pixmap.isNull():
                    continue
                self._pixmaps[str(bank.step_effects[frame])] = pixmap
            centre = self.lane_center(effect.lane)
            effect_size = note_size * (512.0 / 96.0)
            target = QRectF(
                centre - effect_size / 2,
                receptor_y - effect_size / 2,
                effect_size,
                effect_size,
            )
            painter.save()
            try:
                # STEPFX sheets are opaque RGB images whose black background is
                # neutral under the original OpenGL additive blend. Source-over
                # would paint an ugly black square around every effect.
                painter.setCompositionMode(
                    QPainter.CompositionMode.CompositionMode_Plus
                )
                painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
            finally:
                painter.restore()

    @staticmethod
    def _fallback_note(painter: QPainter, note_type: int, rect: QRectF) -> None:
        color = _FALLBACK_COLORS.get(note_type, QColor("#e56b6f"))
        painter.setPen(QPen(color.lighter(140), 1.5))
        painter.setBrush(color)
        if note_type == 0x3:
            path = QPainterPath()
            path.moveTo(rect.center().x(), rect.top())
            path.lineTo(rect.right(), rect.center().y())
            path.lineTo(rect.center().x(), rect.bottom())
            path.lineTo(rect.left(), rect.center().y())
            path.closeSubpath()
            painter.drawPath(path)
        elif note_type == 0x2:
            painter.drawEllipse(rect)
        else:
            painter.drawRoundedRect(rect, 5, 5)

    def _draw_hold_shafts(self, painter: QPainter, note_size: float) -> None:
        for head, tail in self._hold_pairs:
            if tail.time_ms < self._chart_time_ms - 80.0:
                continue
            y1, y2 = self._event_y(head), self._event_y(tail)
            if head.time_ms <= self._chart_time_ms <= tail.time_ms:
                y1 = self._receptor_y()
            if max(y1, y2) < -100 or min(y1, y2) > self.height() + 100:
                continue
            centre = self.lane_center(tail.lane)
            target = QRectF(
                centre - note_size / 2,
                min(y1, y2),
                note_size,
                max(2.0, abs(y2 - y1)),
            )
            bank = (
                None
                if self._noteskin_pack is None
                else self._noteskin_pack.bank(head.raw[2])
            )
            drawn = False
            painter.save()
            painter.setOpacity(self._event_opacity(head))
            if bank is not None:
                frame = int(max(0.0, self._chart_time_ms) // 80) % len(
                    bank.animation
                )
                atlas = bank.animation[frame]
                pixmap = self._pixmap(atlas)
                if pixmap is not None:
                    atlas_lane = (
                        self.start_column + self._visual_lane(tail.lane)
                    ) % 5
                    tile_x, tile_y, tile_width, _ = atlas.tile(atlas_lane, 0)
                    painter.drawPixmap(
                        target,
                        pixmap,
                        QRectF(tile_x, tile_y, tile_width, 8),
                    )
                    drawn = True
            if not drawn:
                width = max(8.0, note_size * 0.34)
                painter.fillRect(
                    QRectF(
                        centre - width / 2,
                        min(y1, y2),
                        width,
                        max(2.0, abs(y2 - y1)),
                    ),
                    QColor(88, 160, 230, 210),
                )
            painter.restore()

    def _draw_sequence_zone(
        self,
        painter: QPainter,
        geometry: PlayfieldGeometry,
        receptor_y: float,
    ) -> None:
        if self.command.freedom or self.session.runtime_modifier.freedom:
            return
        bank = None if self._noteskin_pack is None else self._noteskin_pack.bank(0)
        if bank is not None and bank.base is not None:
            pixmap = self._pixmap(bank.base)
            if pixmap is not None:
                # Prime draws BASE twice for Double (HD1+HD2 is the distinct
                # Half Double path). The HD atlas keeps the functional five-
                # lane strip in its central 384 px; the 48 px sides are empty.
                # Map that useful strip to exactly five pitches. R9 cropped it
                # but stretched it over six pitches; R10 retained the empty
                # sides and consequently recreated a Versus-style centre gap.
                source = QRectF(48.0, 0.0, 384.0, 96.0)
                for panel in range(geometry.panel_count):
                    target = QRectF(
                        geometry.panel_left(panel),
                        receptor_y - geometry.note_size / 2,
                        geometry.panel_width,
                        geometry.note_size,
                    )
                    painter.drawPixmap(target, pixmap, source)
                return
        lane_map = self._lane_map()
        for visual_lane in range(self.columns):
            centre = geometry.lane_center(visual_lane)
            rect = QRectF(
                centre - geometry.note_size / 2,
                receptor_y - geometry.note_size / 2,
                geometry.note_size,
                geometry.note_size,
            )
            source_lane = lane_map[visual_lane]
            painter.setPen(QPen(QColor("#b7c7e8"), 2.0))
            painter.setBrush(
                QColor("#5676a8")
                if source_lane in self.session.pressed_lanes
                else QColor(35, 46, 68, 210)
            )
            painter.drawRoundedRect(rect, 8, 8)

    def paintEvent(self, event) -> None:
        paint_started = perf_counter()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#05070b"))
        geometry = self._geometry()
        left = geometry.left
        field_width = geometry.field_width
        painter.fillRect(
            QRectF(left, 0.0, field_width, float(self.height())), QColor("#10141e")
        )
        receptor_y = self._receptor_y()
        sx, sy, tx, ty = self._sequence_affine()
        painter.save()
        painter.setTransform(QTransform(sx, 0.0, 0.0, sy, tx, ty), True)
        if self._show_guide:
            painter.setPen(QPen(QColor("#ffd166"), 1.0, Qt.PenStyle.DashLine))
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

        stats = self.session.stats
        painter.setPen(QColor("#ffffff"))
        if self.session.last_judgment is not None:
            painter.drawText(
                QRectF(left, 142, field_width, 40),
                Qt.AlignmentFlag.AlignCenter,
                self._judgment_text(self.session.last_judgment),
            )
        if stats.combo > 1:
            painter.drawText(
                QRectF(left, 178, field_width, 28),
                Qt.AlignmentFlag.AlignCenter,
                f"{stats.combo} COMBO",
            )

        mode = "AUTO" if self.session.autoplay else "MANUAL"
        painter.setPen(QColor("#d7dbe5"))
        painter.drawText(
            QRectF(12, self.height() - 28, self.width() - 24, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{mode} · {self.session.selected_speed:g}x · "
            f"{self._chart_time_ms / 1000:.3f}s · "
            f"{self.field_mode} · COMMAND {self.command.raw or '—'}",
        )
        if self._show_debug:
            self._draw_debug(painter, left, field_width)
        painted_at = perf_counter()
        self._paint_timestamps.append(painted_at)
        self._paint_cost_ms = (painted_at - paint_started) * 1000.0

    def _judgment_text(self, judgment: Judgment) -> str:
        if not (
            self.command.judge_reverse or self.session.runtime_modifier.judge_reverse
        ):
            return judgment.value
        return {
            Judgment.PERFECT: Judgment.MISS,
            Judgment.GREAT: Judgment.BAD,
            Judgment.GOOD: Judgment.GOOD,
            Judgment.BAD: Judgment.GREAT,
            Judgment.MISS: Judgment.PERFECT,
        }[judgment].value

    def _draw_debug(self, painter: QPainter, left: float, width: float) -> None:
        stats = self.session.stats
        position = self.stream.position_at(self._chart_time_ms)
        speed_factor = self.stream.speed_factor_at(self._chart_time_ms)
        fps = 0.0
        if len(self._paint_timestamps) >= 2:
            elapsed = self._paint_timestamps[-1] - self._paint_timestamps[0]
            if elapsed > 0.0:
                fps = (len(self._paint_timestamps) - 1) / elapsed
        lines = (
            (
                f"TIME {self._chart_time_ms:10.3f} ms   POS {position:9.3f}  "
                f"BLOCK {speed_factor:7.3f}  HIGH {self.session.high_speed:7.3f}"
            ),
            (
                f"SPEEDMODE {self.session.speed_mode.name}  "
                f"ACCDEC {self._effective_acc_dec().name}  "
                f"THROW {self._effective_throw().name}"
            ),
            f"RENDER {fps:6.1f} fps  PAINT {self._paint_cost_ms:6.2f} ms",
            (
                "LOCAL P/G/GD/B/M "
                f"{stats.perfect}/{stats.great}/{stats.good}/{stats.bad}/{stats.miss}"
            ),
            f"LOCAL COMBO {stats.combo}  MAX {stats.max_combo}  SCORE {stats.score}",
            (
                f"LOCAL GAUGE {stats.gauge}/{self.session.gauge_limit}  "
                f"ROUTE {self.stream.route.policy.value}"
            ),
            (
                f"AUTO {int(self.session.autoplay)}  "
                f"GUIDE {int(self._show_guide)}  WORLD {int(self._world_tour)}"
            ),
            (
                f"TRANSFORM {int(self._sequence_transform())}  "
                f"APPROX {','.join(self.command.approximate_effects) or '-'}  "
                f"PENDING {','.join(self.command.pending_effects) or '-'}"
            ),
        )
        rect = QRectF(left + 8, 220, width - 16, len(lines) * 20 + 12)
        painter.fillRect(rect, QColor(0, 0, 0, 205))
        painter.setPen(QColor("#79ff8c"))
        for index, line in enumerate(lines):
            painter.drawText(rect.adjusted(8, 5 + index * 20, -8, 0), line)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            event.accept()
            return
        key = event.key()
        keypad_five = key == Qt.Key.Key_5 and bool(
            event.modifiers() & Qt.KeyboardModifier.KeypadModifier
        )
        if key == Qt.Key.Key_F6:
            self._show_debug = not self._show_debug
        elif key == Qt.Key.Key_F8:
            enabled = self.session.toggle_autoplay()
            self.statusChanged.emit(f"Autoplay {'on' if enabled else 'off'}")
        elif key == Qt.Key.Key_F9:
            self._show_guide = not self._show_guide
        elif key == Qt.Key.Key_F11:
            self._world_tour = not self._world_tour
        elif key == Qt.Key.Key_Space:
            self.seekRequested.emit(self._chart_time_ms + 5000.0)
        elif key == Qt.Key.Key_Escape:
            self.exitRequested.emit()
        elif keypad_five:
            self._press_global_pad(7)
        elif Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            self.session.select_speed(key - Qt.Key.Key_0)
            self._refresh_tooltip()
            self.statusChanged.emit(f"Speed {self.session.selected_speed:g}x")
        elif key in _PAD_KEYS:
            self._press_global_pad(_PAD_KEYS[key])
        else:
            super().keyPressEvent(event)
            return
        self.update()
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        keypad_five = event.key() == Qt.Key.Key_5 and bool(
            event.modifiers() & Qt.KeyboardModifier.KeypadModifier
        )
        if not event.isAutoRepeat() and (event.key() in _PAD_KEYS or keypad_five):
            global_lane = 7 if keypad_five else _PAD_KEYS[event.key()]
            visual_lane = global_lane - self.start_column
            if 0 <= visual_lane < self.columns:
                self.session.release(self._screen_lane_to_source(visual_lane))
                self.update()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _press_global_pad(self, global_lane: int) -> None:
        visual_lane = global_lane - self.start_column
        if 0 <= visual_lane < self.columns:
            self.session.press(
                self._screen_lane_to_source(visual_lane), self._chart_time_ms
            )
