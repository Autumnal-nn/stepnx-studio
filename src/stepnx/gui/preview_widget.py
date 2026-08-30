from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import deque
from time import perf_counter

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
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
from stepnx.preview.geometry import (
    PlayfieldGeometry,
    PlayfieldStyle,
    default_playfield_style,
)
from stepnx.preview.legacy_render import (
    legacy_nx_homography,
    legacy_visibility_gradient_stops,
)
from stepnx.preview.modifiers import AccDecMode, SequenceZoneTransform, ThrowMode
from stepnx.preview.session import GameplaySession, Judgment
from stepnx.preview.speed import native_base_velocity_pixels
from stepnx.preview.visuals import (
    LEGACY_ACCEL_LIMIT,
    LEGACY_ACCDEC_PATH_UNIT,
    LINE_BASE_ACC_OFFSET,
    legacy_acc_dec_distance,
    legacy_exceed_x_offset,
    native_line_local_y,
    native_line_y,
    native_screen_y,
    prime2_snake_path_lane_position,
    prime2_snake_x_offset,
    prime2_throw_perspective_scale,
    prime2_throw_z_offset,
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
        # Long bodies (0xB) participate in judgment/runtime state, but the
        # renderer never draws them as standalone notes. Keep a separate draw
        # index so pathological BeatSplit=128 holds do not make paintEvent walk
        # thousands of invisible body ticks every frame.
        self._render_events = tuple(
            event for event in stream.events if event.note_type != 0xB
        )
        self._render_event_times = tuple(
            event.time_ms for event in self._render_events
        )
        self._duration_ms = stream.duration_ms
        self._hold_pairs = self._pair_holds(stream.events)
        self._hold_pair_by_event = {
            event: (head, tail)
            for head, tail in self._hold_pairs
            for event in (head, tail)
        }
        hold_pairs_by_visibility: dict[int, list[tuple[PreviewEvent, PreviewEvent]]] = {
            0: [], 1: [], 2: [], 3: []
        }
        for head, tail in self._hold_pairs:
            visibility = resolved_command.effective_visibility(int(head.visibility))
            hold_pairs_by_visibility.setdefault(visibility, []).append((head, tail))
        self._hold_pairs_by_visibility = {
            visibility: tuple(pairs)
            for visibility, pairs in hold_pairs_by_visibility.items()
        }
        # Shaft rendering is an interval query, not a chart-tail scan. Keep both
        # endpoint orders so each frame can approach the visible window from the
        # cheaper side while preserving arbitrarily long holds that span it.
        self._hold_head_times_by_visibility = {
            visibility: tuple(head.time_ms for head, _ in pairs)
            for visibility, pairs in self._hold_pairs_by_visibility.items()
        }
        self._hold_pairs_by_tail_visibility = {
            visibility: tuple(sorted(pairs, key=lambda pair: pair[1].time_ms))
            for visibility, pairs in self._hold_pairs_by_visibility.items()
        }
        self._hold_tail_times_by_visibility = {
            visibility: tuple(tail.time_ms for _, tail in pairs)
            for visibility, pairs in self._hold_pairs_by_tail_visibility.items()
        }
        self._render_time_window: tuple[float, float] | None = None

        self._lane_map_cache = resolved_command.lane_map(
            self.columns, seed=stream.route.seed or 0
        )
        inverse_lanes = list(range(self.columns))
        for visual_lane, source_lane in enumerate(self._lane_map_cache):
            if 0 <= source_lane < self.columns:
                inverse_lanes[source_lane] = visual_lane
        self._visual_lane_cache = tuple(inverse_lanes)

        block_styles: dict[int, PlayfieldStyle] = {}
        for block_id, params in stream.block_step_params:
            for param in params:
                if param.metadata_id != 200:
                    continue
                try:
                    block_styles[block_id] = PlayfieldStyle(param.raw_value)
                except ValueError:
                    pass
                break
        self._block_playfield_styles = block_styles
        self._native_state_time = 0.0
        self._native_state = stream.native_state_at(0.0)
        self._geometry_cache_key: tuple[float, PlayfieldStyle] | None = None
        self._geometry_cache: PlayfieldGeometry | None = None

        self._paint_timestamps: deque[float] = deque(maxlen=120)
        self._paint_cost_ms = 0.0
        self._advance_cost_ms = 0.0
        self._host_paint_cost_ms = 0.0
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
        self._native_state_time = self._chart_time_ms
        self._native_state = self.stream.native_state_at(self._chart_time_ms)
        advance_started = perf_counter()
        self.session.advance(self._chart_time_ms)
        self._advance_cost_ms = (perf_counter() - advance_started) * 1000.0
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

    def _default_playfield_style(self) -> PlayfieldStyle:
        return default_playfield_style(self.columns)

    def _current_native_state(self):
        timing = self.stream.native_timing
        if timing is None:
            return None
        if self._native_state_time != self._chart_time_ms:
            self._native_state_time = self._chart_time_ms
            self._native_state = timing.state_at(self._chart_time_ms)
        return self._native_state

    def _active_playfield_style(self) -> PlayfieldStyle:
        """Resolve the active Prime-style judge-line layout.

        Division Metadata 200 is block-local and must be re-evaluated whenever
        native timing selects a different block. Missing/unknown values fall
        back to StepNX's launch default without mutating chart structure.
        """

        default = self._default_playfield_style()
        timing = self.stream.native_timing
        state = self._current_native_state()
        if timing is None or not timing.blocks or state is None:
            return default
        block_id = timing.blocks[state.block_index].block_id
        return self._block_playfield_styles.get(block_id, default)

    def _geometry(self) -> PlayfieldGeometry:
        width = max(1.0, float(self.width()))
        style = self._active_playfield_style()
        key = (width, style)
        if self._geometry_cache_key != key or self._geometry_cache is None:
            self._geometry_cache_key = key
            self._geometry_cache = PlayfieldGeometry(
                width,
                self.columns,
                style,
                self.start_column,
            )
        return self._geometry_cache

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

    def _effective_nx_mode(self) -> bool:
        return bool(self.command.nx_mode or self.session.runtime_modifier.nx)

    def _playfield_transform(self, z: float = 0.0) -> QTransform:
        transform = self._sequence_transform()
        if self._effective_nx_mode():
            return QTransform(
                *legacy_nx_homography(
                    float(self.width()),
                    float(self.height()),
                    z=float(z),
                    drop=bool(transform & SequenceZoneTransform.DROP),
                    under_attack=bool(
                        transform & SequenceZoneTransform.UNDER_ATTACK
                    ),
                )
            )
        sx, sy, tx, ty = self._sequence_affine()
        return QTransform(sx, 0.0, 0.0, sy, tx, ty)

    def _lane_map(self) -> tuple[int, ...]:
        return self._lane_map_cache

    def _screen_lane_to_source(self, visual_lane: int) -> int:
        lane = int(visual_lane)
        if self._sequence_transform() & SequenceZoneTransform.UNDER_ATTACK:
            lane = self.columns - 1 - lane
        return self._lane_map()[lane]

    def _visual_lane(self, source_lane: int) -> int:
        lane = int(source_lane)
        if 0 <= lane < len(self._visual_lane_cache):
            return self._visual_lane_cache[lane]
        return lane

    def lane_center(self, source_lane: int) -> float:
        """Return the shared horizontal centre for one source lane."""
        return self._geometry().lane_center(self._visual_lane(source_lane))

    def _lane_position_x(self, visual_lane_position: float) -> float:
        """Project a fractional visual-lane coordinate into the active layout."""

        return self._geometry().lane_position(float(visual_lane_position))

    def _legacy_command_acc_dec(self) -> AccDecMode:
        """Resolve PIUTESTER/NX2 A/D without conflating it with R!SE Header 2."""

        mode = AccDecMode.LINEAR
        for character in self.command.raw:
            if character == "d":
                mode = AccDecMode.DECELERATION
            elif character == "a":
                mode = AccDecMode.ACCELERATION
        return mode

    def _effective_acc_dec(self) -> AccDecMode:
        legacy = self._legacy_command_acc_dec()
        return (
            legacy
            if legacy is not AccDecMode.LINEAR
            else self.session.runtime_modifier.acc_dec
        )

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
        return self.stream.beat_distance_at(
            event,
            self._chart_time_ms,
            state=self._current_native_state(),
        )

    def _event_local_y(self, event: PreviewEvent) -> float:
        # Header ID 2 remains the modern R!SE LineBase curve. Historical A/D
        # commands use a distinct Prime/NXA renderer and are applied in screen Y.
        return native_line_local_y(
            self._event_beat_distance(event), self.session.runtime_modifier.acc_dec
        )

    def _event_native_y(self, event: PreviewEvent) -> float:
        return native_line_y(
            self._event_beat_distance(event),
            self.session.high_speed,
            self.session.runtime_modifier.acc_dec,
        )

    def _path_anchor(
        self, event: PreviewEvent
    ) -> tuple[PreviewEvent, float]:
        """Return the rigid path anchor used by legacy long notes."""

        pair = self._hold_pair_by_event.get(event)
        if pair is None:
            return event, self._event_beat_distance(event)
        head, tail = pair
        if head.time_ms <= self._chart_time_ms <= tail.time_ms:
            return head, 0.0
        return head, self._event_beat_distance(head)

    def _throw_projection(
        self, x: float, y: float, beat_distance: float
    ) -> tuple[float, float, float]:
        """Project legacy Throw when NX Mode is not handling the 3-D plane."""

        mode = self._effective_throw()
        if mode is ThrowMode.FLAT:
            return float(x), float(y), 1.0
        z = prime2_throw_z_offset(
            beat_distance,
            self.session.high_speed,
            rise=mode is ThrowMode.RISE,
            alternate_amplitude=self._effective_nx_mode(),
        )
        if self._effective_nx_mode():
            # NX's fixed-Z QTransform below performs the source perspective.
            return float(x), float(y), 1.0
        scale = prime2_throw_perspective_scale(z)
        centre_x = float(self.width()) / 2.0
        centre_y = float(self.height()) / 2.0
        return (
            centre_x + (float(x) - centre_x) * scale,
            centre_y + (float(y) - centre_y) * scale,
            scale,
        )

    def _event_throw_z(self, event: PreviewEvent) -> float:
        mode = self._effective_throw()
        if mode is ThrowMode.FLAT:
            return 0.0
        _, beat_distance = self._path_anchor(event)
        return prime2_throw_z_offset(
            beat_distance,
            self.session.high_speed,
            rise=mode is ThrowMode.RISE,
            alternate_amplitude=self._effective_nx_mode(),
        )

    def _base_screen_y_for_beat_distance(self, beat_distance: float) -> float:
        geometry = self._geometry()
        legacy_mode = self._legacy_command_acc_dec()
        if legacy_mode is not AccDecMode.LINEAR:
            return self._receptor_y() + legacy_acc_dec_distance(
                beat_distance,
                self.session.high_speed,
                geometry.path_unit,
                legacy_mode,
            )
        if self.command.exceed_mode or self.session.runtime_modifier.exceed:
            # Prime/NXA path_exeed shares its unbounded linear distance with
            # both axes. Keeping R!SE's 65.647/72 Y projection here made the
            # diagonal about ten percent too shallow even after X was fixed.
            return self._receptor_y() + legacy_acc_dec_distance(
                beat_distance,
                self.session.high_speed,
                geometry.path_unit,
                AccDecMode.LINEAR,
            )
        native_y = native_line_y(
            beat_distance,
            self.session.high_speed,
            self.session.runtime_modifier.acc_dec,
        )
        return native_screen_y(
            native_y,
            self._receptor_y(),
            geometry.note_size,
        )

    def _event_y(self, event: PreviewEvent) -> float:
        return self._base_screen_y_for_beat_distance(self._event_beat_distance(event))

    def _event_x_offset(self, event: PreviewEvent) -> float:
        geometry = self._geometry()
        _, beat_distance = self._path_anchor(event)
        offset = 0.0

        # NX20 Snake Path is a per-note VisualEffect bit. It is not Header 35
        # ZigZag and it is not Header 34 / COMMAND z global Snake. The selected
        # block supplies its phase start (222) and phase length (221).
        if event.snake_path:
            visual_lane = self._visual_lane(event.lane)
            lane_position = prime2_snake_path_lane_position(
                visual_lane,
                beat_distance,
                self.columns,
                self.stream.route.seed or 0,
                start=self.stream.block_param(event.block_id, 222, 1.0),
                interval=self.stream.block_param(event.block_id, 221, 1.0),
            )
            offset += self._lane_position_x(lane_position) - self.lane_center(event.lane)

        # Header 35 ZigZag remains effective state only until its distinct
        # rendering equation is recovered. Do not alias it to Snake Path.
        if self.command.snake or self.session.runtime_modifier.snake:
            offset += prime2_snake_x_offset(beat_distance, geometry.path_unit)

        if self.command.exceed_mode or self.session.runtime_modifier.exceed:
            if self.columns <= 5:
                # Prime stores one signed bank offset for the selected Single
                # player. P1 approaches from the right; P2 approaches from left.
                from_right = self.start_column < 5
            else:
                # Double keeps the two native five-lane bank origins: bank 0 gets
                # +d and bank 1 gets -d. Do not normalize against field width.
                from_right = (self.start_column + self._visual_lane(event.lane)) < 5
            offset += legacy_exceed_x_offset(
                beat_distance,
                self.session.high_speed,
                geometry.path_unit,
                from_right=from_right,
            )
        return offset

    def _screen_y_for_beat_distance(self, beat_distance: float) -> float:
        return self._base_screen_y_for_beat_distance(beat_distance)

    def _event_render_geometry(
        self, event: PreviewEvent
    ) -> tuple[float, float, float]:
        centre_x = self.lane_center(event.lane) + self._event_x_offset(event)
        centre_y = self._event_y(event)
        if self._effective_nx_mode():
            return centre_x, centre_y, self._geometry().note_size
        _, beat_distance = self._path_anchor(event)
        centre_x, centre_y, scale = self._throw_projection(
            centre_x, centre_y, beat_distance
        )
        return centre_x, centre_y, self._geometry().note_size * scale

    def _effective_visibility(self, event: PreviewEvent) -> int:
        return self.command.effective_visibility(int(event.visibility))

    def _flash_visible(self) -> bool:
        return self.command.flash_visible(
            self._chart_time_ms,
            header_flash=self.session.runtime_modifier.flash,
        )

    def _visible_events_from(
        self,
        events: tuple[PreviewEvent, ...],
        event_times: tuple[float, ...],
    ) -> tuple[PreviewEvent, ...]:
        # paintEvent calls this once before drawing notes and shafts. Store the
        # exact time-domain projection of its screen-space culling window so
        # long shafts can share it instead of examining the rest of the chart.
        self._render_time_window = None
        geometry = self._geometry()
        # Accel/Decel can add up to 200 native Y units outside the linear
        # projection. Include that exact bound in culling so transformed notes
        # are not discarded before _event_y() evaluates them.
        margin = 130.0 + abs(LINE_BASE_ACC_OFFSET) * (
            geometry.note_size / 72.0
        )
        if self._legacy_command_acc_dec() is not AccDecMode.LINEAR:
            margin += LEGACY_ACCEL_LIMIT * (
                geometry.path_unit / LEGACY_ACCDEC_PATH_UNIT
            )
        if self._effective_throw() is not ThrowMode.FLAT:
            margin += 100.0 * (geometry.note_size / 72.0)
        if self._effective_nx_mode():
            # The NX homography can project local coordinates well outside the
            # ordinary flat viewport back into the visible trapezoid.
            margin += float(self.height()) * 2.0
        if self._sequence_transform() & SequenceZoneTransform.MID:
            margin += abs(float(self.height()) / 2.0 - self._receptor_y())
        timing = self.stream.timing
        if not timing or not events:
            return ()
        # The native position axis clamps after the route endpoint. Keep the
        # explicit time-domain guard so the last notes cannot reappear forever.
        if self._chart_time_ms > self._duration_ms + 250.0:
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
        self._render_time_window = (
            min(time_bounds) - 250.0,
            max(time_bounds) + 250.0,
        )
        first = bisect_left(event_times, self._render_time_window[0])
        last = bisect_right(event_times, self._render_time_window[1])
        return tuple(
            event
            for event in events[first:last]
            if -margin <= self._event_y(event) <= self.height() + margin
        )

    def visible_events(self) -> tuple[PreviewEvent, ...]:
        """Return all visible runtime events, including long-body judgment ticks."""

        return self._visible_events_from(self.stream.events, self._event_times)

    def _visible_render_events(self) -> tuple[PreviewEvent, ...]:
        """Return only events that can produce standalone draw calls."""

        return self._visible_events_from(self._render_events, self._render_event_times)

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

    def _visible_hold_pairs(
        self, visibility_filter: int
    ) -> tuple[tuple[PreviewEvent, PreviewEvent], ...]:
        """Return holds whose [head, tail] interval overlaps the draw window.

        The old renderer walked every hold whose tail had not passed yet. On
        dense charts that made frame cost proportional to the *remaining song*:
        expensive at the start and progressively cheaper toward the end.
        """

        window = self._render_time_window
        if window is None:
            return ()
        visibility = int(visibility_filter)
        pairs_by_head = self._hold_pairs_by_visibility.get(visibility, ())
        if not pairs_by_head:
            return ()
        head_times = self._hold_head_times_by_visibility.get(visibility, ())
        pairs_by_tail = self._hold_pairs_by_tail_visibility.get(visibility, ())
        tail_times = self._hold_tail_times_by_visibility.get(visibility, ())
        window_start, window_end = window

        head_last = bisect_right(head_times, window_end)
        tail_first = bisect_left(tail_times, window_start)

        # Query from whichever endpoint leaves fewer candidates. Filtering the
        # opposite endpoint keeps long holds spanning the complete window. This
        # avoids the previous O(all future holds) behaviour without imposing a
        # maximum hold duration or assuming monotonic scrolling.
        if head_last <= len(pairs_by_tail) - tail_first:
            candidates = pairs_by_head[:head_last]
        else:
            candidates = pairs_by_tail[tail_first:]
        return tuple(
            (head, tail)
            for head, tail in candidates
            if head.time_ms <= window_end and tail.time_ms >= window_start
        )

    @staticmethod
    def _hold_shaft_height(
        y1: float,
        y2: float,
        rendered_note_size: float,
        *,
        head_terminal_visible: bool,
        tail_terminal_visible: bool,
    ) -> float:
        span = abs(float(y2) - float(y1))
        # Subpixel endpoint noise must not manufacture a visible long body.
        if span <= 0.5:
            return 0.0
        # When both terminal quads are still present, there is no exposed shaft
        # until their screen-space silhouettes stop overlapping.
        if (
            head_terminal_visible
            and tail_terminal_visible
            and span <= max(1.0, float(rendered_note_size))
        ):
            return 0.0
        return span

    def _draw_hold_shafts(
        self,
        painter: QPainter,
        note_size: float,
        visibility_filter: int,
    ) -> None:
        for head, tail in self._visible_hold_pairs(visibility_filter):
            if tail.time_ms < self._chart_time_ms - 80.0:
                continue

            y1 = self._event_y(head)
            y2 = self._event_y(tail)
            if head.time_ms <= self._chart_time_ms <= tail.time_ms:
                y1 = self._receptor_y()
            anchor_x = self.lane_center(head.lane) + self._event_x_offset(head)
            _, anchor_distance = self._path_anchor(head)
            if self._effective_nx_mode():
                x1 = x2 = anchor_x
                scale = 1.0
            else:
                x1, y1, scale = self._throw_projection(
                    anchor_x, y1, anchor_distance
                )
                x2, y2, _ = self._throw_projection(
                    anchor_x, y2, anchor_distance
                )
            centre = (x1 + x2) / 2.0
            rendered_note_size = note_size * scale
            head_visible = (
                self.session.event_key(head) not in self.session.judgments
                or head.time_ms >= self._chart_time_ms - 80.0
            )
            tail_visible = (
                self.session.event_key(tail) not in self.session.judgments
                or tail.time_ms >= self._chart_time_ms - 80.0
            )
            shaft_height = self._hold_shaft_height(
                y1,
                y2,
                rendered_note_size,
                head_terminal_visible=head_visible,
                tail_terminal_visible=tail_visible,
            )
            if shaft_height <= 0.0:
                continue
            if (
                not self._effective_nx_mode()
                and (max(y1, y2) < -100 or min(y1, y2) > self.height() + 100)
            ):
                continue
            target = QRectF(
                centre - rendered_note_size / 2,
                min(y1, y2),
                rendered_note_size,
                shaft_height,
            )
            bank = (
                None
                if self._noteskin_pack is None
                else self._noteskin_pack.bank(head.raw[2])
            )
            drawn = False
            painter.save()
            try:
                if self._effective_nx_mode():
                    painter.setTransform(
                        self._playfield_transform(self._event_throw_z(head)),
                        False,
                    )
                if bank is not None:
                    frame = int(max(0.0, self._chart_time_ms) // 80) % len(
                        bank.animation
                    )
                    atlas = bank.animation[frame]
                    pixmap = self._pixmap(atlas)
                    if pixmap is not None:
                        atlas_lane = (
                            self.start_column + self._visual_lane(head.lane)
                        ) % 5
                        tile_x, tile_y, tile_width, _ = atlas.tile(atlas_lane, 0)
                        painter.drawPixmap(
                            target,
                            pixmap,
                            QRectF(tile_x, tile_y, tile_width, 8),
                        )
                        drawn = True
                if not drawn:
                    width = max(8.0, rendered_note_size * 0.34)
                    painter.fillRect(
                        QRectF(
                            centre - width / 2,
                            min(y1, y2),
                            width,
                            shaft_height,
                        ),
                        QColor(88, 160, 230, 210),
                    )
            finally:
                painter.restore()

    def _projected_note_centre_and_extent(
        self, event: PreviewEvent
    ) -> tuple[QPointF, float]:
        centre_x, centre_y, rendered_note_size = self._event_render_geometry(event)
        transform = self._playfield_transform(
            self._event_throw_z(event) if self._effective_nx_mode() else 0.0
        )
        centre = transform.map(QPointF(centre_x, centre_y))
        top = transform.map(
            QPointF(centre_x, centre_y - rendered_note_size / 2.0)
        )
        bottom = transform.map(
            QPointF(centre_x, centre_y + rendered_note_size / 2.0)
        )
        extent = math.hypot(bottom.x() - top.x(), bottom.y() - top.y())
        return centre, max(1.0, extent)

    def _collapsed_hold_tail(self, event: PreviewEvent) -> bool:
        if event.note_type != 0xF:
            return False
        pair = self._hold_pair_by_event.get(event)
        if pair is None:
            return False
        head, tail = pair
        head_centre, head_extent = self._projected_note_centre_and_extent(head)
        tail_centre, tail_extent = self._projected_note_centre_and_extent(tail)
        distance = math.hypot(
            tail_centre.x() - head_centre.x(),
            tail_centre.y() - head_centre.y(),
        )
        return distance <= max(head_extent, tail_extent) + 1e-6

    def _draw_note_group(
        self,
        painter: QPainter,
        geometry: PlayfieldGeometry,
        visibility_filter: int,
        visible_notes: tuple[PreviewEvent, ...] | list[PreviewEvent] | None = None,
    ) -> None:
        self._draw_hold_shafts(painter, geometry.note_size, visibility_filter)
        notes = self._visible_render_events() if visible_notes is None else visible_notes
        # The native game collapses a hold whose complete projected length fits
        # underneath one terminal into the head silhouette. Shaft is already
        # suppressed by _hold_shaft_height; suppress the covered tail too.
        drawable_notes = tuple(
            note for note in notes if not self._collapsed_hold_tail(note)
        )
        ordered_notes = tuple(
            note for note in drawable_notes if note.note_type != 0x7
        ) + tuple(note for note in drawable_notes if note.note_type == 0x7)
        for note in ordered_notes:
            if self._effective_visibility(note) != int(visibility_filter):
                continue
            key = self.session.event_key(note)
            if (
                key in self.session.judgments
                and note.time_ms < self._chart_time_ms - 80
            ):
                continue
            centre_x, centre_y, rendered_note_size = self._event_render_geometry(note)
            rect = QRectF(
                centre_x - rendered_note_size / 2,
                centre_y - rendered_note_size / 2,
                rendered_note_size,
                rendered_note_size,
            )
            painter.save()
            try:
                if self._effective_nx_mode():
                    painter.setTransform(
                        self._playfield_transform(self._event_throw_z(note)),
                        False,
                    )
                if not self._draw_asset(painter, note, rect):
                    self._fallback_note(painter, note.note_type, rect)
            finally:
                painter.restore()

    def _render_visibility_layer(
        self,
        geometry: PlayfieldGeometry,
        visibility: int,
        visible_notes: tuple[PreviewEvent, ...] | list[PreviewEvent],
    ) -> QImage:
        image = QImage(self.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        layer = QPainter(image)
        try:
            layer.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            layer.setTransform(self._playfield_transform(), False)
            self._draw_note_group(
                layer, geometry, visibility, visible_notes=visible_notes
            )
        finally:
            layer.end()

        mask = QPainter(image)
        try:
            mask.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationIn
            )
            gradient = QLinearGradient(0.0, 0.0, 0.0, float(self.height()))
            for position, alpha in legacy_visibility_gradient_stops(visibility):
                colour = QColor(255, 255, 255)
                colour.setAlphaF(float(alpha))
                gradient.setColorAt(float(position), colour)
            mask.fillRect(
                QRectF(0.0, 0.0, float(self.width()), float(self.height())),
                QBrush(gradient),
            )
        finally:
            mask.end()
        return image

    def _active_hold_visibilities(self) -> frozenset[int]:
        time_ms = self._chart_time_ms
        active: set[int] = set()
        for visibility in (1, 2):
            if any(
                head.time_ms <= time_ms <= tail.time_ms
                for head, tail in self._visible_hold_pairs(visibility)
            ):
                active.add(visibility)
        return frozenset(active)

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
        playfield_transform = self._playfield_transform()
        painter.save()
        painter.setTransform(playfield_transform, False)
        if self._show_guide:
            painter.setPen(QPen(QColor("#ffd166"), 1.0, Qt.PenStyle.DashLine))
            painter.drawLine(
                QPointF(left, receptor_y), QPointF(left + field_width, receptor_y)
            )
        self._draw_sequence_zone(painter, geometry, receptor_y)
        flash_visible = self._flash_visible()
        visible_by_visibility: dict[int, list[PreviewEvent]] = {1: [], 2: [], 3: []}
        if flash_visible:
            for note in self._visible_render_events():
                visibility = self._effective_visibility(note)
                if visibility in visible_by_visibility:
                    visible_by_visibility[visibility].append(note)
            self._draw_note_group(
                painter,
                geometry,
                3,
                visible_notes=visible_by_visibility[3],
            )
        painter.restore()

        if flash_visible:
            # NXA/Prime apply Appear/Vanish through a screen-space alpha texture.
            # Full-size intermediate images are expensive, so create them only
            # when a transition-family note is visible or a matching long is
            # currently held across the receptor.
            active_hold_visibilities = self._active_hold_visibilities()
            for visibility in (1, 2):
                notes = visible_by_visibility[visibility]
                if not notes and visibility not in active_hold_visibilities:
                    continue
                layer = self._render_visibility_layer(
                    geometry, visibility, visible_notes=notes
                )
                painter.drawImage(0, 0, layer)

        painter.save()
        painter.setTransform(playfield_transform, False)
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
            (
                f"RENDER {fps:6.1f} fps  PAINT {self._paint_cost_ms:6.2f} ms  "
                f"ADV {self._advance_cost_ms:6.2f} ms  "
                f"HOST {self._host_paint_cost_ms:6.2f} ms  "
                f"E/G {self.session.last_advance_event_count}/"
                f"{self.session.last_advance_group_count}"
            ),
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
