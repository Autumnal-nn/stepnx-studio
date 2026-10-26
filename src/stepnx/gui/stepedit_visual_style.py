"""Measured STEPEdit-like paint policy for the opt-in Qt viewport.

The palette is sampled from the user-supplied 280x844 STEPEdit screenshot.
Geometry (24px lanes/tiles) is independently supported by static RE evidence.
Vector glyphs are temporary stand-ins; pixel-identical arrows require the
original tile/mask atlas, which is not part of this repository.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QPixmap

from stepnx.authoring.noteskin import LocalNoteskinPack, PngAtlas, hold_atlas_plan
from stepnx.resources import bundled_noteskin_root
from stepnx.authoring.noteskin import load_noteskin_pack


TILE_PIXELS = 24
LANE_PIXELS = 24
NOTE_BACKGROUND = QColor("#FFFFEB")
INDICATOR_BACKGROUND = QColor("#D4D0C8")
PROPERTIES_BACKGROUND = QColor("#FFFFFF")
VERTICAL_GRID = QColor("#005494")
MINOR_GRID = QColor("#B2D7EB")
MAJOR_GRID = QColor("#005494")
LANE_BOUNDARY = QColor("#FF0000")
SELECTION_BACKGROUND = QColor("#C8C8C8")
SPLIT_BACKGROUNDS = tuple(
    QColor(value) for value in ("#FFFFEB", "#EBFFFF", "#EBFFEB", "#FFEBFF")
)
EDITOR_ZOOM_PRESETS = (25, 50, 75, 100, 125, 150, 175, 200)
ATLAS_TILE_PIXELS = 96


def split_background(split_index: int) -> QColor:
    """Four-color cycle by 0-based Split order, not active Block identity."""
    return SPLIT_BACKGROUNDS[split_index % len(SPLIT_BACKGROUNDS)]


def scaled_editor_geometry(percent: int):
    """Render dimensions scaled together, never encoded NX20 timing/BeatSplit."""
    from stepnx.authoring.stepedit_layout import StepEditGeometry
    if percent not in EDITOR_ZOOM_PRESETS:
        raise ValueError(f"unsupported STEPEdit editor zoom: {percent}%")
    factor = percent / 100.0
    return StepEditGeometry(
        vertical_zoom=factor,
        beat_height=192,
        lane_pitch=ATLAS_TILE_PIXELS * factor,
        indicator_width=31 * factor,
        property_width=300 * factor,
        resize_band=5 * factor,
    )


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


class StepEditAtlasArtist:
    """The existing built-in/user-provided 96px noteskin atlas at editor zoom.

    All images are looked up by the NX note's embedded bank and its source
    column. Missing atlas cells use the current provisional vector painter.
    Original atlas pixels remain local; no image bytes are copied to charts.
    """

    def __init__(self, pack: LocalNoteskinPack | None = None) -> None:
        self.pack = pack if pack is not None else load_noteskin_pack(bundled_noteskin_root())
        self._pixmaps: dict[str, QPixmap] = {}

    def _pixmap(self, atlas: PngAtlas) -> QPixmap | None:
        key = str(atlas.path)
        if key not in self._pixmaps:
            self._pixmaps[key] = QPixmap(key)
        item = self._pixmaps[key]
        return item if not item.isNull() else None

    def _tile(self, painter: QPainter, atlas: PngAtlas, column: int,
              row: int, destination: QRectF) -> bool:
        pixmap = self._pixmap(atlas)
        if pixmap is None:
            return False
        painter.drawPixmap(destination, pixmap, QRectF(*atlas.tile(column, row)))
        return True

    def draw(self, painter: QPainter, destination: QRectF, source_lane: int,
             raw: bytes, row_pitch: float) -> bool:
        """Return True if an existing noteskin atlas drew the note."""
        kind = raw[0] & 0x0F
        subtype = raw[2]
        lane = source_lane % 5
        pack = self.pack
        if kind == 3:
            bank = pack.bank(subtype)
            if bank is not None:
                atlas_row = 2 if (raw[0] & 0x60) == 0x20 else 1
                if self._tile(painter, bank.animation[0], lane, atlas_row, destination):
                    return True
        elif kind in (7, 0xB, 0xF):
            bank = pack.bank(subtype)
            if bank is not None:
                atlas = bank.animation[0]
                plan = hold_atlas_plan(kind)
                if plan.terminal_row is not None:
                    if self._tile(painter, atlas, lane, plan.terminal_row, destination):
                        return True
                else:
                    pixmap = self._pixmap(atlas)
                    if pixmap is not None:
                        x, y, w, _ = atlas.tile(lane, 0)
                        painter.drawPixmap(
                            QRectF(destination.x(), destination.y(),
                                   destination.width(), max(1.0, row_pitch)),
                            pixmap, QRectF(x, y, w, 8),
                        )
                        return True
        elif kind == 1 and pack.item_animation and subtype < 32:
            if self._tile(painter, pack.item_animation[0], subtype, 0, destination):
                return True
        elif kind == 2 and pack.division is not None and subtype < 5:
            if self._tile(painter, pack.division, subtype, 0, destination):
                return True

        # Preserve readable unknown data and missing-bank cases, but do not
        # scale glyphs to encoded row spacing. Only user-selected field zoom.
        painter.save()
        try:
            factor = destination.width() / TILE_PIXELS
            painter.translate(destination.x(), destination.y())
            painter.scale(factor, factor)
            StepEditTileArtist.draw(painter, 0, 0, source_lane, raw)
        finally:
            painter.restore()
        return False
