from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter


_EDITOR_LOW_ALPHA = 102  # 40% for Invisible/Hidden editor visibility.
_EDITOR_TRANSITION_ALPHA = 0  # Appear/Vanish use the full 0%..100% ramp.


@dataclass(frozen=True, slots=True)
class _HoldVisualContext:
    function: int
    visibility: int
    start_y: float
    end_y: float


def _cell_raw(row, lane: int) -> bytes | None:
    """Return one note cell without caring which row-storage backend is active."""

    try:
        if hasattr(row, "cell"):
            return row.cell(lane).raw
        return row.cells[lane].raw
    except (AttributeError, IndexError):
        return None


def _hold_visual_contexts(widget, segment) -> dict[tuple[int, float], _HoldVisualContext]:
    """Project Hold Head semantics across its Body/Tail cells for editor drawing.

    NX20 stores every cell independently, but legacy authored longs may put the
    visual/function modifier only on the Hold Head. The editor interprets those
    modifiers as a property of the complete long without rewriting Body/Tail
    bytes. Only complete Head -> Body* -> Tail runs are projected.
    """

    contexts: dict[tuple[int, float], _HoldVisualContext] = {}
    block = segment.block
    for lane in range(widget._snapshot.columns):
        head_index: int | None = None
        head_raw: bytes | None = None
        for row_index, row in enumerate(block.rows):
            raw = _cell_raw(row, lane)
            note_type = 0 if raw is None else raw[0] & 0x0F

            if head_index is None:
                if note_type == 0x7:
                    head_index = row_index
                    head_raw = raw
                continue

            if note_type == 0xB:
                continue

            if note_type == 0xF and head_raw is not None:
                function = head_raw[0] & 0x60
                visibility = head_raw[1] & 0x07
                # A fully normal/visible Head does not impose anything on the
                # rest of the long. This keeps deliberately decorated Body/Tail
                # cells visible to the raw renderer.
                if function != 0x40 or visibility != 3:
                    head_y = segment.y_for_row(head_index)
                    tail_y = segment.y_for_row(row_index)
                    head_rect = QRectF(
                        *widget._geometry.note_rect(lane, head_y, segment.row_height)
                    )
                    tail_rect = QRectF(
                        *widget._geometry.note_rect(lane, tail_y, segment.row_height)
                    )
                    context = _HoldVisualContext(
                        function=function,
                        visibility=visibility,
                        start_y=head_rect.top(),
                        end_y=tail_rect.bottom(),
                    )
                    for member_index in range(head_index, row_index + 1):
                        member_raw = _cell_raw(block.rows[member_index], lane)
                        if member_raw is None:
                            continue
                        member_type = member_raw[0] & 0x0F
                        if member_type not in (0x7, 0xB, 0xF):
                            continue
                        member_y = segment.y_for_row(member_index)
                        contexts[(lane, member_y)] = context

            # Any non-body cell closes the current run. A new Head may start
            # immediately on the same lane.
            head_index = row_index if note_type == 0x7 else None
            head_raw = raw if note_type == 0x7 else None

    return contexts


def _effective_hold_raw(raw: bytes, context: _HoldVisualContext | None) -> bytes:
    if context is None or raw[0] & 0x0F not in (0x7, 0xB, 0xF):
        return raw
    changed = bytearray(raw)
    changed[0] = (changed[0] & ~0x60) | context.function
    changed[1] = (changed[1] & ~0x07) | context.visibility
    return bytes(changed)


def _render_target_rect(
    note_type: int, rect: QRectF, y: float, row_height: float
) -> QRectF:
    """Return the raster target used by editor-only visual effects.

    HOLD_BODY is a shaft segment whose height is the encoded row span. Treating
    it as a square note target shrinks every affected Body cell and creates the
    striped gaps visible in Hidden/Appear/Vanish longs.
    """

    if note_type == 0xB:
        return QRectF(rect.x(), y, rect.width(), max(1.0, row_height))
    return QRectF(rect)


def _visibility_alpha(visibility: int, progress: float) -> int:
    progress = max(0.0, min(1.0, float(progress)))
    if visibility == 1:  # Appear: opaque at top, transparent at bottom.
        alpha = 255.0 + (_EDITOR_TRANSITION_ALPHA - 255.0) * progress
    elif visibility == 2:  # Vanish: transparent at top, opaque at bottom.
        alpha = _EDITOR_TRANSITION_ALPHA + (255.0 - _EDITOR_TRANSITION_ALPHA) * progress
    else:
        return 255
    return max(0, min(255, round(alpha)))


def _transition_progress(
    target: QRectF, context: _HoldVisualContext | None
) -> tuple[float, float]:
    if context is None or context.end_y <= context.start_y:
        return 0.0, 1.0
    span = context.end_y - context.start_y
    return (
        (target.top() - context.start_y) / span,
        (target.bottom() - context.start_y) / span,
    )


def _apply_alpha_mask(
    image: QImage,
    *,
    hidden: bool,
    visibility: int,
    progress: tuple[float, float] = (0.0, 1.0),
) -> None:
    """Apply editor-only Hidden/Appear/Vanish visibility to one rendered note."""

    painter = QPainter(image)
    try:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        rect = QRectF(0.0, 0.0, float(image.width()), float(image.height()))
        if hidden or visibility == 0:
            painter.fillRect(rect, QColor(255, 255, 255, _EDITOR_LOW_ALPHA))
        if visibility in (1, 2):
            gradient = QLinearGradient(0.0, 0.0, 0.0, float(image.height()))
            gradient.setColorAt(
                0.0,
                QColor(255, 255, 255, _visibility_alpha(visibility, progress[0])),
            )
            gradient.setColorAt(
                1.0,
                QColor(255, 255, 255, _visibility_alpha(visibility, progress[1])),
            )
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
    original_draw_segment = timeline_class._draw_segment

    def draw_segment_with_hold_context(self, painter, visible):
        previous = getattr(self, "_phase12_hold_visual_contexts", None)
        # Gameplay projection/preview semantics stay independent. This context
        # exists only while drawing the paused authoring grid.
        self._phase12_hold_visual_contexts = (
            {}
            if getattr(self, "_playback_active", False)
            else _hold_visual_contexts(self, visible.segment)
        )
        try:
            return original_draw_segment(self, painter, visible)
        finally:
            if previous is None:
                try:
                    del self._phase12_hold_visual_contexts
                except AttributeError:
                    pass
            else:
                self._phase12_hold_visual_contexts = previous

    def draw_editor_semantics(self, painter, lane, y, row_height, raw, rect):
        context = getattr(self, "_phase12_hold_visual_contexts", {}).get((lane, y))
        render_raw = _effective_hold_raw(raw, context)

        note_type = render_raw[0] & 0x0F
        function = render_raw[0] & 0x60
        visibility = render_raw[1] & 0x07
        ghost_tap = note_type == 0x3 and function == 0x20
        roll_head = note_type == 0x7 and function == 0x20
        hidden = function == 0x60
        needs_mask = hidden or visibility in (0, 1, 2)

        if not ghost_tap and not roll_head and not needs_mask:
            return original_draw(self, painter, lane, y, row_height, render_raw, rect)

        target = _render_target_rect(note_type, rect, y, row_height)
        width = max(1, int(math.ceil(target.width())))
        height = max(1, int(math.ceil(target.height())))
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        local = QPainter(image)
        try:
            local_rect = QRectF(0.0, 0.0, float(width), float(height))
            if roll_head:
                drawn = _draw_roll_head(
                    self, local, lane, 0.0, float(height), render_raw, local_rect
                )
            else:
                note_raw = render_raw
                if ghost_tap:
                    changed = bytearray(render_raw)
                    changed[0] = (changed[0] & ~0x60) | 0x40
                    note_raw = bytes(changed)
                drawn = original_draw(
                    self,
                    local,
                    lane,
                    0.0,
                    float(height),
                    note_raw,
                    local_rect,
                )
        finally:
            local.end()

        if not drawn:
            return False

        outline = _ghost_outline(image) if ghost_tap else None
        if needs_mask:
            progress = _transition_progress(target, context)
            _apply_alpha_mask(
                image,
                hidden=hidden,
                visibility=visibility,
                progress=progress,
            )
            if outline is not None:
                _apply_alpha_mask(
                    outline,
                    hidden=hidden,
                    visibility=visibility,
                    progress=progress,
                )

        if outline is not None:
            painter.drawImage(target, outline)
        painter.drawImage(target, image)
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

    timeline_class._draw_segment = draw_segment_with_hold_context
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
