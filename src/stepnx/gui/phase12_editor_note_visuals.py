from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter


_EDITOR_LOW_ALPHA = 102  # 40% for Invisible/Hidden editor visibility.
_EDITOR_TRANSITION_ALPHA = 0  # Appear/Vanish use the full 0%..100% ramp.


def _apply_alpha_mask(image: QImage, *, hidden: bool, visibility: int) -> None:
    """Apply editor-only Hidden/Appear/Vanish visibility to one rendered note."""

    painter = QPainter(image)
    try:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        rect = QRectF(0.0, 0.0, float(image.width()), float(image.height()))
        if hidden or visibility == 0:
            painter.fillRect(rect, QColor(255, 255, 255, _EDITOR_LOW_ALPHA))
        if visibility in (1, 2):
            gradient = QLinearGradient(0.0, 0.0, 0.0, float(image.height()))
            if visibility == 1:  # Appear: opaque at top, transparent at bottom.
                gradient.setColorAt(0.0, QColor(255, 255, 255, 255))
                gradient.setColorAt(1.0, QColor(255, 255, 255, _EDITOR_TRANSITION_ALPHA))
            else:  # Vanish: transparent at top, opaque at bottom.
                gradient.setColorAt(0.0, QColor(255, 255, 255, _EDITOR_TRANSITION_ALPHA))
                gradient.setColorAt(1.0, QColor(255, 255, 255, 255))
            painter.fillRect(rect, gradient)
    finally:
        painter.end()


def _ghost_outline(source: QImage, radius: int = 2) -> QImage:
    """Build a white alpha-derived outline without assuming an arrow shape."""

    outline = QImage(source.size(), QImage.Format.Format_ARGB32_Premultiplied)
    outline.fill(Qt.GlobalColor.transparent)
    painter = QPainter(outline)
    try:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                if dx * dx + dy * dy > radius * radius + 1:
                    continue
                painter.drawImage(dx, dy, source)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(outline.rect(), QColor(255, 255, 255, 255))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
        painter.drawImage(0, 0, source)
    finally:
        painter.end()
    return outline


def _draw_roll_head(self, painter, lane, y, row_height, raw, rect) -> bool:
    """Use atlas row 2 as the actual roll head for HOLD_HEAD + function 0x20."""

    pack = getattr(self, "_noteskin_pack", None)
    if pack is None:
        return False
    bank = pack.bank(raw[2])
    if bank is None or not bank.animation:
        return False
    atlas = bank.animation[0]
    pixmap = self._pixmap(atlas.path)
    if pixmap is None:
        return False
    atlas_lane = (self._snapshot.start_column + lane) % 5

    tile_x, tile_y, tile_width, tile_height = atlas.tile(atlas_lane, 0)
    body_source = QRectF(tile_x, tile_y, tile_width, min(8, tile_height))
    body_target = QRectF(rect.x(), y, rect.width(), max(1.0, row_height))
    painter.drawPixmap(body_target, pixmap, body_source)
    return self._draw_atlas_tile(painter, atlas, atlas_lane, 2, rect)


def _install_note_renderer() -> None:
    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_phase12_editor_note_visuals", False):
        return

    original_draw = timeline_class._draw_noteskin_note

    def draw_editor_semantics(self, painter, lane, y, row_height, raw, rect):
        note_type = raw[0] & 0x0F
        function = raw[0] & 0x60
        visibility = raw[1] & 0x07
        ghost_tap = note_type == 0x3 and function == 0x20
        roll_head = note_type == 0x7 and function == 0x20
        hidden = function == 0x60
        needs_mask = hidden or visibility in (0, 1, 2)

        if not ghost_tap and not roll_head and not needs_mask:
            return original_draw(self, painter, lane, y, row_height, raw, rect)

        width = max(1, int(math.ceil(rect.width())))
        height = max(1, int(math.ceil(max(rect.height(), row_height))))
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        local = QPainter(image)
        try:
            local_rect = QRectF(0.0, 0.0, float(width), float(height))
            if roll_head:
                drawn = _draw_roll_head(
                    self, local, lane, 0.0, float(height), raw, local_rect
                )
            else:
                render_raw = raw
                if ghost_tap:
                    changed = bytearray(raw)
                    changed[0] = (changed[0] & ~0x60) | 0x40
                    render_raw = bytes(changed)
                drawn = original_draw(
                    self,
                    local,
                    lane,
                    0.0,
                    float(height),
                    render_raw,
                    local_rect,
                )
        finally:
            local.end()

        if not drawn:
            return False

        outline = _ghost_outline(image) if ghost_tap else None
        if needs_mask:
            _apply_alpha_mask(image, hidden=hidden, visibility=visibility)
            if outline is not None:
                _apply_alpha_mask(outline, hidden=hidden, visibility=visibility)

        if outline is not None:
            painter.drawImage(rect, outline)
        painter.drawImage(rect, image)
        return True

    def draw_unknown_markers(painter, raw, rect) -> None:
        if raw[0] & 0x0F not in (0x3, 0x7):
            return
        visibility = raw[1] & 0x07
        if visibility < 4:
            return
        badge = QRectF(rect.left() + 1, rect.top() + 1, rect.width() - 2, 15)
        painter.fillRect(badge, QColor(0, 0, 0, 175))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            badge.adjusted(3, 0, -2, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"V{visibility}",
        )

    timeline_class._draw_noteskin_note = draw_editor_semantics
    timeline_class._draw_note_markers = staticmethod(draw_unknown_markers)
    timeline_class._phase12_editor_note_visuals = True


def _install_raw_visibility_choices(window) -> None:
    combo = getattr(window, "visibility_combo", None)
    if combo is None:
        return
    existing = {int(combo.itemData(index)) for index in range(combo.count())}
    if 4 not in existing:
        combo.addItem("Raw 4 (unknown runtime meaning)", 4)
    if 5 not in existing:
        combo.addItem("Raw 5 (unknown runtime meaning)", 5)


def install_phase12_editor_note_visuals(window) -> None:
    if getattr(window, "_phase12_editor_note_visuals_installed", False):
        return
    window._phase12_editor_note_visuals_installed = True
    _install_note_renderer()
    _install_raw_visibility_choices(window)
