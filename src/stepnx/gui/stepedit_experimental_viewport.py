"""Experimental Qt viewport for the STEPEdit-inspired authoring geometry.

The host passes one EditorController backed by the existing workspace
CommandStack. This widget neither serializes NX20 nor publishes files.
"""
from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractScrollArea, QApplication

from stepnx.authoring.editor_controller import (
    EditorContextError,
    EditorController,
    InteractionTool,
)
from stepnx.authoring.selection import CellSelection, CellTarget
from stepnx.authoring.stepedit_hold import HoldGestureError, plan_hold_creation, plan_hold_erasure
from stepnx.authoring.stepedit_layout import StepEditGeometry, StepEditGridLayout, StepEditRegion
from stepnx.authoring.tools import NoteTool, note_tool_raw
from stepnx.core.model import EmptyRow, LightmapRow, NoteRow, PackedNoteRow
from stepnx.gui.stepedit_visual_style import (
    INDICATOR_BACKGROUND, LANE_BOUNDARY, MAJOR_GRID, MINOR_GRID,
    NOTE_BACKGROUND, PROPERTIES_BACKGROUND, VERTICAL_GRID,
    SELECTION_BACKGROUND, StepEditAtlasArtist, scaled_editor_geometry,
    split_background, wheel_line_pixels, wheel_notch_pixels,
)


_EMPTY = b"\x00\x00\x00\x00"
_HOLD_TYPES = frozenset((7, 0xB, 0xF))
_SCROLL_MAX = 2**31 - 2


def _raw_cell(row, lane: int) -> bytes:
    if isinstance(row, EmptyRow):
        return _EMPTY
    if isinstance(row, PackedNoteRow):
        return row.cell(lane).raw
    if isinstance(row, NoteRow):
        return row.cells[lane].raw
    if isinstance(row, LightmapRow):
        return row.raw_channels
    raise TypeError(f"unsupported row type: {type(row).__name__}")


def _row_id(rows, index: int) -> int:
    # One bounded row access; never enumerate source-backed CompactRows.
    return rows[index].stable_id


class StepEditExperimentalViewport(QAbstractScrollArea):
    """Editable experimental surface; default Studio viewport remains unchanged."""

    documentChanged = Signal(object)
    routeChanged = Signal()
    selectionChanged = Signal(object)
    statusMessage = Signal(str)

    def __init__(
        self,
        controller: EditorController,
        *,
        tap_raw: Callable[[], bytes] | None = None,
        hold_raw: Callable[[NoteTool], bytes] | None = None,
        noteskin_pack=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._tap_raw = tap_raw or (lambda: note_tool_raw(NoteTool.TAP))
        self._hold_raw = hold_raw or (lambda part: note_tool_raw(part))
        self._zoom_percent = 100
        self._geometry = scaled_editor_geometry(self._zoom_percent)
        self._artist = StepEditAtlasArtist(noteskin_pack)
        self.layout_model = StepEditGridLayout(controller.snapshot, self._geometry)
        self._scroll_scale = 1.0
        self._wheel_residual = 0.0
        self._lease = None
        self._pressed = None
        self._last_paint_hit = None
        self._hold_preview_hit = None
        self._select_anchor = None
        self._select_current = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._update_scrollbars()

    def _scroll_y(self) -> float:
        return self.verticalScrollBar().value() * self._scroll_scale

    def _update_scrollbars(self, *, scroll_y: float | None = None) -> None:
        viewport_height = max(1, self.viewport().height())
        limit = max(0.0, self.layout_model.content_height - viewport_height)
        self._scroll_scale = max(1.0, limit / _SCROLL_MAX)
        self.verticalScrollBar().setRange(0, int(math.ceil(limit / self._scroll_scale)))
        self.verticalScrollBar().setPageStep(max(1, int(viewport_height / self._scroll_scale)))
        self.verticalScrollBar().setSingleStep(
            max(1, int(round(wheel_line_pixels(4 * self._geometry.vertical_zoom) / self._scroll_scale)))
        )
        self.horizontalScrollBar().setRange(
            0, max(0, int(math.ceil(self.layout_model.content_width - self.viewport().width())))
        )
        if scroll_y is not None:
            self.verticalScrollBar().setValue(int(round(max(0, scroll_y) / self._scroll_scale)))
        self.viewport().update()

    def _rebuild_layout(self, *, scroll_y: float | None = None) -> None:
        self.layout_model = StepEditGridLayout(self.controller.snapshot, self._geometry)
        self._update_scrollbars(scroll_y=scroll_y)

    def set_zoom(self, percent: int) -> None:
        # Only exact presets are supported. Do not multiply temporal spacing
        # twice: the geometry's beat_height is constant at 192.
        self._cancel_interaction()
        new_geometry = scaled_editor_geometry(percent)
        old = self.layout_model
        scroll = self._scroll_y()
        anchor_y = self.viewport().height() / 2.0
        hit = old.hit_test(old.x_for_lane(0), anchor_y, scroll_y=scroll)
        if hit.region is StepEditRegion.BODY:
            anchor = (hit.split_id, hit.row_index)
        elif old.segments:
            anchor = (old.segments[0].split_id, 0)
        else:
            anchor = None
        self._zoom_percent = percent
        self._geometry = new_geometry
        self._rebuild_layout()
        if anchor is not None:
            self._update_scrollbars(
                scroll_y=self.layout_model.scroll_for_anchor(
                    old, anchor[0], anchor[1], anchor_y,
                )
            )

    def set_tool(self, tool: InteractionTool) -> None:
        self._cancel_interaction()
        self.controller.set_tool(tool)
        self.viewport().update()

    def select_block(self, split_id: int, block_id: int) -> None:
        self._cancel_interaction()
        scroll = self._scroll_y()
        self.controller.select_block(split_id, block_id)
        self._rebuild_layout(scroll_y=scroll)
        self.routeChanged.emit()

    def cycle_block(self, split_id: int, delta: int = 1) -> None:
        self._cancel_interaction()
        scroll = self._scroll_y()
        self.controller.cycle_block(split_id, delta)
        self._rebuild_layout(scroll_y=scroll)
        self.routeChanged.emit()

    def undo(self) -> None:
        if self._lease is not None or self._pressed is not None:
            self._cancel_interaction()
            return
        if self.controller._stack.can_undo:
            self.controller.undo()
            self._rebuild_layout(scroll_y=self._scroll_y())
            self.documentChanged.emit(self.controller.document)

    def redo(self) -> None:
        if self._lease is not None or self._pressed is not None:
            self._cancel_interaction()
            return
        if self.controller._stack.can_redo:
            self.controller.redo()
            self._rebuild_layout(scroll_y=self._scroll_y())
            self.documentChanged.emit(self.controller.document)

    def _cancel_interaction(self) -> None:
        self.controller.cancel_stroke()
        self._lease = None
        self._pressed = None
        self._last_paint_hit = None
        self._hold_preview_hit = None
        self._select_anchor = None
        self._select_current = None
        self.viewport().update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scrollbars()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self.viewport().update()

    def wheelEvent(self, event) -> None:
        """Match CScrollView's 24*zoom line step and Windows wheel-line setting.

        Qt default scrollbars use a small, unrelated singleStep; forwarding the
        event to QAbstractScrollArea makes one notch far slower than STEPEdit.
        """
        pixels = event.pixelDelta()
        if not pixels.isNull():
            movement = float(pixels.y())
        else:
            lines = int(QApplication.wheelScrollLines())
            movement = (
                event.angleDelta().y() / 120.0
            ) * wheel_notch_pixels(
                4 * self._geometry.vertical_zoom, lines, self.viewport().height()
            )
        if not movement:
            event.accept()
            return
        limit = max(0.0, self.layout_model.content_height - self.viewport().height())
        requested = self._scroll_y() - movement + self._wheel_residual
        requested = min(limit, max(0.0, requested))
        position = int(round(requested / self._scroll_scale))
        self.verticalScrollBar().setValue(position)
        actual = self._scroll_y()
        self._wheel_residual = requested - actual
        if requested == 0.0 or requested == limit:
            self._wheel_residual = 0.0
        event.accept()

    def _hit(self, event):
        return self.layout_model.hit_test(
            event.position().x() + self.horizontalScrollBar().value(),
            event.position().y(),
            scroll_y=self._scroll_y(),
        )

    def _target(self, hit):
        if hit.region is not StepEditRegion.BODY:
            return None
        rows = self.controller.snapshot.active_block(hit.split_id).rows
        return CellTarget(_row_id(rows, hit.row_index), hit.lane)

    def _existing_raw(self, hit) -> bytes:
        rows = self.controller.snapshot.active_block(hit.split_id).rows
        return _raw_cell(rows[hit.row_index], hit.lane)

    def _reject_hold(self, hit) -> bool:
        if self._existing_raw(hit)[0] & 0x0F in _HOLD_TYPES:
            self.statusMessage.emit(
                "Hold encountered. Use the current Studio editor for Hold operations."
            )
            return True
        return False

    def _extend_paint_to(self, hit) -> None:
        """Fill intervening rows of a same-lane drag, even if Qt skips events.

        Never cross Blocks or rewrite a partial Hold. Each visited target is
        revalidated by the scoped controller before it joins the pending edit.
        """
        previous = self._last_paint_hit
        if previous is not None and previous.lane == hit.lane:
            rows = self.controller.snapshot.active_block(hit.split_id).rows
            start = previous.row_index
            stop = hit.row_index
            step = 1 if stop >= start else -1
            for index in range(start, stop + step, step):
                raw = _raw_cell(rows[index], hit.lane)
                if raw[0] & 0x0F in _HOLD_TYPES:
                    raise EditorContextError("paint stroke intersects a Hold")
                self.controller.extend_stroke(
                    self._lease, CellTarget(_row_id(rows, index), hit.lane)
                )
        else:
            self.controller.extend_stroke(self._lease, self._target(hit))
        self._last_paint_hit = hit

    def _commit(self, scope, target: CellTarget, raw: bytes) -> None:
        try:
            self.controller.set_note(scope, target, raw)
        except (EditorContextError, ValueError) as exc:
            self.statusMessage.emit(str(exc))
            return
        self._rebuild_layout(scroll_y=self._scroll_y())
        self.documentChanged.emit(self.controller.document)

    def _apply_hold_gesture(self, scope, initial, final) -> bool:
        """Atomic create/erase via the same domain stack and snapshot guards."""
        block = self.controller.snapshot.active_block(initial.split_id)
        existing = self._existing_raw(initial)
        part_map = {
            7: NoteTool.HOLD_HEAD,
            0xB: NoteTool.HOLD_BODY,
            0xF: NoteTool.HOLD_TAIL,
        }
        try:
            if (existing[0] & 0x0F) in part_map:
                edits = plan_hold_erasure(block, initial.lane, initial.row_index)
            else:
                edits = plan_hold_creation(
                    block, initial.lane, initial.row_index, final.row_index,
                    lambda kind: self._hold_raw(part_map[kind]),
                )
            self.controller.apply_note_batch(scope, edits)
        except (HoldGestureError, EditorContextError, ValueError, IndexError) as exc:
            self.statusMessage.emit(str(exc))
            return False
        self._rebuild_layout(scroll_y=self._scroll_y())
        self.documentChanged.emit(self.controller.document)
        return True

    def _start_selection(self, hit) -> None:
        self._select_anchor = hit
        self._select_current = hit
        self.viewport().update()

    def _finish_selection(self, hit, *, additive: bool = False) -> None:
        anchor = self._select_anchor
        self._select_anchor = None
        self._select_current = None
        if anchor is None or hit.region is not StepEditRegion.BODY:
            self.viewport().update()
            return
        if (anchor.split_id, anchor.block_id) != (hit.split_id, hit.block_id):
            self.statusMessage.emit("Selection stays inside the selected Block in M4.")
            self.viewport().update()
            return
        rows = self.controller.snapshot.active_block(hit.split_id).rows
        targets = set(self.controller.session.selection.targets) if additive else set()
        for row in range(min(anchor.row_index, hit.row_index), max(anchor.row_index, hit.row_index) + 1):
            row_id = _row_id(rows, row)
            for lane in range(min(anchor.lane, hit.lane), max(anchor.lane, hit.lane) + 1):
                targets.add(CellTarget(row_id, lane))
        self.controller.session.selection = CellSelection(
            frozenset(targets),
            CellTarget(_row_id(rows, anchor.row_index), anchor.lane),
        )
        self.selectionChanged.emit(self.controller.session.selection)
        self.viewport().update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus()
        hit = self._hit(event)
        if hit.region is StepEditRegion.INDICATOR and hit.split_id is not None:
            self.cycle_block(hit.split_id)
            return
        if hit.region is not StepEditRegion.BODY:
            return
        if self.controller.snapshot.effective_lightmap:
            self.statusMessage.emit("Lightmap editing remains in the existing Studio viewport.")
            return
        try:
            scope = self.controller.capture_scope(hit.split_id, hit.block_id)
            target = self._target(hit)
            if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or self.controller.session.tool is InteractionTool.SELECT:
                self._pressed = (scope, hit)
                self._start_selection(hit)
                return
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.controller.session.selection = self.controller.session.selection.toggle(target)
                self.selectionChanged.emit(self.controller.session.selection)
                self.viewport().update()
                return
            tool = self.controller.session.tool
            if tool in (InteractionTool.ADD, InteractionTool.ERASE) and self._reject_hold(hit):
                return
            self._pressed = (scope, hit)
            if tool in (InteractionTool.ADD, InteractionTool.ERASE):
                raw = self._tap_raw() if tool is InteractionTool.ADD else _EMPTY
                self._lease = self.controller.start_stroke(scope, target, raw)
                self._last_paint_hit = hit
            elif tool is InteractionTool.TOGGLE:
                pass  # Commit a tap/erase only after a same-cell release.
            else:
                self.statusMessage.emit("This experimental tool is not yet implemented.")
                self._pressed = None
        except (EditorContextError, ValueError) as exc:
            self._cancel_interaction()
            self.statusMessage.emit(str(exc))
        self.viewport().update()

    def mouseMoveEvent(self, event) -> None:
        if self._pressed is None:
            return
        hit = self._hit(event)
        if self._select_anchor is not None:
            if hit.region is StepEditRegion.BODY:
                self._select_current = hit
                self.viewport().update()
            return
        if self._lease is None:
            scope, start = self._pressed
            if self.controller.session.tool is InteractionTool.TOGGLE:
                if hit.region is StepEditRegion.BODY and (
                    hit.split_id, hit.block_id, hit.lane
                ) == (scope.split_id, scope.block_id, start.lane):
                    self._hold_preview_hit = hit
                    self.viewport().update()
                else:
                    self._hold_preview_hit = None
                    self.viewport().update()
            return
        if hit.region is not StepEditRegion.BODY:
            return
        scope, _ = self._pressed
        if (hit.split_id, hit.block_id) != (scope.split_id, scope.block_id):
            self._cancel_interaction()
            self.statusMessage.emit("Stroke cancelled at Split/Block boundary.")
            return
        if self._reject_hold(hit):
            self._cancel_interaction()
            return
        try:
            self._extend_paint_to(hit)
        except (EditorContextError, ValueError) as exc:
            self._cancel_interaction()
            self.statusMessage.emit(str(exc))
        self.viewport().update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._pressed is None:
            return
        hit = self._hit(event)
        if self._select_anchor is not None:
            self._finish_selection(
                hit, additive=bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            )
            self._pressed = None
            return
        scope, initial = self._pressed
        self._pressed = None
        self._hold_preview_hit = None
        if self._lease is not None:
            lease = self._lease
            if hit.region is not StepEditRegion.BODY or (
                hit.split_id, hit.block_id
            ) != (scope.split_id, scope.block_id):
                self._cancel_interaction()
                return
            if self._reject_hold(hit):
                self._cancel_interaction()
                return
            try:
                self._extend_paint_to(hit)
                self.controller.finish_stroke(lease)
            except (EditorContextError, ValueError) as exc:
                self._cancel_interaction()
                self.statusMessage.emit(str(exc))
                return
            self._lease = None
            self._last_paint_hit = None
            self._rebuild_layout(scroll_y=self._scroll_y())
            self.documentChanged.emit(self.controller.document)
            return
        if (hit.region is StepEditRegion.BODY and hit.split_id == initial.split_id
            and hit.block_id == initial.block_id
            and hit.lane == initial.lane):
            existing = self._existing_raw(initial)
            if hit.row_index != initial.row_index:
                self._apply_hold_gesture(scope, initial, hit)
                return
            if (existing[0] & 0x0F) in _HOLD_TYPES:
                self._apply_hold_gesture(scope, initial, hit)
                return
            if existing != _EMPTY and existing[0] & 0x0F == 0:
                self.statusMessage.emit("Unknown or opaque note bytes: Toggle will not discard them.")
                return
            try:
                raw = _EMPTY if existing != _EMPTY else self._tap_raw()
            except (ValueError, IndexError) as exc:
                self.statusMessage.emit(str(exc))
                return
            self._commit(scope, self._target(initial), raw)
        else:
            self.statusMessage.emit("Gesture cancelled outside the original lane/Block.")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._cancel_interaction()
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z:
                self.undo()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Y:
                self.redo()
                event.accept()
                return
        return super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        self._cancel_interaction()
        super().focusOutEvent(event)

    def hideEvent(self, event) -> None:
        self._cancel_interaction()
        super().hideEvent(event)

    def _draw_grid(self, painter: QPainter, view, scroll: float) -> None:
        """Draw the STEPEdit lane and beat raster before any note sprites."""
        seg = view.segment
        g = self.layout_model.geometry
        left = self.layout_model.grid_left
        right = self.layout_model.grid_right
        top = seg.top - scroll
        bottom = seg.bottom - scroll
        painter.fillRect(QRectF(0, top, left, bottom - top), INDICATOR_BACKGROUND)
        painter.fillRect(
            QRectF(left, top, right - left, bottom - top),
            split_background(seg.split_index),
        )
        painter.fillRect(
            QRectF(right, top, g.property_width, bottom - top),
            PROPERTIES_BACKGROUND,
        )
        # Selected cells keep an opaque, neutral background below the
        # grid lines and the existing noteskin sprite.
        selected = self.controller.session.selection.targets
        if selected:
            rows = self.controller.snapshot.active_block(seg.split_id).rows
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(SELECTION_BACKGROUND)
            for index in range(view.first_row, view.last_row):
                row_id = rows[index].stable_id
                y = seg.y_for_row(index) - scroll
                for lane in range(self.controller.snapshot.columns):
                    if CellTarget(row_id, lane) in selected:
                        painter.drawRect(
                            QRectF(
                                left + lane * g.lane_pitch, y,
                                g.lane_pitch, seg.row_pitch,
                            )
                        )

        painter.setPen(QPen(VERTICAL_GRID, 1))
        for lane in range(self.controller.snapshot.columns + 1):
            x = int(round(left + lane * g.lane_pitch))
            painter.drawLine(x, int(top), x, int(bottom))
        painter.setPen(QPen(LANE_BOUNDARY, 1))
        for lane in (0, self.controller.snapshot.columns):
            x = int(round(left + lane * g.lane_pitch))
            painter.drawLine(x, int(top), x, int(bottom))
        if self.controller.snapshot.columns == 10:
            center_x = int(round(left + 5 * g.lane_pitch))
            painter.drawLine(center_x, int(top), center_x, int(bottom))

        # One row may represent a fraction of a beat. Use the actual encoded
        # BeatSplit and BeatMeasure, never the visual tile height.
        block = self.controller.snapshot.active_block(seg.split_id)
        measure_rows = max(1, seg.beat_split * max(1, block.beat_measure))
        for index in range(view.first_row, view.last_row):
            y = int(round(seg.y_for_row(index) - scroll))
            major = index % measure_rows == 0
            painter.setPen(QPen(MAJOR_GRID if major else MINOR_GRID, 1))
            painter.drawLine(int(left), y, int(right), y)

        # Screenshot: outer right boundary remains red over row highlights.
        painter.setPen(QPen(LANE_BOUNDARY, 1))
        painter.drawLine(int(right), int(top), int(right), int(bottom))

    def _draw_notes(
        self, painter: QPainter, segment, first: int, last: int, scroll: float
    ) -> None:
        """Layer Hold shaft strips first, terminal tiles and taps second.

        Every 0xB occupies only its *encoded* row interval. The current
        96x96 image is never forced into that interval, and a head/tail is
        rendered once rather than repeated at each body row.
        """
        rows = self.controller.snapshot.active_block(segment.split_id).rows
        pitch = self.layout_model.geometry.lane_pitch
        source_offset = self.controller.snapshot.start_column
        columns = self.controller.snapshot.columns

        # Pass 1: stretch only the repeatable atlas shaft strip along the
        # temporal span. The terminal tiles are handled in the next pass.
        for index in range(first, last):
            row_top = segment.y_for_row(index) - scroll
            row = rows[index]
            if isinstance(row, LightmapRow):
                continue
            for lane in range(columns):
                raw = _raw_cell(row, lane)
                kind = raw[0] & 0x0F
                if kind not in _HOLD_TYPES:
                    continue
                # Head and tail glyphs contain their own tip decorations.
                # Keep any shaft visible between the terminals; at small
                # row spacing they naturally overlap without shrinking.
                if kind == 0x7:
                    top = row_top + min(pitch / 2, segment.row_pitch)
                    bottom = row_top + segment.row_pitch
                elif kind == 0xF:
                    top = row_top
                    bottom = row_top + min(pitch / 2, segment.row_pitch)
                else:
                    top = row_top
                    bottom = row_top + segment.row_pitch
                if bottom <= top:
                    continue
                rect = QRectF(
                    self.layout_model.x_for_lane(lane, center=False),
                    top, pitch, bottom - top,
                )
                if not self._artist.draw_hold_shaft(
                    painter, rect, source_offset + lane, raw,
                ):
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor("#76DDF2"))
                    painter.drawRect(QRectF(
                        rect.x() + pitch * 0.37, rect.y(),
                        pitch * 0.26, rect.height(),
                    ))

        # Pass 2: source-backed Tap/Item/Division glyphs, and exactly one
        # terminal tile for each encoded 0x7/0xF cell. 0xB draws no glyph.
        for index in range(first, last):
            row_top = segment.y_for_row(index) - scroll
            row = rows[index]
            if isinstance(row, LightmapRow):
                continue
            for lane in range(columns):
                raw = _raw_cell(row, lane)
                kind = raw[0] & 0x0F
                if not kind or kind == 0xB:
                    continue
                destination = QRectF(
                    self.layout_model.x_for_lane(lane, center=False),
                    row_top, pitch, pitch,
                )
                self._artist.draw(
                    painter, destination, source_offset + lane,
                    raw, segment.row_pitch,
                )

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        try:
            painter.fillRect(self.viewport().rect(), NOTE_BACKGROUND)
            if not self.layout_model.segments:
                return
            scroll = self._scroll_y()
            painter.save()
            painter.translate(-self.horizontalScrollBar().value(), 0)
            # A sprite extends up to 24 px past its logical row, including
            # when multiple row starts occupy a single physical pixel.
            min_pitch = min(seg.row_pitch for seg in self.layout_model.segments)
            tile_pixels = self.layout_model.geometry.lane_pitch
            overscan = min(10_000, max(2, int(math.ceil(tile_pixels / min_pitch)) + 1))
            visible = self.layout_model.visible_segments(
                scroll, self.viewport().height(), overscan_rows=overscan
            )
            # Two independent passes reproduce STEPEdit's grid-then-sprite
            # layering, so a dense note is not hidden by a later gridline.
            for view in visible:
                self._draw_grid(painter, view, scroll)
            for view in visible:
                seg = view.segment
                self._draw_notes(painter, seg, view.first_row, view.last_row, scroll)
                caption_y = max(12, int(seg.top - scroll + 14))
                if caption_y <= self.viewport().height():
                    painter.setPen(QColor("#050505"))
                    painter.drawText(2, caption_y, f"{seg.split_index + 1:03d}")
                    painter.drawText(
                        int(self.layout_model.grid_right + 5), caption_y,
                        f"Block {seg.block_index + 1}  BS {seg.beat_split}"
                    )
            if (
                self._hold_preview_hit is not None
                and self._pressed is not None
                and self.controller.session.tool is InteractionTool.TOGGLE
            ):
                _scope, anchor = self._pressed
                final = self._hold_preview_hit
                if (anchor.split_id, anchor.block_id, anchor.lane) == (
                    final.split_id, final.block_id, final.lane
                ) and anchor.row_index != final.row_index:
                    seg = self.layout_model.segment(anchor.split_id)
                    left = self.layout_model.x_for_lane(anchor.lane, center=False)
                    width = self.layout_model.geometry.lane_pitch
                    top = seg.y_for_row(min(anchor.row_index, final.row_index)) - scroll
                    bottom = seg.y_for_row(max(anchor.row_index, final.row_index)) - scroll
                    painter.setPen(QPen(QColor("#14578a"), 1))
                    painter.setBrush(QColor(89, 213, 254, 105))
                    painter.drawRect(QRectF(
                        left + width * 0.37, top + width * 0.5,
                        width * 0.26, max(1.0, bottom - top),
                    ))
            if self._select_anchor is not None and self._select_current is not None:
                start, end = self._select_anchor, self._select_current
                if (
                    end.region is StepEditRegion.BODY
                    and (start.split_id, start.block_id) == (end.split_id, end.block_id)
                ):
                    seg = self.layout_model.segment(start.split_id)
                    left = self.layout_model.x_for_lane(min(start.lane, end.lane), center=False)
                    right = self.layout_model.x_for_lane(max(start.lane, end.lane), center=False)
                    top = seg.y_for_row(min(start.row_index, end.row_index)) - scroll
                    bottom = seg.y_for_row(max(start.row_index, end.row_index)) - scroll + seg.row_pitch
                    painter.setPen(QPen(QColor("#ffe089"), 1))
                    painter.setBrush(QColor(255, 224, 137, 45))
                    painter.drawRect(QRectF(left, top, right - left + self.layout_model.geometry.lane_pitch, bottom - top))
            if self._lease is not None and self.controller.session.gesture is not None:
                painter.setBrush(QColor(63, 173, 241, 110))
                painter.setPen(Qt.PenStyle.NoPen)
                for target in self.controller.session.gesture.targets:
                    for seg in self.layout_model.segments:
                        rows = self.controller.snapshot.active_block(seg.split_id).rows
                        base = getattr(rows, "base", rows)
                        # Preview only: find row via sparse indexed IDs where available.
                        ids = getattr(base, "_row_ids", None)
                        if ids is None:
                            continue
                        from bisect import bisect_left
                        idx = bisect_left(ids, target.row_id)
                        if idx >= len(ids) or int(ids[idx]) != target.row_id:
                            continue
                        y = seg.y_for_row(idx) - scroll
                        x = self.layout_model.x_for_lane(target.lane)
                        box = self.layout_model.geometry.lane_pitch
                        painter.drawRect(QRectF(
                            x - box / 2, y, box, box
                        ))
                        break
            painter.restore()
        finally:
            painter.end()
