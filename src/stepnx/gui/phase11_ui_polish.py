from __future__ import annotations

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

    _install_timing_line_selection()
    _move_waveform_to_audio(window)
    _install_shortcuts(window)
