"""Experimental Qt viewport for the STEPEdit-inspired authoring geometry.

The host passes one EditorController backed by the existing workspace
CommandStack. This widget neither serializes NX20 nor publishes files.
"""
from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractScrollArea

from stepnx.authoring.editor_controller import (
    EditorContextError,
    EditorController,
    InteractionTool,
)
from stepnx.authoring.selection import CellSelection, CellTarget
from stepnx.authoring.stepedit_layout import StepEditGeometry, StepEditGridLayout, StepEditRegion
from stepnx.authoring.tools import NoteTool, note_tool_raw
from stepnx.core.model import EmptyRow, LightmapRow, NoteRow, PackedNoteRow


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
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._tap_raw = tap_raw or (lambda: note_tool_raw(NoteTool.TAP))
        self._geometry = StepEditGeometry(vertical_zoom=4)
        self.layout_model = StepEditGridLayout(controller.snapshot, self._geometry)
        self._scroll_scale = 1.0
        self._lease = None
        self._pressed = None
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
        self.horizontalScrollBar().setRange(
            0, max(0, int(math.ceil(self.layout_model.content_width - self.viewport().width())))
        )
        if scroll_y is not None:
            self.verticalScrollBar().setValue(int(round(max(0, scroll_y) / self._scroll_scale)))
        self.viewport().update()

    def _rebuild_layout(self, *, scroll_y: float | None = None) -> None:
        self.layout_model = StepEditGridLayout(self.controller.snapshot, self._geometry)
        self._update_scrollbars(scroll_y=scroll_y)

    def set_zoom(self, zoom: float) -> None:
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
        self._geometry = self._geometry.with_zoom(zoom)
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
        self._select_anchor = None
        self._select_current = None
        self.viewport().update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scrollbars()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self.viewport().update()

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

    def _commit(self, scope, target: CellTarget, raw: bytes) -> None:
        try:
            self.controller.set_note(scope, target, raw)
        except (EditorContextError, ValueError) as exc:
            self.statusMessage.emit(str(exc))
            return
        self._rebuild_layout(scroll_y=self._scroll_y())
        self.documentChanged.emit(self.controller.document)

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
            if self._reject_hold(hit):
                return
            tool = self.controller.session.tool
            self._pressed = (scope, hit)
            if tool in (InteractionTool.ADD, InteractionTool.ERASE):
                raw = self._tap_raw() if tool is InteractionTool.ADD else _EMPTY
                self._lease = self.controller.start_stroke(scope, target, raw)
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
            self.controller.extend_stroke(self._lease, self._target(hit))
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
        if self._lease is not None:
            lease = self._lease
            self._lease = None
            if hit.region is StepEditRegion.BODY and (
                hit.split_id, hit.block_id
            ) == (scope.split_id, scope.block_id):
                if not self._reject_hold(hit):
                    try:
                        self.controller.extend_stroke(lease, self._target(hit))
                    except (EditorContextError, ValueError) as exc:
                        self._cancel_interaction()
                        self.statusMessage.emit(str(exc))
                        return
            else:
                self._cancel_interaction()
                return
            try:
                self.controller.finish_stroke(lease)
            except (EditorContextError, ValueError) as exc:
                self._cancel_interaction()
                self.statusMessage.emit(str(exc))
                return
            self._rebuild_layout(scroll_y=self._scroll_y())
            self.documentChanged.emit(self.controller.document)
            return
        if (hit.region is StepEditRegion.BODY and hit.split_id == initial.split_id
            and hit.block_id == initial.block_id
            and hit.row_index == initial.row_index and hit.lane == initial.lane):
            raw = _EMPTY if self._existing_raw(initial) != _EMPTY else self._tap_raw()
            self._commit(scope, self._target(initial), raw)
        else:
            self.statusMessage.emit("Hold dragging is reserved for a later M4 slice.")

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

    def _draw_notes(self, painter: QPainter, segment, first: int, last: int, scroll: float) -> None:
        rows = self.controller.snapshot.active_block(segment.split_id).rows
        spacing = self.layout_model.geometry.lane_pitch
        for index in range(first, last):
            y = segment.y_for_row(index) - scroll
            row = rows[index]
            if segment.row_pitch >= 4.0:
                painter.setPen(QPen(QColor("#353b48")))
                painter.drawLine(
                    int(self.layout_model.grid_left), int(round(y)),
                    int(self.layout_model.grid_right), int(round(y)),
                )
            for lane in range(self.controller.snapshot.columns):
                raw = _raw_cell(row, lane)
                if isinstance(row, LightmapRow):
                    if lane >= 3 or raw[lane] == 0:
                        continue
                    kind = 0x1
                else:
                    kind = raw[0] & 0x0F
                    if not kind:
                        continue
                x = self.layout_model.x_for_lane(lane)
                radius = min(9.0, max(2.0, segment.row_pitch * 0.36), spacing * 0.37)
                palette = {
                    1: "#df9c45", 2: "#c88aff", 3: "#64bfff",
                    7: "#75d5ff", 0xB: "#5c8cda", 0xF: "#75d5ff",
                }
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(palette.get(kind, "#dbdce0")))
                painter.drawRoundedRect(
                    int(x - radius), int(y + segment.row_pitch / 2 - radius),
                    int(radius * 2), int(radius * 2), 3, 3,
                )
                if CellTarget(row.stable_id, lane) in self.controller.session.selection.targets:
                    painter.setPen(QPen(QColor("#ffe089"), 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(
                        int(x - spacing / 2 + 1), int(y),
                        int(spacing - 2), max(1, int(segment.row_pitch)),
                    )

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        try:
            painter.fillRect(self.viewport().rect(), QColor("#1b1e24"))
            if not self.layout_model.segments:
                return
            scroll = self._scroll_y()
            painter.setPen(QPen(QColor("#425267")))
            for lane in range(self.controller.snapshot.columns + 1):
                x = self.layout_model.grid_left + lane * self.layout_model.geometry.lane_pitch
                painter.drawLine(int(x), 0, int(x), self.viewport().height())
            for view in self.layout_model.visible_segments(scroll, self.viewport().height()):
                seg = view.segment
                self._draw_notes(painter, seg, view.first_row, view.last_row, scroll)
                caption_y = max(12, int(seg.top - scroll + 14))
                if caption_y <= self.viewport().height():
                    painter.setPen(QColor("#b6bfcb"))
                    painter.drawText(
                        2, caption_y, f"S{seg.split_index + 1}"
                    )
                    painter.drawText(
                        int(self.layout_model.grid_right + 5), caption_y,
                        f"Block {seg.block_index + 1}  BS {seg.beat_split}"
                    )
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
                        painter.drawRect(int(x - 9), int(y + seg.row_pitch / 2 - 9), 18, 18)
                        break
        finally:
            painter.end()
