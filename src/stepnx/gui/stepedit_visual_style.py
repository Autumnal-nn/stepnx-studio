"""Measured STEPEdit-like paint policy for the opt-in Qt viewport.

The palette is sampled from the user-supplied 280x844 STEPEdit screenshot.
Geometry (24px lanes/tiles) is independently supported by static RE evidence.
Vector glyphs are temporary stand-ins; pixel-identical arrows require the
original tile/mask atlas, which is not part of this repository.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF


TILE_PIXELS = 24
LANE_PIXELS = 24
NOTE_BACKGROUND = QColor("#FFFFEB")
INDICATOR_BACKGROUND = QColor("#D4D0C8")
PROPERTIES_BACKGROUND = QColor("#FFFFFF")
VERTICAL_GRID = QColor("#005494")
MINOR_GRID = QColor("#B2D7EB")
MAJOR_GRID = QColor("#005494")
LANE_BOUNDARY = QColor("#FF0000")


def note_rect(lane_left: float, row_top: float) -> QRectF:
    """STEPEdit's 24x24 tile, independent of BeatSplit and display zoom."""
    return QRectF(lane_left, row_top, TILE_PIXELS, TILE_PIXELS)


def wheel_line_pixels(vertical_zoom: float) -> float:
    """CScrollView SetScrollSizes sizeLine.cy is 24 * vertical_zoom."""
    return 24.0 * vertical_zoom


def wheel_notch_pixels(vertical_zoom: float, system_lines: int, viewport_height: float) -> float:
    """One 120-unit notch in logical pixels, matching MFC line scrolling.

    Qt exposes the Windows-configured wheel scroll line count. A negative value
    represents page mode; zero intentionally disables scrolling.
    """
    if system_lines < 0:
        return max(0.0, viewport_height)
    return wheel_line_pixels(vertical_zoom) * system_lines


def _arrow_path() -> QPainterPath:
    # Compact diagonal arrow, with deliberately aliased 24px raster edges.
    path = QPainterPath()
    path.moveTo(3, 10)
    path.lineTo(10, 10)
    path.lineTo(10, 3)
    path.lineTo(21, 3)
    path.lineTo(21, 14)
    path.lineTo(14, 14)
    path.lineTo(14, 21)
    path.closeSubpath()
    return path


class StepEditTileArtist:
    """Fixed-size provisional icons; do not scale to row height."""

    @staticmethod
    def draw(painter: QPainter, left: float, top: float, lane: int, raw: bytes) -> QRectF:
        destination = note_rect(left, top)
        kind = raw[0] & 0x0F
        if kind == 0:
            return destination
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.translate(left, top)
            painter.translate(12.0, 12.0)
            # The two groups of five share the same pad directions.
            pad = lane % 5
            if pad == 0:  # Lower-left
                painter.rotate(180)
            elif pad == 1:  # Upper-left
                painter.rotate(270)
            elif pad == 3:  # Upper-right
                painter.rotate(0)
            elif pad == 4:  # Lower-right
                painter.rotate(90)
            painter.translate(-12.0, -12.0)
            if pad == 2 or kind in (1, 2):
                base = QColor("#FFCB20") if kind not in (7, 0xB, 0xF) else QColor("#5CE7FF")
                painter.setPen(QPen(QColor("#005494"), 1))
                painter.setBrush(QColor("#FFFFFF"))
                painter.drawEllipse(QRectF(2, 2, 20, 20))
                painter.setBrush(base)
                painter.drawEllipse(QRectF(5, 5, 14, 14))
                painter.setBrush(QColor("#FFFFFF"))
                painter.drawEllipse(QRectF(9, 9, 6, 6))
            else:
                cyan = kind in (7, 0xB, 0xF)
                base = QColor("#59D5FE") if cyan else QColor("#FF9F1A")
                edge = QColor("#005494")
                painter.setPen(QPen(edge, 2))
                painter.setBrush(QColor("#FFFFFF"))
                painter.drawPath(_arrow_path())
                painter.setPen(QPen(edge, 1))
                painter.setBrush(base)
                painter.drawPolygon(
                    QPolygonF([
                        QPointF(6, 11), QPointF(12, 11), QPointF(12, 5),
                        QPointF(19, 5), QPointF(19, 12), QPointF(12, 12),
                        QPointF(12, 18),
                    ])
                )
        finally:
            painter.restore()
        return destination
