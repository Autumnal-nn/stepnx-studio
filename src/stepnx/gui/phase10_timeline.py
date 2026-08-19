from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QMenu

from stepnx.authoring.selection import CellSelection
from stepnx.gui.timeline_widget import TimelineWidget as _BaseTimelineWidget


class Phase10TimelineWidget(_BaseTimelineWidget):
    """StepEdit-style Toggle/edit gestures layered over the native viewport."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._phase10_press_hit = None
        self._phase10_last_hit = None
        self._phase10_drag_cancelled = False

    def set_selection(self, selection) -> None:
        super().set_selection(selection)
        host = self.window()
        updater = getattr(host, "_phase10_update_selection_status", None)
        if callable(updater):
            updater(self)

    def _phase10_hit(self, event):
        content_x = event.position().x() + self.horizontalScrollBar().value()
        content_y = event.position().y() + self.verticalScrollBar().value()
        return self._snapped_hit(self._layout.cell_at(content_x, content_y))

    def _phase10_row_hit(self, event):
        content_y = event.position().y() + self.verticalScrollBar().value()
        row = self._layout.row_at_y(content_y)
        if row is None:
            return None
        segment, row_index = row
        row_index = self._layout.snap_row_index(segment, row_index, self._snap_beats)
        return segment, row_index

    def mousePressEvent(self, event) -> None:
        content_x = event.position().x() + self.horizontalScrollBar().value()
        content_y = event.position().y() + self.verticalScrollBar().value()
        segment = self._layout.segment_at_y(content_y)
        if segment is not None:
            self.inspectionRequested.emit(segment.split_id, segment.block.stable_id)

        if event.button() == Qt.MouseButton.RightButton and segment is not None:
            host = self.window()
            row_hit = self._phase10_row_hit(event)
            row_index = None if row_hit is None else row_hit[1]
            menu = QMenu(self)
            split_menu = menu.addMenu("Split")
            a_split_here = split_menu.addAction("Split here")
            a_merge = split_menu.addAction("Merge Splits…")
            a_resize = split_menu.addAction("Resize Split…")
            a_split_here.setEnabled(row_index is not None and row_index > 0)
            try:
                split_index = next(
                    i for i, item in enumerate(self._snapshot.splits)
                    if item.stable_id == segment.split_id
                )
                a_merge.setEnabled(split_index + 1 < len(self._snapshot.splits))
            except StopIteration:
                a_merge.setEnabled(False)

            block_menu = menu.addMenu("Block")
            a_create_block = block_menu.addAction("Create Block after")
            a_duplicate_block = block_menu.addAction("Duplicate Block")
            a_delete_block = block_menu.addAction("Delete Block…")

            chosen = menu.exec(event.globalPosition().toPoint())
            action_map = {
                a_split_here: "split-here",
                a_merge: "merge-splits",
                a_resize: "resize-split",
                a_create_block: "insert-block",
                a_duplicate_block: "duplicate-block",
                a_delete_block: "delete-block",
            }
            command = action_map.get(chosen)
            handler = getattr(host, "_phase10_context_action", None)
            if command is not None and callable(handler):
                handler(
                    self,
                    command,
                    segment.split_id,
                    segment.block.stable_id,
                    row_index,
                )
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._phase10_hit(event)
            if hit is None:
                # StepEdit-style blank click: clear the cell selection without
                # creating an edit gesture. This makes it possible to return to
                # a neutral Play/Pause state after inspecting a note.
                self.set_selection(CellSelection())
                event.accept()
                return
            modifiers = event.modifiers()
            if modifiers & (
                Qt.KeyboardModifier.ShiftModifier
                | Qt.KeyboardModifier.ControlModifier
            ):
                hit_segment, row_index, lane = hit
                self._select_hit(hit_segment, row_index, lane, modifiers)
                event.accept()
                return
            self._phase10_press_hit = hit
            self._phase10_last_hit = hit
            self._phase10_drag_cancelled = False
            self.editGestureStarted.emit()
            hit_segment, row_index, lane = hit
            self._select_hit(
                hit_segment, row_index, lane, Qt.KeyboardModifier.NoModifier
            )
            self.viewport().update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._phase10_press_hit is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            hit = self._phase10_hit(event)
            if hit is not None:
                start_segment, _start_row, start_lane = self._phase10_press_hit
                segment, _row, lane = hit
                if (
                    segment.block.stable_id != start_segment.block.stable_id
                    or lane != start_lane
                ):
                    self._phase10_drag_cancelled = True
                else:
                    self._phase10_last_hit = hit
            self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._phase10_press_hit is not None
        ):
            start = self._phase10_press_hit
            end = self._phase10_last_hit or start
            self._phase10_press_hit = None
            self._phase10_last_hit = None
            host = self.window()
            try:
                _segment_a, row_a, lane_a = start
                _segment_b, row_b, lane_b = end
                if (
                    not self._phase10_drag_cancelled
                    and lane_a == lane_b
                    and row_a != row_b
                ):
                    handler = getattr(host, "_phase10_hold", None)
                    if callable(handler):
                        handler(self, start, end)
                elif not self._phase10_drag_cancelled:
                    handler = getattr(host, "_phase10_click", None)
                    if callable(handler):
                        handler(self, start)
            finally:
                self._phase10_drag_cancelled = False
                self.editGestureFinished.emit()
                self.viewport().update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._phase10_press_hit is None or self._phase10_last_hit is None:
            return
        if self._phase10_drag_cancelled:
            return
        start_segment, start_row, lane = self._phase10_press_hit
        end_segment, end_row, end_lane = self._phase10_last_hit
        if (
            start_segment.block.stable_id != end_segment.block.stable_id
            or lane != end_lane
            or start_row == end_row
        ):
            return
        host = self.window()
        validator = getattr(host, "_phase10_drag_preview_allowed", None)
        if not callable(validator) or not validator(self, self._phase10_press_hit, self._phase10_last_hit):
            return

        lo, hi = sorted((start_row, end_row))
        x_scroll = self.horizontalScrollBar().value()
        y_scroll = self.verticalScrollBar().value()
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(0.58)
        accent = QColor("#78b7ff")
        painter.setPen(QPen(accent.lighter(145), 1.6))
        painter.setBrush(accent)
        try:
            head_rect = None
            tail_rect = None
            for index in range(lo, hi + 1):
                x, y, width, height = self._geometry.note_rect(
                    lane,
                    start_segment.y_for_row(index),
                    start_segment.row_height,
                )
                rect = QRectF(x - x_scroll, y - y_scroll, width, height)
                if index == lo:
                    head_rect = rect
                elif index == hi:
                    tail_rect = rect
                else:
                    body_width = max(5.0, rect.width() * 0.28)
                    painter.drawRoundedRect(
                        QRectF(
                            rect.center().x() - body_width / 2,
                            rect.top(),
                            body_width,
                            rect.height(),
                        ),
                        2,
                        2,
                    )
            if head_rect is not None and tail_rect is not None:
                shaft_width = max(5.0, head_rect.width() * 0.24)
                painter.drawRect(
                    QRectF(
                        head_rect.center().x() - shaft_width / 2,
                        min(head_rect.center().y(), tail_rect.center().y()),
                        shaft_width,
                        abs(tail_rect.center().y() - head_rect.center().y()),
                    )
                )
                painter.drawRoundedRect(head_rect, 5, 5)
                painter.drawRoundedRect(tail_rect, 5, 5)
        finally:
            painter.end()
    @staticmethod
    def _phase10_special_tile(atlas, cell: int):
        if cell < 0:
            return None
        capacity = atlas.columns * atlas.rows
        if cell >= capacity:
            return None
        return cell % atlas.columns, cell // atlas.columns

    def _phase10_draw_special_cell(self, painter, atlas, cell: int, rect) -> bool:
        tile = self._phase10_special_tile(atlas, cell)
        if tile is None:
            return False
        column, row = tile
        return self._draw_atlas_tile(painter, atlas, column, row, rect)

    def _draw_noteskin_note(self, painter, lane, y, row_height, raw, rect):
        pack = getattr(self, "_noteskin_pack", None)
        profile = getattr(getattr(self, "_snapshot", None), "profile", "")
        if (
            profile == "nxa-step5-patched"
            and pack is not None
            and pack.special_items is not None
        ):
            atlas = pack.special_items

            # Inert SPECIAL.PNG call. raw[2] physically permits cells 0..96
            # through 64+cell. The visual renderer draws the cell only when it
            # actually exists in the loaded atlas; this avoids inventing a 97th
            # tile for a 32x3 sheet while preserving raw cell 96 authoring.
            if (
                raw[0] == 0x01
                and raw[1] == 0x03
                and 64 <= raw[2] <= 160
                and (raw[3] & 0x3F) == 0
            ):
                return self._phase10_draw_special_cell(
                    painter, atlas, raw[2] - 64, rect
                )

            # Number Block 00..99. The engine composes two SPECIAL.PNG cells in
            # one square: units first, then the tens overlay (10+tens). Drawing
            # in this order matches the renderer's layered digit composition.
            if (
                raw[0] == 0x02
                and raw[1] == 0x03
                and 100 <= raw[2] <= 199
                and (raw[3] & 0x3F) == 0x01
            ):
                number = raw[2] - 100
                tens_cell = 10 + number // 10
                units_cell = number % 10
                units = self._phase10_draw_special_cell(
                    painter, atlas, units_cell, rect
                )
                tens = self._phase10_draw_special_cell(
                    painter, atlas, tens_cell, rect
                )
                return units or tens

        return super()._draw_noteskin_note(
            painter, lane, y, row_height, raw, rect
        )
