from __future__ import annotations

import math
from types import MethodType

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QMessageBox

from stepnx.authoring.tools import NoteTool
from stepnx.core.commands import SetNoteAt


_EDITOR_LOW_ALPHA = 102  # 40% for Invisible/Hidden authoring cues.
_EDITOR_TRANSITION_ALPHA = 0
_GHOST_OUTLINE_RADIUS = 3
_NXA_PROFILES = frozenset({"nxa-native", "nxa-step5-patched"})


def _visibility_alpha(visibility: int, progress: float) -> int:
    """Return the editor cue alpha for one vertical position inside a note."""

    progress = max(0.0, min(1.0, float(progress)))
    if visibility in (1, 5):  # Appear / AppearLow.
        alpha = 255.0 + (_EDITOR_TRANSITION_ALPHA - 255.0) * progress
    elif visibility in (2, 4):  # Vanish / VanishLow.
        alpha = _EDITOR_TRANSITION_ALPHA + (255.0 - _EDITOR_TRANSITION_ALPHA) * progress
    else:
        return 255
    return max(0, min(255, round(alpha)))


def _is_roll_head(raw: bytes) -> bool:
    """NX20 roll heads are Hold Heads with the 0x10 sustain bit cleared."""

    return len(raw) == 4 and (raw[0] & 0x0F) == 0x7 and not (raw[0] & 0x10)


def _should_apply_editor_mask(raw: bytes) -> bool:
    """Only Tap and Hold Head carry editor opacity cues.

    Body/Tail stay fully opaque even when their raw bytes repeat the visibility
    value. The head is enough to communicate that the property belongs to the
    complete long and avoids visually shredding the shaft into per-row filters.
    """

    if len(raw) != 4 or (raw[0] & 0x0F) not in (0x3, 0x7):
        return False
    hidden = (raw[0] & 0x60) == 0x60
    visibility = raw[1] & 0x07
    return hidden or visibility in (0, 1, 2, 4, 5)


def _apply_alpha_mask(image: QImage, *, hidden: bool, visibility: int) -> None:
    """Apply an editor-only visibility cue to a Tap or Hold Head image."""

    painter = QPainter(image)
    try:
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        rect = QRectF(0.0, 0.0, float(image.width()), float(image.height()))
        if hidden or visibility == 0:
            painter.fillRect(rect, QColor(255, 255, 255, _EDITOR_LOW_ALPHA))
        if visibility in (1, 2, 4, 5):
            gradient = QLinearGradient(0.0, 0.0, 0.0, float(image.height()))
            gradient.setColorAt(
                0.0, QColor(255, 255, 255, _visibility_alpha(visibility, 0.0))
            )
            gradient.setColorAt(
                1.0, QColor(255, 255, 255, _visibility_alpha(visibility, 1.0))
            )
            painter.fillRect(rect, gradient)
    finally:
        painter.end()


def _ghost_outline(source: QImage, radius: int = _GHOST_OUTLINE_RADIUS) -> QImage:
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


def _draw_head_shaft_underlay(self, painter, lane, y, row_height, raw, rect) -> bool:
    """Draw the same unfiltered head-to-body bridge as a Normal/Visible long.

    Phase 11 draws this strip directly in timeline coordinates, beginning on the
    Hold Head timing line. The old Phase-12 special path instead rendered the
    complete Phase-11 wrapper into a 44px local image. That clipped the shaft to
    the head square and then applied the head alpha mask to it, which is why
    non-Normal/Visible heads appeared detached from their Body.
    """

    if row_height <= 0.0:
        return False
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
    body_target = QRectF(
        rect.x(),
        y,
        rect.width(),
        max(1.0, row_height),
    )
    painter.drawPixmap(body_target, pixmap, body_source)
    return True


def _draw_hold_head_terminal(self, painter, lane, raw, rect) -> bool:
    """Draw only a Hold Head terminal, never its shaft underlay."""

    pack = getattr(self, "_noteskin_pack", None)
    if pack is None:
        return False
    bank = pack.bank(raw[2])
    if bank is None or not bank.animation:
        return False
    atlas = bank.animation[0]
    atlas_lane = (self._snapshot.start_column + lane) % 5
    atlas_row = 2 if _is_roll_head(raw) else 1
    return self._draw_atlas_tile(painter, atlas, atlas_lane, atlas_row, rect)


def _install_note_renderer() -> None:
    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_phase12_editor_note_visuals_v3", False):
        return

    original_draw = timeline_class._draw_noteskin_note

    def draw_editor_semantics(self, painter, lane, y, row_height, raw, rect):
        note_type = raw[0] & 0x0F
        function = raw[0] & 0x60
        visibility = raw[1] & 0x07
        ghost_terminal = note_type in (0x3, 0x7) and function == 0x20
        roll_head = _is_roll_head(raw)
        needs_mask = _should_apply_editor_mask(raw)

        # Body/Tail always take the normal renderer. Their visual bytes remain
        # losslessly present in the chart, but the authoring cue lives on Head.
        if note_type in (0xB, 0xF):
            return original_draw(self, painter, lane, y, row_height, raw, rect)

        if not ghost_terminal and not roll_head and not needs_mask:
            return original_draw(self, painter, lane, y, row_height, raw, rect)

        # A special Hold Head needs the exact same world-space shaft bridge used
        # by Normal/Visible. Keep that bridge opaque, then filter only the
        # terminal artwork. Rendering the Phase-11 wrapper into the local head
        # image is incorrect because its y coordinate is no longer the row's
        # timing line and the shaft is clipped to the square image.
        if note_type == 0x7:
            _draw_head_shaft_underlay(
                self, painter, lane, y, row_height, raw, rect
            )

        width = max(1, int(math.ceil(rect.width())))
        height = max(1, int(math.ceil(rect.height())))
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        local = QPainter(image)
        try:
            local_rect = QRectF(0.0, 0.0, float(width), float(height))
            if note_type == 0x7:
                drawn = _draw_hold_head_terminal(
                    self, local, lane, raw, local_rect
                )
            else:
                render_raw = raw
                if ghost_terminal:
                    # Ghost Tap keeps ordinary tap artwork. The white outline is
                    # the editor-only distinction; atlas row 2 belongs to Roll.
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

        outline = _ghost_outline(image) if ghost_terminal else None
        if needs_mask:
            hidden = function == 0x60
            _apply_alpha_mask(image, hidden=hidden, visibility=visibility)
            if outline is not None:
                _apply_alpha_mask(outline, hidden=hidden, visibility=visibility)

        if outline is not None:
            painter.drawImage(rect, outline)
        painter.drawImage(rect, image)
        return True

    def draw_visibility_markers(painter, raw, rect) -> None:
        if raw[0] & 0x0F not in (0x3, 0x7):
            return
        visibility = raw[1] & 0x07
        label = {4: "VL", 5: "AL"}.get(visibility)
        if label is None and visibility not in (6, 7):
            return
        if label is None:
            # 6/7 are not typed modes and have no corpus examples. A raw chart
            # can still contain them, so diagnose rather than normalize them.
            label = f"V{visibility}"
        badge = QRectF(rect.left() + 1, rect.top() + 1, rect.width() - 2, 15)
        painter.fillRect(badge, QColor(0, 0, 0, 175))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            badge.adjusted(3, 0, -2, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )

    timeline_class._draw_noteskin_note = draw_editor_semantics
    timeline_class._draw_note_markers = staticmethod(draw_visibility_markers)
    timeline_class._phase12_editor_note_visuals = True
    timeline_class._phase12_editor_note_visuals_v2 = True
    timeline_class._phase12_editor_note_visuals_v3 = True


def _selected_profile(window) -> str:
    getter = getattr(window, "_selected_profile", None)
    if callable(getter):
        return str(getter())
    actions = getattr(window, "profile_actions", {})
    for value, action in actions.items():
        if action.isChecked():
            return str(value)
    return "nxa-native"


def _profile_supports_low_visibility(profile: str) -> bool:
    return str(profile) in _NXA_PROFILES


def _refresh_visibility_choices(window) -> None:
    combo = getattr(window, "visibility_combo", None)
    if combo is None:
        return

    current = combo.currentData()
    for index in range(combo.count() - 1, -1, -1):
        data = combo.itemData(index)
        if data is not None and int(data) in (4, 5, 6, 7):
            combo.removeItem(index)

    if _profile_supports_low_visibility(_selected_profile(window)):
        combo.addItem("VanishLow", 4)
        combo.addItem("AppearLow", 5)

    for index in range(combo.count()):
        if combo.itemData(index) == current:
            combo.setCurrentIndex(index)
            break
    else:
        visible = combo.findData(3)
        if visible >= 0:
            combo.setCurrentIndex(visible)


def _install_profile_visibility_choices(window) -> None:
    _refresh_visibility_choices(window)
    if getattr(window, "_phase12_visibility_profile_hooks", False):
        return
    window._phase12_visibility_profile_hooks = True
    for action in getattr(window, "profile_actions", {}).values():
        action.toggled.connect(
            lambda checked, active_window=window: (
                _refresh_visibility_choices(active_window) if checked else None
            )
        )


def _patch_phase10_visibility_labels() -> None:
    """Correct the legacy inspector table without rewriting the large installer."""

    try:
        import stepnx.gui.phase10_install as phase10
    except ImportError:
        return
    table = getattr(phase10, "_VIS_STATUS", None)
    if not isinstance(table, dict):
        return
    table.pop(6, None)
    table.pop(7, None)
    table[4] = "VanishLow"
    table[5] = "AppearLow"


def _install_roll_tool(window) -> None:
    """Expose Roll as a first-class drag tool without changing raw semantics."""

    combo = getattr(window, "tool_combo", None)
    if combo is None:
        return
    if combo.findText("Roll") < 0:
        toggle_index = combo.findText("Toggle")
        combo.insertItem(max(0, toggle_index + 1), "Roll", NoteTool.ROLL.value)

    if getattr(window, "_phase12_roll_tool_hooks", False):
        return
    window._phase12_roll_tool_hooks = True

    import stepnx.gui.phase10_install as phase10

    original_drag_preview_allowed = window._phase10_drag_preview_allowed
    original_hold = window._phase10_hold

    def roll_drag_preview_allowed(self, widget, start, end) -> bool:
        if self.tool_combo.currentData() != NoteTool.ROLL.value:
            return original_drag_preview_allowed(widget, start, end)
        document_index = phase10._active_document_index(self, widget)
        if document_index is None:
            return False
        return phase10._drag_rows_empty(
            self.sessions[document_index].current, start, end
        )

    def create_roll(self, widget, start, end) -> None:
        if self.tool_combo.currentData() != NoteTool.ROLL.value:
            return original_hold(widget, start, end)

        document_index = phase10._active_document_index(self, widget)
        if document_index is None:
            return
        start_segment, start_row, lane = start
        end_segment, end_row, end_lane = end
        if (
            start_segment.block.stable_id != end_segment.block.stable_id
            or lane != end_lane
        ):
            return

        document = self.sessions[document_index].current
        found = phase10._find_row(
            document, start_segment.block.rows[start_row].stable_id
        )
        if found is None:
            return
        _split, block, actual_start, start_model_row = found
        try:
            start_type = phase10._cell_raw(start_model_row, lane)[0] & 0x0F
            if start_type != 0:
                # A Roll click remains a direct Roll-Head placement. Do not
                # silently manufacture a partial replacement inside a long.
                return phase10._phase10_click(self, widget, start)
            if not phase10._drag_rows_empty(document, start, end):
                self.statusBar().showMessage(
                    "Roll requires an empty span; gesture was not applied",
                    4000,
                )
                return

            _tool, value, functionality, visibility = phase10._tool_state(self)
            lo, hi = sorted((start_row, end_row))
            rows = start_segment.block.rows
            commands = []
            for index in range(lo, hi + 1):
                part = (
                    NoteTool.HOLD_HEAD
                    if index == lo
                    else NoteTool.HOLD_TAIL
                    if index == hi
                    else NoteTool.HOLD_BODY
                )
                raw = bytearray(
                    phase10._regular_note_raw(
                        self, part, value, functionality, visibility
                    )
                )
                # Official NXA Roll fixtures use the 47/4B/4F family: the
                # sustain/can-hold bit is clear on the complete run.
                raw[0] &= ~0x10
                commands.append(
                    SetNoteAt(rows[index].stable_id, lane, bytes(raw))
                )
            phase10._apply(
                self,
                document_index,
                widget,
                phase10._SequenceCommand(commands),
            )
        except (ValueError, IndexError) as exc:
            QMessageBox.critical(self, "Cannot create Roll", str(exc))

    window._phase10_drag_preview_allowed = MethodType(
        roll_drag_preview_allowed, window
    )
    window._phase10_hold = MethodType(create_roll, window)


def install_phase12_editor_note_visuals(window) -> None:
    if getattr(window, "_phase12_editor_note_visuals_installed", False):
        _refresh_visibility_choices(window)
        _install_roll_tool(window)
        return
    window._phase12_editor_note_visuals_installed = True
    _install_note_renderer()
    _patch_phase10_visibility_labels()
    _install_profile_visibility_choices(window)
    _install_roll_tool(window)
