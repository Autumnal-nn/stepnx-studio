from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QKeySequence, QPen

from stepnx.authoring.audio import AudioAlignment
from stepnx.authoring.selection import CellSelection


def _menu_by_name(window, name: str):
    wanted = name.casefold()
    for action in window.menuBar().actions():
        if action.text().replace("&", "").casefold() == wanted:
            return action.menu()
    return None


def _action_by_name(menu, name: str):
    if menu is None:
        return None
    wanted = name.casefold()
    for action in menu.actions():
        if action.text().replace("&", "").replace("…", "").strip().casefold() == wanted:
            return action
    return None


def _selection_rect(geometry, lane: int, row_y: float, row_height: float) -> QRectF:
    """Selection target centered on the same timing line as note artwork."""

    rect = QRectF(*geometry.note_rect(lane, row_y, row_height))
    return rect.adjusted(-1.0, -1.0, 1.0, 1.0)


def _timing_line_row_hit(layout, content_y: float):
    """Resolve a click to the nearest encoded-row timing line.

    Notes and selections are centered on timing lines in Phase 11. The legacy
    ``row_at_y`` method instead treats each line as the top edge of its cell,
    which makes the upper half of visible note artwork select the previous row.
    This helper partitions vertical space at the midpoint between timing lines.
    """

    segment = layout.segment_at_y(content_y)
    if segment is None or segment.row_height <= 0.0 or segment.block.row_count <= 0:
        return None

    relative = (content_y - segment.rows_top) / segment.row_height
    row_index = math.floor(relative + 0.5)
    if row_index < 0:
        row_index = 0
    if row_index < segment.block.row_count:
        return segment, row_index

    # The lower half of a segment's final encoded interval is closer to the
    # first timing line of the following Split. This also lets the upper half of
    # that first note remain clickable even though its artwork protrudes above
    # the Split boundary.
    try:
        segment_index = layout.segments.index(segment)
    except ValueError:
        segment_index = -1
    if 0 <= segment_index + 1 < len(layout.segments):
        following = layout.segments[segment_index + 1]
        if following.block.row_count > 0:
            return following, 0

    # There is no future timing line after the final encoded row, so keep the
    # bottom half of its visible target assigned to that last row.
    return segment, segment.block.row_count - 1


def _timing_line_cell_hit(layout, content_x: float, content_y: float):
    row_hit = _timing_line_row_hit(layout, content_y)
    if row_hit is None or content_x < layout.geometry.ruler_width:
        return None
    lane = int(
        (content_x - layout.geometry.ruler_width) // layout.geometry.lane_width
    )
    if not 0 <= lane < layout.snapshot.columns:
        return None
    return row_hit[0], row_hit[1], lane


def _install_timing_line_hit_testing() -> None:
    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_phase11_timing_line_hit_testing", False):
        return
    if not hasattr(timeline_class, "_phase10_hit"):
        return

    def phase10_hit(self, event):
        content_x = event.position().x() + self.horizontalScrollBar().value()
        content_y = event.position().y() + self.verticalScrollBar().value()
        return self._snapped_hit(
            _timing_line_cell_hit(self._layout, content_x, content_y)
        )

    def phase10_row_hit(self, event):
        content_y = event.position().y() + self.verticalScrollBar().value()
        hit = _timing_line_row_hit(self._layout, content_y)
        if hit is None:
            return None
        segment, row_index = hit
        row_index = self._layout.snap_row_index(
            segment, row_index, self._snap_beats
        )
        return segment, row_index

    timeline_class._phase10_hit = phase10_hit
    timeline_class._phase10_row_hit = phase10_row_hit
    timeline_class._phase11_timing_line_hit_testing = True


def _install_timing_line_selection() -> None:
    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_phase11_timing_line_selection", False):
        return

    original_draw_segment = timeline_class._draw_segment

    def draw_segment_with_centered_selection(self, painter, visible) -> None:
        selection = self._selection
        if not selection.targets:
            original_draw_segment(self, painter, visible)
            return

        # Suppress the legacy row-cell rectangle while the normal segment is
        # painted, then draw the selection against the same note_rect geometry
        # used by timing-line-centered arrows. Empty cells still get the same
        # visible target, so selection remains meaningful without note artwork.
        self._selection = CellSelection()
        try:
            original_draw_segment(self, painter, visible)
        finally:
            self._selection = selection

        segment = visible.segment
        geometry = self._geometry
        lanes_by_row: dict[int, list[int]] = {}
        for target in selection.targets:
            lanes_by_row.setdefault(int(target.row_id), []).append(int(target.lane))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#f4d35e"), 2.0))
        for row_index in range(visible.first_row, visible.last_row):
            row = segment.block.rows[row_index]
            lanes = lanes_by_row.get(int(row.stable_id))
            if not lanes:
                continue
            y = segment.y_for_row(row_index)
            for lane in sorted(lanes):
                painter.drawRect(_selection_rect(geometry, lane, y, segment.row_height))

    timeline_class._draw_segment = draw_segment_with_centered_selection
    timeline_class._phase11_timing_line_selection = True


def _move_waveform_to_audio(window) -> None:
    action = getattr(window, "phase11_waveform_action", None)
    if action is None:
        return

    audio_menu = _menu_by_name(window, "audio")
    if audio_menu is None:
        return
    view_menu = _menu_by_name(window, "view")
    if view_menu is not None:
        view_menu.removeAction(action)

    action.setText("Show Waveform")
    first_separator = next(
        (candidate for candidate in audio_menu.actions() if candidate.isSeparator()),
        None,
    )
    if first_separator is None:
        audio_menu.addAction(action)
    else:
        audio_menu.insertAction(first_separator, action)

    # Phase 11 created View solely for this toggle. Remove the now-empty shell,
    # but leave a future/non-empty View menu alone.
    if view_menu is not None and not any(
        not candidate.isSeparator() for candidate in view_menu.actions()
    ):
        window.menuBar().removeAction(view_menu.menuAction())
        view_menu.deleteLater()


def _close_folder(window) -> None:
    if window.workspace is None:
        return
    confirm = getattr(window, "_confirm_discard", None)
    if callable(confirm) and not confirm():
        return

    decoder = getattr(window, "phase11_waveform_decoder", None)
    if decoder is not None:
        decoder.stop()
    window.audio_transport.load(None)

    window.workspace = None
    window.sessions.clear()
    window.baselines.clear()
    window.widget_documents.clear()
    window.preview_snapshots.clear()
    window.gesture_keys.clear()
    window.waveform = None
    window.audio_alignment = AudioAlignment()
    window.metronome_clock = None
    window.note_metronome_clock = None
    window.last_metronome_beat = None
    window.audio_playing = False

    while window.tabs.count():
        window.tabs.removeTab(window.tabs.count() - 1)
    window.tree.clear()
    window.diagnostics.clear()
    window.inspector.clearContents()
    window.inspector.setRowCount(0)
    window.routes.clear()
    window.audio_position.setRange(0, 0)
    window.audio_position.setValue(0)
    window.audio_play.setText("Play")

    for refresh_name in ("_refresh_edit_actions", "_refresh_structure_actions"):
        refresh = getattr(window, refresh_name, None)
        if callable(refresh):
            refresh()
    window.statusBar().showMessage("Closed folder", 3000)


def _install_shortcuts(window) -> None:
    file_menu = _menu_by_name(window, "file")
    audio_menu = _menu_by_name(window, "audio")

    open_action = _action_by_name(file_menu, "open folder")
    if open_action is not None:
        open_action.setShortcut(QKeySequence("Ctrl+O"))

    close_action = _action_by_name(file_menu, "close folder")
    if close_action is None and file_menu is not None:
        close_action = QAction("Close folder", window)
        close_action.triggered.connect(lambda *_: _close_folder(window))
        actions = file_menu.actions()
        if open_action is not None and open_action in actions:
            index = actions.index(open_action)
            before = actions[index + 1] if index + 1 < len(actions) else None
            file_menu.insertAction(before, close_action)
        else:
            file_menu.addAction(close_action)
    if close_action is not None:
        close_action.setShortcut(QKeySequence("Ctrl+W"))
        window.phase11_close_folder_action = close_action

    select_audio = _action_by_name(audio_menu, "select audio")
    if select_audio is not None:
        select_audio.setShortcut(QKeySequence("Ctrl+3"))


def install_phase11_ui_polish(window) -> None:
    if getattr(window, "_phase11_ui_polish_installed", False):
        return
    window._phase11_ui_polish_installed = True

    _install_timing_line_hit_testing()
    _install_timing_line_selection()
    _move_waveform_to_audio(window)
    _install_shortcuts(window)
