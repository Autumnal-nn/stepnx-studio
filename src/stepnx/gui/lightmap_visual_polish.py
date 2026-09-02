from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen

from stepnx.authoring.selection import CellSelection
from stepnx.core.model import EmptyRow, LightmapRow

_LIGHT_COLORS = (QColor("#d67373"), QColor("#99dd99"), QColor("#7b7bd8"))
_LIGHT_OFF_ALPHA = 13
_LIGHT_ON_ALPHA = 204


def lightmap_alpha(value: int) -> int:
    return _LIGHT_ON_ALPHA if int(value) else _LIGHT_OFF_ALPHA


def lightmap_rect(widget, lane: int, y: float, row_height: float) -> QRectF:
    lane = int(lane)
    if not 0 <= lane < 3:
        raise ValueError("Lightmap lane must be between 0 and 2")
    geometry = widget._geometry
    lane_width = float(geometry.lane_width)
    return QRectF(
        float(geometry.ruler_width) + lane * lane_width + 2.0,
        float(y) + 2.0,
        max(1.0, lane_width - 4.0),
        max(1.0, float(row_height) - 4.0),
    )


def _row_channels(row) -> bytes | None:
    if isinstance(row, EmptyRow):
        return b"\x00\x00\x00"
    if isinstance(row, LightmapRow):
        return bytes(row.raw_channels[:3])
    return None


def _draw_visible_lightmap(widget, painter, visible, selection: CellSelection) -> None:
    segment = visible.segment
    selected_by_row: dict[int, list[int]] = {}
    for target in selection.targets:
        if 0 <= int(target.lane) < 3:
            selected_by_row.setdefault(int(target.row_id), []).append(int(target.lane))
    for row_index in range(visible.first_row, visible.last_row):
        row = segment.block.rows[row_index]
        channels = _row_channels(row)
        if channels is None:
            continue
        y = float(segment.y_for_row(row_index))
        for lane, value in enumerate(channels):
            rect = lightmap_rect(widget, lane, y, segment.row_height)
            color = QColor(_LIGHT_COLORS[lane])
            color.setAlpha(lightmap_alpha(value))
            painter.fillRect(rect, color)
        for lane in selected_by_row.get(int(row.stable_id), ()):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#f4d35e"), 2.0))
            painter.drawRect(lightmap_rect(widget, lane, y, segment.row_height))


def install_lightmap_visual_polish(window) -> None:
    if getattr(window, "_stepnx_lightmap_visual_polish", False):
        return
    window._stepnx_lightmap_visual_polish = True
    import stepnx.gui.timeline_widget as timeline_module
    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_stepnx_lightmap_visual_polish", False):
        return
    timeline_class._stepnx_lightmap_visual_polish = True
    original_draw_segment = timeline_class._draw_segment
    original_draw_lightmap_row = timeline_class._draw_lightmap_row

    def suppress_base_lightmap_row(self, painter, channels, y, row_height) -> None:
        return None

    def draw_segment(self, painter, visible) -> None:
        if not self.snapshot.effective_lightmap:
            original_draw_segment(self, painter, visible)
            return
        selection = self.selection
        self._selection = CellSelection()
        try:
            original_draw_segment(self, painter, visible)
        finally:
            self._selection = selection
        _draw_visible_lightmap(self, painter, visible, selection)

    timeline_class._draw_lightmap_row = suppress_base_lightmap_row
    timeline_class._draw_segment = draw_segment
    timeline_class._stepnx_original_draw_lightmap_row_before_polish = original_draw_lightmap_row
    timeline_class._stepnx_original_draw_segment_before_lightmap_polish = original_draw_segment
