from __future__ import annotations

from math import ceil

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractScrollArea

from stepnx.authoring.glyphs import VisualPack
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


class TimelineWidget(QAbstractScrollArea):
    snapshotChanged = Signal(object)
    inspectionRequested = Signal(int, int)

    def __init__(self, snapshot: AuthoringSnapshot, parent=None) -> None:
        super().__init__(parent)
        self._snapshot = snapshot
        self._geometry = TimelineGeometry()
        self._layout = TimelineLayout(snapshot, self._geometry)
        self._visual_pack: VisualPack | None = None
        self._pixmaps: dict[str, QPixmap] = {}
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._sync_scrollbars()

    @property
    def snapshot(self) -> AuthoringSnapshot:
        return self._snapshot

    def set_snapshot(self, snapshot: AuthoringSnapshot) -> None:
        self._snapshot = snapshot
        self._layout = TimelineLayout(snapshot, self._geometry)
        self._sync_scrollbars()
        self.viewport().update()
        self.snapshotChanged.emit(snapshot)

    def set_visual_pack(self, pack: VisualPack | None) -> None:
        self._visual_pack = pack
        self._pixmaps.clear()
        if pack is not None:
            for name, path in pack.glyphs:
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    self._pixmaps[name] = pixmap
        self.viewport().update()

    def _sync_scrollbars(self) -> None:
        height = max(0, ceil(self._layout.content_height) - self.viewport().height())
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
            self._layout = TimelineLayout(self._snapshot, self._geometry)
            self._sync_scrollbars()
            self.verticalScrollBar().setValue(round((old_scroll + anchor) * ratio - anchor))
            self.viewport().update()
            event.accept()
            return
        super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        content_y = event.position().y() + self.verticalScrollBar().value()
        segment = self._layout.segment_at_y(content_y)
        if segment is not None and segment.top <= content_y < segment.rows_top:
            self.set_snapshot(self._snapshot.cycle_block(segment.split_id))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        content_y = event.position().y() + self.verticalScrollBar().value()
        segment = self._layout.segment_at_y(content_y)
        if segment is not None:
            self.inspectionRequested.emit(segment.split_id, segment.block.stable_id)
        super().mousePressEvent(event)

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

    def _draw_segment(self, painter: QPainter, visible) -> None:
        segment = visible.segment
        geometry = self._geometry
        width = self._layout.content_width
        painter.fillRect(QRectF(0, segment.top, width, geometry.block_header_height), QColor("#242832"))
        painter.setPen(QColor("#d7dbe5"))
        split = self._snapshot.split(segment.split_id)
        painter.drawText(
            QRectF(8, segment.top, width - 16, geometry.block_header_height),
            Qt.AlignmentFlag.AlignVCenter,
            f"Split {split.index + 1}  ·  Block {segment.block.index + 1}/{len(split.blocks)}  ·  "
            f"BPM {segment.block.bpm:g}  ·  rows {segment.block.row_count}",
        )
        if len(split.blocks) > 1:
            painter.setPen(QColor("#8fa5d8"))
            painter.drawText(
                QRectF(width - 210, segment.top, 200, geometry.block_header_height),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                "Double-click to switch branch",
            )

        beat_markers = {marker.row_index: marker for marker in self._layout.beat_markers(visible)}
        for row_index in range(visible.first_row, visible.last_row):
            y = segment.y_for_row(row_index, geometry)
            marker = beat_markers.get(row_index)
            if marker is not None:
                color = QColor("#78839a") if marker.is_measure else QColor("#414957")
                painter.setPen(QPen(color, 1.4 if marker.is_measure else 1.0))
                painter.drawLine(QPointF(0, y), QPointF(width, y))
                painter.setPen(QColor("#aeb6c7"))
                label = f"M{int(marker.beat // max(1, segment.block.beat_measure)) + 1}" if marker.is_measure else f"{marker.beat:g}"
                painter.drawText(QRectF(4, y, geometry.ruler_width - 8, geometry.row_height), label)
            elif geometry.row_height >= 10:
                painter.setPen(QColor("#282c34"))
                painter.drawLine(QPointF(geometry.ruler_width, y), QPointF(width, y))

            row = segment.block.rows[row_index]
            if isinstance(row, EmptyRow):
                continue
            if isinstance(row, LightmapRow):
                self._draw_lightmap_row(painter, row.raw_channels, y)
                continue
            if isinstance(row, (NoteRow, PackedNoteRow)):
                for lane in range(row.cell_count):
                    cell = row.cell(lane) if isinstance(row, PackedNoteRow) else row.cells[lane]
                    if cell.note_type:
                        self._draw_note(painter, lane, y, cell.raw)

        painter.setPen(QColor("#303641"))
        for lane in range(self._snapshot.columns + 1):
            x = geometry.ruler_width + lane * geometry.lane_width
            painter.drawLine(QPointF(x, segment.rows_top), QPointF(x, segment.bottom))

    def _draw_lightmap_row(self, painter: QPainter, channels: bytes, y: float) -> None:
        colors = (QColor("#d67373"), QColor("#99dd99"), QColor("#7b7bd8"), QColor("#d7b46a"))
        width = self._geometry.lane_width * max(1, self._snapshot.columns) / 4
        for index, value in enumerate(channels):
            if value:
                rect = QRectF(self._geometry.ruler_width + index * width + 2, y + 2, width - 4, self._geometry.row_height - 4)
                color = colors[index]
                color.setAlpha(max(40, min(255, value)))
                painter.fillRect(rect, color)

    def _draw_note(self, painter: QPainter, lane: int, y: float, raw: bytes) -> None:
        note_type = raw[0] & 0x0F
        glyph_name = {1: "item", 2: "division", 3: "tap", 7: "hold-head", 11: "hold-body", 15: "hold-tail"}.get(note_type, "unknown")
        margin = max(2.0, self._geometry.row_height * 0.12)
        rect = QRectF(
            self._geometry.ruler_width + lane * self._geometry.lane_width + margin,
            y + margin,
            self._geometry.lane_width - margin * 2,
            self._geometry.row_height - margin * 2,
        )
        pixmap = self._pixmaps.get(glyph_name)
        if pixmap is not None:
            painter.drawPixmap(rect.toRect(), pixmap)
            return
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
