from __future__ import annotations

from math import ceil, isfinite

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractScrollArea

from stepnx.authoring.audio import AudioAlignment, WaveformEnvelope
from stepnx.authoring.glyphs import VisualPack
from stepnx.authoring.noteskin import LocalNoteskinPack, PngAtlas, hold_atlas_plan
from stepnx.authoring.selection import CellSelection, CellTarget
from stepnx.authoring.snapshot import AuthoringSnapshot
from stepnx.authoring.timeline import TimelineGeometry, TimelineLayout
from stepnx.core.model import EmptyRow, LightmapRow, NoteRow, PackedNoteRow

_NOTE_COLORS = {
    0x1: QColor("#df8b42"),
    0x2: QColor("#b76dd8"),
    0x3: QColor("#62b8ff"),
    0x7: QColor("#8bc7ff"),
    0xB: QColor("#5f91cf"),
    0xF: QColor("#8bc7ff"),
}

_PLAYHEAD_VIEWPORT_FRACTION = 0.07


class TimelineWidget(QAbstractScrollArea):
    snapshotChanged = Signal(object)
    inspectionRequested = Signal(int, int)
    noteEditRequested = Signal(int, int)
    holdEditRequested = Signal(object, int)
    contextStructureRequested = Signal(int, int, object)
    editGestureStarted = Signal()
    editGestureFinished = Signal()
    selectedCellsChanged = Signal(object)

    def __init__(self, snapshot: AuthoringSnapshot, parent=None) -> None:
        super().__init__(parent)
        self._snapshot = snapshot
        self._geometry = TimelineGeometry()
        self._layout = TimelineLayout(snapshot, self._geometry)
        self._visual_pack: VisualPack | None = None
        self._noteskin_pack: LocalNoteskinPack | None = None
        self._glyph_pixmaps: dict[str, QPixmap] = {}
        self._atlas_pixmaps: dict[str, QPixmap] = {}
        self._hold_terminal_pixmaps: dict[tuple[str, int, int, bool], QPixmap] = {}
        self._selection = CellSelection()
        self._selection_mode = False
        self._drag_start = None
        self._drag_current = None
        self._snap_beats = 0.0
        self._waveform: WaveformEnvelope | None = None
        self._audio_alignment = AudioAlignment()
        self._playback_time_ms: float | None = None
        self._playback_y: float | None = None
        self._playback_active = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._sync_scrollbars()

    @property
    def snapshot(self) -> AuthoringSnapshot:
        return self._snapshot

    def set_snapshot(self, snapshot: AuthoringSnapshot) -> None:
        self._snapshot = snapshot
        self._layout = TimelineLayout(
            snapshot, self._geometry, playback=self._playback_active
        )
        self._playback_y = (
            None
            if self._playback_time_ms is None
            else self._layout.y_for_chart_time(self._playback_time_ms)
        )
        self._sync_scrollbars()
        self.viewport().update()
        self.snapshotChanged.emit(snapshot)

    def set_visual_pack(self, pack: VisualPack | None) -> None:
        self._visual_pack = pack
        self._glyph_pixmaps.clear()
        if pack is not None:
            for name, path in pack.glyphs:
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    self._glyph_pixmaps[name] = pixmap
        self.viewport().update()

    def set_noteskin_pack(self, pack: LocalNoteskinPack | None) -> None:
        self._noteskin_pack = pack
        self._atlas_pixmaps.clear()
        self._hold_terminal_pixmaps.clear()
        self.viewport().update()

    def set_selected_cell(self, row_id: int, lane: int) -> None:
        self.set_selection(self._selection.replace(CellTarget(row_id, lane)))

    @property
    def selection(self) -> CellSelection:
        return self._selection

    def set_selection(self, selection: CellSelection) -> None:
        self._selection = selection
        self.viewport().update()
        self.selectedCellsChanged.emit(selection)

    def set_selection_mode(self, enabled: bool) -> None:
        self._selection_mode = enabled

    def set_snap_beats(self, beats: float) -> None:
        if beats < 0.0:
            raise ValueError("snap interval cannot be negative")
        self._snap_beats = beats

    def chart_time_at_viewport_beat(
        self, fraction: float = _PLAYHEAD_VIEWPORT_FRACTION
    ) -> float | None:
        """Return the beat at/before a viewport-relative playhead position."""
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("viewport fraction must be between zero and one")
        content_y = (
            self.verticalScrollBar().value() + self.viewport().height() * fraction
        )
        row = self._layout.row_at_y(content_y)
        if row is None:
            return None
        segment, row_index = row
        block = segment.block
        if block.bpm <= 0.0 or block.beat_split <= 0:
            return None
        beat_row = (row_index // block.beat_split) * block.beat_split
        return block.start_time + beat_row * 60_000.0 / (
            block.bpm * block.beat_split
        )

    def set_waveform(
        self,
        waveform: WaveformEnvelope | None,
        alignment: AudioAlignment | None = None,
    ) -> None:
        self._waveform = waveform
        self._audio_alignment = alignment or AudioAlignment()
        self.viewport().update()

    def set_playback_time(
        self, chart_time_ms: float | None, *, follow: bool = False
    ) -> None:
        if chart_time_ms is not None and not isfinite(chart_time_ms):
            raise ValueError("playback time must be finite")
        self._playback_time_ms = chart_time_ms
        self._playback_y = (
            None
            if chart_time_ms is None
            else self._layout.y_for_chart_time(chart_time_ms)
        )
        if follow and self._playback_y is not None:
            # Keep the playhead close to the top while retaining a small amount
            # of context for notes that have just passed.
            anchor = self.viewport().height() * _PLAYHEAD_VIEWPORT_FRACTION
            self.verticalScrollBar().setValue(round(self._playback_y - anchor))
        self.viewport().update()

    def set_playback_active(self, active: bool) -> None:
        active = bool(active)
        if active == self._playback_active:
            return
        vertical_position = self.verticalScrollBar().value()
        # Layout height legitimately changes between the editable encoded-row
        # grid and gameplay projection. Preserve the playhead's position in
        # the viewport, rather than the now-meaningless raw scrollbar value.
        playhead_view_y = (
            None
            if self._playback_y is None
            else self._playback_y - vertical_position
        )
        horizontal_position = self.horizontalScrollBar().value()
        self._playback_active = active
        self._layout = TimelineLayout(
            self._snapshot, self._geometry, playback=self._playback_active
        )
        self._playback_y = (
            None
            if self._playback_time_ms is None
            else self._layout.y_for_chart_time(self._playback_time_ms)
        )
        self._sync_scrollbars()
        self.verticalScrollBar().setValue(
            vertical_position
            if playhead_view_y is None or self._playback_y is None
            else round(self._playback_y - playhead_view_y)
        )
        self.horizontalScrollBar().setValue(horizontal_position)
        self.viewport().update()

    def _snapped_hit(self, hit):
        if hit is None:
            return None
        segment, row_index, lane = hit
        row_index = self._layout.snap_row_index(segment, row_index, self._snap_beats)
        return segment, row_index, lane

    @staticmethod
    def _row_ids(segment) -> tuple[int, ...]:
        return tuple(row.stable_id for row in segment.block.rows)

    def _select_hit(self, segment, row_index: int, lane: int, modifiers) -> None:
        target = CellTarget(segment.block.rows[row_index].stable_id, lane)
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            try:
                selection = self._selection.rectangle(self._row_ids(segment), target)
            except ValueError:
                selection = self._selection.replace(target)
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            selection = self._selection.toggle(target)
        else:
            selection = self._selection.replace(target)
        self.set_selection(selection)

    def _pixmap(self, path) -> QPixmap | None:
        key = str(path)
        if key not in self._atlas_pixmaps:
            pixmap = QPixmap(key)
            if not pixmap.isNull():
                self._atlas_pixmaps[key] = pixmap
        return self._atlas_pixmaps.get(key)

    def _draw_atlas_tile(
        self,
        painter: QPainter,
        atlas: PngAtlas,
        column: int,
        row: int,
        target: QRectF,
    ) -> bool:
        pixmap = self._pixmap(atlas.path)
        if pixmap is None:
            return False
        source = QRectF(*atlas.tile(column, row))
        painter.drawPixmap(target, pixmap, source)
        return True

    def _hold_terminal_pixmap(
        self,
        pixmap: QPixmap,
        atlas: PngAtlas,
        column: int,
        row: int,
        *,
        shaft_above: bool,
    ) -> QPixmap:
        """Compose a terminal and shaft with a per-column silhouette mask."""

        key = (str(atlas.path), column, row, shaft_above)
        cached = self._hold_terminal_pixmaps.get(key)
        if cached is not None:
            return cached
        tile_x, tile_y, tile_width, tile_height = atlas.tile(column, row)
        source = pixmap.toImage()
        terminal = source.copy(tile_x, tile_y, tile_width, tile_height)
        shaft_height = min(8, tile_height)
        shaft_source = source.copy(
            tile_x, atlas.tile(column, 0)[1], tile_width, shaft_height
        )
        shaft = QImage(tile_width, tile_height, QImage.Format.Format_ARGB32)
        shaft.fill(Qt.GlobalColor.transparent)
        shaft_painter = QPainter(shaft)
        try:
            shaft_painter.drawImage(
                QRectF(0, 0, tile_width, tile_height),
                shaft_source,
                QRectF(0, 0, shaft_source.width(), shaft_source.height()),
            )
        finally:
            shaft_painter.end()

        # A single global top/bottom bound leaves a visible gap on diagonal
        # arrows. Mask each shaft column against that column's real artwork.
        for x in range(tile_width):
            # Tail row 0 also supplies the repeatable strip in its first few
            # rows. Exclude that strip while locating the terminal silhouette.
            search_start = shaft_height if shaft_above and row == 0 else 0
            opaque_rows = [
                y
                for y in range(search_start, tile_height)
                if terminal.pixelColor(x, y).alpha() > 0
            ]
            if not opaque_rows:
                for y in range(tile_height):
                    shaft.setPixelColor(x, y, Qt.GlobalColor.transparent)
                continue
            boundary = min(opaque_rows) if shaft_above else max(opaque_rows)
            erase_rows = (
                range(boundary, tile_height)
                if shaft_above
                else range(boundary + 1)
            )
            for y in erase_rows:
                shaft.setPixelColor(x, y, Qt.GlobalColor.transparent)

        composite = QImage(tile_width, tile_height, QImage.Format.Format_ARGB32)
        composite.fill(Qt.GlobalColor.transparent)
        composite_painter = QPainter(composite)
        try:
            composite_painter.drawImage(0, 0, shaft)
            composite_painter.drawImage(0, 0, terminal)
        finally:
            composite_painter.end()
        result = QPixmap.fromImage(composite)
        self._hold_terminal_pixmaps[key] = result
        return result

    def _sync_scrollbars(self) -> None:
        viewport_height = self.viewport().height()
        # Leave a virtual blank tail after the chart.  Without it, the
        # scrollbar reaches its maximum before the final timing position can
        # reach the fixed playhead, so the playhead appears to slide down the
        # viewport near the end of playback.  This space is view-only: it does
        # not create rows and remains outside hit-testing and serialization.
        trailing_space = viewport_height * (1.0 - _PLAYHEAD_VIEWPORT_FRACTION)
        scrollable_height = self._layout.content_height + trailing_space
        height = max(0, ceil(scrollable_height) - viewport_height)
        width = max(0, ceil(self._layout.content_width) - self.viewport().width())
        self.verticalScrollBar().setRange(0, height)
        self.verticalScrollBar().setPageStep(max(1, self.viewport().height()))
        self.horizontalScrollBar().setRange(0, width)
        self.horizontalScrollBar().setPageStep(max(1, self.viewport().width()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_scrollbars()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self.viewport().update()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            old_height = self._geometry.row_height
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self._geometry = self._geometry.zoomed(factor)
            ratio = self._geometry.row_height / old_height
            old_scroll = self.verticalScrollBar().value()
            anchor = event.position().y()
            self._layout = TimelineLayout(
                self._snapshot, self._geometry, playback=self._playback_active
            )
            self._sync_scrollbars()
            self.verticalScrollBar().setValue(round((old_scroll + anchor) * ratio - anchor))
            self.viewport().update()
            event.accept()
            return
        angle = event.angleDelta().y()
        if angle:
            content_y = event.position().y() + self.verticalScrollBar().value()
            # One wheel notch advances half a musical beat.  A fixed pixel step
            # makes split-128 charts feel sixteen times slower than split-8,
            # while a full beat per notch is needlessly coarse for authoring.
            distance = self._layout.pixels_for_beats_at_y(content_y, angle / 240.0)
            if distance:
                scrollbar = self.verticalScrollBar()
                scrollbar.setValue(round(scrollbar.value() - distance))
                event.accept()
                return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        content_x = event.position().x() + self.horizontalScrollBar().value()
        content_y = event.position().y() + self.verticalScrollBar().value()
        segment = self._layout.segment_at_y(content_y)
        info_left = self._layout.chart_width
        info_height = (
            42.0
            if segment is not None
            and len(self._snapshot.split(segment.split_id).blocks) > 1
            else 24.0
        )
        if (
            segment is not None
            and content_x >= info_left
            and content_y < segment.top + info_height
        ):
            self.set_snapshot(self._snapshot.cycle_block(segment.split_id))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        content_x = event.position().x() + self.horizontalScrollBar().value()
        content_y = event.position().y() + self.verticalScrollBar().value()
        segment = self._layout.segment_at_y(content_y)
        if segment is not None:
            self.inspectionRequested.emit(segment.split_id, segment.block.stable_id)
        if event.button() == Qt.MouseButton.RightButton and segment is not None:
            self.contextStructureRequested.emit(
                segment.split_id, segment.block.stable_id, event.globalPosition().toPoint()
            )
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._snapped_hit(self._layout.cell_at(content_x, content_y))
            if hit is not None:
                hit_segment, row_index, lane = hit
                if event.modifiers() & (
                    Qt.KeyboardModifier.ShiftModifier
                    | Qt.KeyboardModifier.ControlModifier
                ) or self._selection_mode:
                    self._select_hit(hit_segment, row_index, lane, event.modifiers())
                else:
                    self.editGestureStarted.emit()
                    self._drag_start = hit
                    self._drag_current = hit
                    self.set_selection(
                        self._selection.replace(
                            CellTarget(hit_segment.block.rows[row_index].stable_id, lane)
                        )
                    )
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            content_x = event.position().x() + self.horizontalScrollBar().value()
            content_y = event.position().y() + self.verticalScrollBar().value()
            hit = self._snapped_hit(self._layout.cell_at(content_x, content_y))
            if hit is not None:
                segment, row_index, lane = hit
                row_id = segment.block.rows[row_index].stable_id
                target = CellTarget(row_id, lane)
                if self._selection_mode or event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    try:
                        selection = self._selection.rectangle(self._row_ids(segment), target)
                    except ValueError:
                        selection = self._selection.replace(target)
                    if selection != self._selection:
                        self.set_selection(selection)
                elif self._drag_start is not None:
                    start_segment, _, start_lane = self._drag_start
                    if segment.split_id == start_segment.split_id and lane == start_lane:
                        self._drag_current = hit
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._drag_start is not None:
                start_segment, start_row, lane = self._drag_start
                end_segment, end_row, end_lane = self._drag_current or self._drag_start
                if start_segment.split_id == end_segment.split_id and lane == end_lane:
                    first, last = sorted((start_row, end_row))
                    row_ids = tuple(
                        start_segment.block.rows[index].stable_id
                        for index in range(first, last + 1)
                    )
                    if len(row_ids) == 1:
                        self.noteEditRequested.emit(row_ids[0], lane)
                    else:
                        self.holdEditRequested.emit(row_ids, lane)
                self._drag_start = None
                self._drag_current = None
            self.editGestureFinished.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.viewport().rect(), QColor("#15171b"))
        x_offset = self.horizontalScrollBar().value()
        y_offset = self.verticalScrollBar().value()
        painter.translate(-x_offset, -y_offset)
        viewport_height = self.viewport().height()
        visible = self._layout.visible_segments(y_offset, viewport_height, overscan_rows=2)
        for item in visible:
            self._draw_segment(painter, item)
        if self._playback_y is not None:
            painter.setPen(QPen(QColor("#ff5a5f"), 2.0))
            painter.drawLine(
                QPointF(0, self._playback_y),
                QPointF(self._layout.chart_width, self._playback_y),
            )

    def _draw_segment(self, painter: QPainter, visible) -> None:
        segment = visible.segment
        geometry = self._geometry
        width = self._layout.chart_width
        info_left = width
        info_height = 42.0 if len(self._snapshot.split(segment.split_id).blocks) > 1 else 24.0
        painter.fillRect(
            QRectF(info_left, segment.top, geometry.block_info_width, info_height),
            QColor("#242832"),
        )
        painter.setPen(QColor("#d7dbe5"))
        split = self._snapshot.split(segment.split_id)
        painter.drawText(
            QRectF(info_left + 8, segment.top, geometry.block_info_width - 16, 24),
            Qt.AlignmentFlag.AlignVCenter,
            f"Split {split.index + 1}  ·  Block {segment.block.index + 1}/{len(split.blocks)}  ·  "
            f"BPM {segment.block.bpm:g}  ·  rows {segment.block.row_count}",
        )
        if len(split.blocks) > 1:
            painter.setPen(QColor("#8fa5d8"))
            painter.drawText(
                QRectF(info_left + 8, segment.top + 22, geometry.block_info_width - 16, 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                "Double-click here to switch branch",
            )

        beat_markers = {marker.row_index: marker for marker in self._layout.beat_markers(visible)}
        for row_index in range(visible.first_row, visible.last_row):
            y = segment.y_for_row(row_index)
            if self._waveform is not None and segment.block.bpm > 0 and segment.block.beat_split > 0:
                chart_time = segment.block.start_time + row_index * 60_000.0 / (
                    segment.block.bpm * segment.block.beat_split
                )
                audio_time = self._audio_alignment.chart_to_audio(chart_time)
                amplitude = self._waveform.amplitude_at(audio_time)
                if amplitude > 0:
                    centre = geometry.ruler_width / 2
                    half = amplitude * max(1.0, geometry.ruler_width / 2 - 5)
                    painter.setPen(QPen(QColor(88, 166, 190, 125), 1.0))
                    painter.drawLine(QPointF(centre - half, y), QPointF(centre + half, y))
            marker = beat_markers.get(row_index)
            if marker is not None:
                color = QColor("#78839a") if marker.is_measure else QColor("#414957")
                painter.setPen(QPen(color, 1.4 if marker.is_measure else 1.0))
                painter.drawLine(QPointF(0, y), QPointF(width, y))
                painter.setPen(QColor("#aeb6c7"))
                label = f"M{int(marker.beat // max(1, segment.block.beat_measure)) + 1}" if marker.is_measure else f"{marker.beat:g}"
                painter.drawText(QRectF(4, y, geometry.ruler_width - 8, segment.row_height), label)
            elif self._snap_beats > 0 and row_index % self._layout.rows_per_snap(
                segment, self._snap_beats
            ) == 0:
                painter.setPen(QPen(QColor("#536989"), 1.0))
                painter.drawLine(
                    QPointF(geometry.ruler_width, y), QPointF(width, y)
                )
            elif segment.row_height >= 10:
                painter.setPen(QColor("#282c34"))
                painter.drawLine(QPointF(geometry.ruler_width, y), QPointF(width, y))

            row = segment.block.rows[row_index]
            selected_lanes = sorted(
                target.lane for target in self._selection.targets if target.row_id == row.stable_id
            )
            for lane in selected_lanes:
                rect = QRectF(
                    geometry.ruler_width + lane * geometry.lane_width + 1,
                    y + 1,
                    geometry.lane_width - 2,
                    max(1.0, segment.row_height - 2),
                )
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#f4d35e"), 2.0))
                painter.drawRect(rect)
            if isinstance(row, EmptyRow):
                continue
            if isinstance(row, LightmapRow):
                self._draw_lightmap_row(
                    painter, row.raw_channels, y, segment.row_height
                )
                continue
            if isinstance(row, (NoteRow, PackedNoteRow)):
                for lane in range(row.cell_count):
                    cell = row.cell(lane) if isinstance(row, PackedNoteRow) else row.cells[lane]
                    if cell.note_type:
                        self._draw_note(painter, lane, y, segment.row_height, cell.raw)

        painter.setPen(QColor("#303641"))
        for lane in range(self._snapshot.columns + 1):
            x = geometry.ruler_width + lane * geometry.lane_width
            painter.drawLine(QPointF(x, segment.rows_top), QPointF(x, segment.bottom))

    def _draw_lightmap_row(
        self, painter: QPainter, channels: bytes, y: float, row_height: float
    ) -> None:
        colors = (QColor("#d67373"), QColor("#99dd99"), QColor("#7b7bd8"), QColor("#d7b46a"))
        width = self._geometry.lane_width * max(1, self._snapshot.columns) / 4
        for index, value in enumerate(channels):
            if value:
                rect = QRectF(
                    self._geometry.ruler_width + index * width + 2,
                    y + 2,
                    width - 4,
                    max(1.0, row_height - 4),
                )
                color = colors[index]
                color.setAlpha(max(40, min(255, value)))
                painter.fillRect(rect, color)

    def _draw_note(
        self, painter: QPainter, lane: int, y: float, row_height: float, raw: bytes
    ) -> None:
        note_type = raw[0] & 0x0F
        glyph_name = {1: "item", 2: "division", 3: "tap", 7: "hold-head", 11: "hold-body", 15: "hold-tail"}.get(note_type, "unknown")
        rect = QRectF(*self._geometry.note_rect(lane, y, row_height))
        drawn = self._draw_noteskin_note(painter, lane, y, row_height, raw, rect)
        if not drawn:
            pixmap = self._glyph_pixmaps.get(glyph_name)
            if pixmap is not None:
                painter.drawPixmap(rect.toRect(), pixmap)
            else:
                color = _NOTE_COLORS.get(note_type, QColor("#e56b6f"))
                painter.setPen(QPen(color.lighter(135), 1.3))
                painter.setBrush(color)
                if note_type in (0x7, 0xB, 0xF):
                    painter.drawRoundedRect(rect, 3, 3)
                elif note_type == 0x1:
                    painter.drawRect(rect)
                elif note_type == 0x2:
                    painter.drawEllipse(rect)
                elif note_type == 0x3:
                    path = QPainterPath()
                    path.moveTo(rect.center().x(), rect.top())
                    path.lineTo(rect.right(), rect.center().y())
                    path.lineTo(rect.center().x(), rect.bottom())
                    path.lineTo(rect.left(), rect.center().y())
                    path.closeSubpath()
                    painter.drawPath(path)
                else:
                    painter.drawRect(rect)
                    painter.drawLine(rect.topLeft(), rect.bottomRight())
                    painter.drawLine(rect.topRight(), rect.bottomLeft())
        self._draw_note_markers(painter, raw, rect)

    @staticmethod
    def _draw_note_markers(painter: QPainter, raw: bytes, rect: QRectF) -> None:
        if raw[0] & 0x0F not in (0x3, 0x7):
            return
        markers = []
        function = raw[0] & 0x60
        if function == 0x20:
            markers.append("G")
        elif function == 0x60:
            markers.append("H")
        visibility = raw[1] & 0x07
        markers.extend({0: ("X",), 1: ("▿",), 2: ("▵",)}.get(visibility, ()))
        if not markers:
            return
        text = " ".join(markers)
        badge = QRectF(rect.left() + 1, rect.top() + 1, rect.width() - 2, 15)
        painter.fillRect(badge, QColor(0, 0, 0, 175))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            badge.adjusted(3, 0, -2, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

    def _draw_noteskin_note(
        self,
        painter: QPainter,
        lane: int,
        y: float,
        row_height: float,
        raw: bytes,
        rect: QRectF,
    ) -> bool:
        pack = self._noteskin_pack
        if pack is None:
            return False
        note_type = raw[0] & 0x0F
        atlas_lane = (self._snapshot.start_column + lane) % 5
        subtype = raw[2]

        if note_type == 0x3:
            bank = pack.bank(subtype)
            if bank is None:
                return False
            # The authoring view uses a deterministic frame.  Animation timing
            # belongs to gameplay preview; row 2 is the non-registering ghost
            # overlay and row 1 is the normal tap artwork.
            atlas_row = 2 if (raw[0] & 0x60) == 0x20 else 1
            return self._draw_atlas_tile(
                painter, bank.animation[0], atlas_lane, atlas_row, rect
            )

        if note_type in (0x7, 0xB, 0xF):
            bank = pack.bank(subtype)
            if bank is None:
                return False
            atlas = bank.animation[0]
            pixmap = self._pixmap(atlas.path)
            if pixmap is None:
                return False

            # Clip terminal continuation per source column. A global boundary
            # leaves gaps on diagonal silhouettes; a full strip leaks through
            # transparent pixels behind the arrow.
            plan = hold_atlas_plan(note_type)
            tile_x, tile_y, tile_width, tile_height = atlas.tile(atlas_lane, 0)
            body_source = QRectF(tile_x, tile_y, tile_width, min(8, tile_height))
            if plan.shaft_above_terminal or plan.shaft_below_terminal:
                assert plan.terminal_row is not None
                terminal = self._hold_terminal_pixmap(
                    pixmap,
                    atlas,
                    atlas_lane,
                    plan.terminal_row,
                    shaft_above=plan.shaft_above_terminal,
                )
                painter.drawPixmap(rect, terminal, QRectF(terminal.rect()))
                return True
            if plan.terminal_row is not None:
                return self._draw_atlas_tile(
                    painter, atlas, atlas_lane, plan.terminal_row, rect
                )
            body_target = QRectF(
                rect.x(),
                y,
                rect.width(),
                max(1.0, row_height),
            )
            painter.drawPixmap(body_target, pixmap, body_source)
            return plan.repeat_shaft

        if note_type == 0x1 and pack.item_animation and subtype < 32:
            return self._draw_atlas_tile(
                painter, pack.item_animation[0], subtype, 0, rect
            )

        if note_type == 0x2 and pack.division is not None and subtype < 5:
            return self._draw_atlas_tile(painter, pack.division, subtype, 0, rect)
        return False
