from __future__ import annotations

import math
from dataclasses import replace
from fractions import Fraction

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QMessageBox, QToolBar

from stepnx.authoring.snapshot import create_authoring_snapshot
from stepnx.core.model import EmptyRow, LightmapRow, NoteRow, PackedNoteRow
from stepnx.core.scalars import RawF32
from stepnx.gui.phase10_install import _resize_split_to_reference_rows


_BOUNDARY_TOLERANCE_PX = 6.0
_IDLE_REFRESH_MS = 120


class _ReplaceDocument:
    def __init__(self, result):
        self.result = result

    def apply(self, _document):
        return self.result


def _row_has_content(row) -> bool:
    if isinstance(row, EmptyRow):
        return False
    if isinstance(row, LightmapRow):
        return any(row.raw_channels)
    if isinstance(row, PackedNoteRow):
        return any(row.raw_cells)
    if isinstance(row, NoteRow):
        return any(cell.raw != b"\0\0\0\0" for cell in row.cells)
    return True


def _minimum_reference_rows(document, split_id: int, reference_block_id: int) -> int:
    """Smallest safe reference-row count without truncating any playable cell."""

    split = next(item for item in document.splits if item.stable_id == split_id)
    reference = next(
        item for item in split.blocks if item.stable_id == reference_block_id
    )
    reference_split = int(reference.beat_split.value)
    if reference_split <= 0:
        raise ValueError("reference Block has invalid Beat Split")

    minimum_beats = Fraction(0, 1)
    for block in split.blocks:
        beat_split = int(block.beat_split.value)
        if beat_split <= 0:
            raise ValueError(f"Block {block.stable_id} has invalid Beat Split")
        last_content = -1
        for index, row in enumerate(block.rows):
            if _row_has_content(row):
                last_content = index
        if last_content >= 0:
            minimum_beats = max(
                minimum_beats,
                Fraction(last_content + 1, beat_split),
            )

    minimum = math.ceil(minimum_beats * reference_split)
    return max(1, minimum)


def _rows_are_representable(document, split_id: int, reference_block_id: int, rows: int) -> bool:
    split = next(item for item in document.splits if item.stable_id == split_id)
    reference = next(
        item for item in split.blocks if item.stable_id == reference_block_id
    )
    reference_split = int(reference.beat_split.value)
    if reference_split <= 0 or rows < 1:
        return False
    beats = Fraction(rows, reference_split)
    return all(
        int(block.beat_split.value) > 0
        and (beats * int(block.beat_split.value)).denominator == 1
        for block in split.blocks
    )


def _nearest_representable_rows(
    document,
    split_id: int,
    reference_block_id: int,
    requested_rows: int,
) -> int:
    minimum = _minimum_reference_rows(document, split_id, reference_block_id)
    requested_rows = max(minimum, int(requested_rows))
    if _rows_are_representable(
        document, split_id, reference_block_id, requested_rows
    ):
        return requested_rows

    for distance in range(1, 65537):
        lower = requested_rows - distance
        upper = requested_rows + distance
        if lower >= minimum and _rows_are_representable(
            document, split_id, reference_block_id, lower
        ):
            return lower
        if _rows_are_representable(
            document, split_id, reference_block_id, upper
        ):
            return upper
    raise ValueError("no representable Split boundary was found")


def _resize_split_boundary_document(
    document,
    split_id: int,
    reference_block_id: int,
    requested_rows: int,
):
    """Resize upper Split and move the immediately lower Split in chart time."""

    split_index = next(
        i for i, item in enumerate(document.splits) if item.stable_id == split_id
    )
    if split_index + 1 >= len(document.splits):
        raise ValueError("the final Split has no lower boundary to move")
    upper = document.splits[split_index]
    reference = next(
        item for item in upper.blocks if item.stable_id == reference_block_id
    )
    old_rows = len(reference.rows)
    new_rows = _nearest_representable_rows(
        document, split_id, reference_block_id, requested_rows
    )
    if new_rows == old_rows:
        return document, new_rows

    bpm = float(reference.bpm.value)
    beat_split = int(reference.beat_split.value)
    if not math.isfinite(bpm) or bpm <= 0.0 or beat_split <= 0:
        raise ValueError("reference Block has invalid BPM or Beat Split")
    delta_ms = (new_rows - old_rows) * 60_000.0 / (bpm * beat_split)

    resized = _resize_split_to_reference_rows(
        document, split_id, reference_block_id, new_rows
    )
    lower = resized.splits[split_index + 1]
    lower_blocks = tuple(
        replace(
            block,
            start_time=RawF32.from_value(float(block.start_time.value) + delta_ms),
            span=None,
        )
        for block in lower.blocks
    )
    lower = replace(lower, blocks=lower_blocks, span=None)
    splits = tuple(
        lower if index == split_index + 1 else item
        for index, item in enumerate(resized.splits)
    )
    return replace(resized, splits=splits), new_rows


def _snapshot_with_updated_rows(snapshot, document, block_id: int):
    """Patch only one Block's row sequence for immediate note-edit feedback."""

    document_block = None
    document_split_id = None
    for split in document.splits:
        for block in split.blocks:
            if block.stable_id == block_id:
                document_block = block
                document_split_id = split.stable_id
                break
        if document_block is not None:
            break
    if document_block is None:
        return snapshot

    changed = False
    splits = []
    for split in snapshot.splits:
        if split.stable_id != document_split_id:
            splits.append(split)
            continue
        blocks = []
        for block in split.blocks:
            if block.stable_id == block_id:
                blocks.append(replace(block, rows=document_block.rows))
                changed = True
            else:
                blocks.append(block)
        splits.append(replace(split, blocks=tuple(blocks)))
    return replace(snapshot, splits=tuple(splits)) if changed else snapshot


def _restore_active_blocks(snapshot, previous):
    for split_id, block_id in previous.active_blocks:
        try:
            snapshot = snapshot.with_active_block(split_id, block_id)
        except KeyError:
            pass
    return snapshot


def _install_fast_note_feedback(window) -> None:
    original_apply_document = window._apply_document
    original_click = getattr(window, "_phase10_click", None)
    original_hold = getattr(window, "_phase10_hold", None)
    if not callable(original_click) or not callable(original_hold):
        return

    pending: dict[object, int] = {}
    timer = QTimer(window)
    timer.setSingleShot(True)
    timer.setInterval(_IDLE_REFRESH_MS)
    window.phase11_feedback_refresh_timer = timer
    window._phase11_fast_note_block_id = None

    def full_idle_refresh() -> None:
        if window.workspace is None:
            pending.clear()
            return
        for widget, document_index in tuple(pending.items()):
            if window.widget_documents.get(widget) != document_index:
                continue
            current = window.sessions[document_index].current
            previous = widget.snapshot
            snapshot = _restore_active_blocks(
                create_authoring_snapshot(current), previous
            )
            widget.set_snapshot(snapshot)
            if widget is window.tabs.currentWidget():
                window._set_metronome_snapshot(snapshot)
        pending.clear()
        window._populate_diagnostics()
        window._populate_routes()
        window._refresh_edit_actions()

    timer.timeout.connect(full_idle_refresh)

    def apply_document_fast(
        document_index,
        widget,
        document,
        *,
        tree_selection=None,
    ) -> None:
        block_id = window._phase11_fast_note_block_id
        if block_id is None or tree_selection is not None:
            pending.pop(widget, None)
            if not pending:
                timer.stop()
            original_apply_document(
                document_index,
                widget,
                document,
                tree_selection=tree_selection,
            )
            return

        entry = window.workspace.documents[document_index].with_document(document)
        window.workspace = window.workspace.replace_document(entry)
        widget.set_snapshot(
            _snapshot_with_updated_rows(widget.snapshot, document, block_id)
        )
        title = entry.path.name + (" *" if entry.is_modified else "")
        window.tabs.setTabText(window.tabs.indexOf(widget), title)
        pending[widget] = document_index
        timer.start()

    window._apply_document = apply_document_fast

    def click_fast(widget, hit):
        window._phase11_fast_note_block_id = hit[0].block.stable_id
        try:
            return original_click(widget, hit)
        finally:
            window._phase11_fast_note_block_id = None

    def hold_fast(widget, start, end):
        window._phase11_fast_note_block_id = start[0].block.stable_id
        try:
            return original_hold(widget, start, end)
        finally:
            window._phase11_fast_note_block_id = None

    window._phase10_click = click_fast
    window._phase10_hold = hold_fast

    def finish_fast(document_index, widget) -> None:
        window.sessions[document_index].finish_coalescing()
        window.gesture_keys.pop(widget, None)
        if widget in pending:
            timer.start()
        else:
            window._refresh_edit_actions()

    window._finish_note_gesture = finish_fast


def _install_division_metadata_action(window) -> None:
    original_inspect_ids = window._inspect_ids

    def inspect_ids(document_index: int, split_id: int, block_id: int) -> None:
        window.phase11_active_block_context = (
            document_index,
            split_id,
            block_id,
        )
        original_inspect_ids(document_index, split_id, block_id)

    window._inspect_ids = inspect_ids

    action = window.metadata_menu.addAction("Edit Division metadata…")
    action.setToolTip(
        "Edit the Division metadata owned by the active Block. The grid's last "
        "inspected Block is used even when the workspace tree is still on a Split."
    )
    window.phase11_division_metadata_action = action

    def edit_division_metadata() -> None:
        context = window._metadata_context()
        if context is not None and context[1].value == "division":
            window._edit_metadata()
            return
        active = getattr(window, "phase11_active_block_context", None)
        if active is None:
            QMessageBox.information(
                window,
                "Choose a Block",
                "Click inside a Block in the chart, then open Division metadata again.",
            )
            return
        document_index, split_id, block_id = active
        window._populate_tree(("block", document_index, split_id, block_id))
        window._inspect("block", document_index, split_id, block_id)
        window._edit_metadata()

    action.triggered.connect(edit_division_metadata)


def _install_toolbar_rows(window) -> None:
    for toolbar in window.findChildren(QToolBar):
        if toolbar.windowTitle() == "Audio transport":
            window.insertToolBarBreak(toolbar)
            return


def _boundary_hit(widget, event):
    if widget.snapshot.effective_lightmap:
        return None
    content_x = event.position().x() + widget.horizontalScrollBar().value()
    content_y = event.position().y() + widget.verticalScrollBar().value()
    # Restrict the resize affordance to the actual note grid. The right-side
    # timing gutter retains its existing click/double-click/context behavior.
    grid_width = widget.snapshot.columns * widget._layout.lane_width
    if content_x < 0 or content_x > grid_width:
        return None
    for segment in widget._layout.segments[:-1]:
        if abs(content_y - segment.bottom) <= _BOUNDARY_TOLERANCE_PX:
            return segment, content_y
    return None


def _install_split_boundary_drag(window) -> None:
    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_phase11_split_boundary_drag", False):
        return
    timeline_class._phase11_split_boundary_drag = True

    original_press = timeline_class.mousePressEvent
    original_move = timeline_class.mouseMoveEvent
    original_release = timeline_class.mouseReleaseEvent
    original_paint = timeline_class.paintEvent

    def mouse_press(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            hit = _boundary_hit(self, event)
            if hit is not None:
                segment, content_y = hit
                host = self.window()
                document_index = host.widget_documents.get(self)
                if document_index is not None:
                    document = host.sessions[document_index].current
                    try:
                        minimum = _minimum_reference_rows(
                            document,
                            segment.split_id,
                            segment.block.stable_id,
                        )
                    except (StopIteration, ValueError):
                        minimum = 1
                    self._phase11_boundary_drag = {
                        "split_id": segment.split_id,
                        "block_id": segment.block.stable_id,
                        "start_content_y": content_y,
                        "boundary_y": segment.bottom,
                        "row_height": segment.row_height,
                        "original_rows": segment.block.row_count,
                        "target_rows": segment.block.row_count,
                        "minimum_rows": minimum,
                    }
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                    event.accept()
                    self.viewport().update()
                    return
        original_press(self, event)

    def mouse_move(self, event) -> None:
        drag = getattr(self, "_phase11_boundary_drag", None)
        if drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            content_y = event.position().y() + self.verticalScrollBar().value()
            row_height = max(0.0001, float(drag["row_height"]))
            delta_rows = round((content_y - drag["start_content_y"]) / row_height)
            requested = max(
                int(drag["minimum_rows"]),
                int(drag["original_rows"]) + delta_rows,
            )
            host = self.window()
            document_index = host.widget_documents.get(self)
            if document_index is not None:
                document = host.sessions[document_index].current
                try:
                    requested = _nearest_representable_rows(
                        document,
                        int(drag["split_id"]),
                        int(drag["block_id"]),
                        requested,
                    )
                except (StopIteration, ValueError):
                    pass
            drag["target_rows"] = requested
            self.viewport().update()
            event.accept()
            return

        hit = _boundary_hit(self, event)
        if hit is not None and not event.buttons():
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif not event.buttons():
            self.unsetCursor()
        original_move(self, event)

    def mouse_release(self, event) -> None:
        drag = getattr(self, "_phase11_boundary_drag", None)
        if event.button() == Qt.MouseButton.LeftButton and drag is not None:
            self._phase11_boundary_drag = None
            self.unsetCursor()
            target_rows = int(drag["target_rows"])
            if target_rows != int(drag["original_rows"]):
                host = self.window()
                handler = getattr(host, "_phase11_commit_split_boundary", None)
                if callable(handler):
                    handler(
                        self,
                        int(drag["split_id"]),
                        int(drag["block_id"]),
                        target_rows,
                    )
            self.viewport().update()
            event.accept()
            return
        original_release(self, event)

    def paint_event(self, event) -> None:
        original_paint(self, event)
        drag = getattr(self, "_phase11_boundary_drag", None)
        if drag is None:
            return
        delta_rows = int(drag["target_rows"]) - int(drag["original_rows"])
        y = (
            float(drag["boundary_y"])
            + delta_rows * float(drag["row_height"])
            - self.verticalScrollBar().value()
        )
        painter = QPainter(self.viewport())
        try:
            pen = QPen(QColor("#8fc8ff"), 2.0, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(0, round(y), self.viewport().width(), round(y))
        finally:
            painter.end()

    timeline_class.mousePressEvent = mouse_press
    timeline_class.mouseMoveEvent = mouse_move
    timeline_class.mouseReleaseEvent = mouse_release
    timeline_class.paintEvent = paint_event

    def commit_boundary(widget, split_id: int, block_id: int, rows: int) -> None:
        document_index = window.widget_documents.get(widget)
        if document_index is None:
            return
        document = window.sessions[document_index].current
        try:
            result, actual_rows = _resize_split_boundary_document(
                document, split_id, block_id, rows
            )
            if result is document:
                return
            updated = window.sessions[document_index].execute(_ReplaceDocument(result))
        except (StopIteration, ValueError) as exc:
            QMessageBox.critical(window, "Cannot move Split boundary", str(exc))
            return
        window._apply_document(
            document_index,
            widget,
            updated,
            tree_selection=("block", document_index, split_id, block_id),
        )
        window.statusBar().showMessage(
            f"Moved Split boundary to row {actual_rows}; lower Start Time recalculated",
            5000,
        )

    window._phase11_commit_split_boundary = commit_boundary


def install_phase11_feedback(window) -> None:
    if getattr(window, "_phase11_feedback_installed", False):
        return
    window._phase11_feedback_installed = True

    _install_toolbar_rows(window)
    _install_fast_note_feedback(window)
    _install_division_metadata_action(window)
    _install_split_boundary_drag(window)
