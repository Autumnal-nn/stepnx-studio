from __future__ import annotations

from PySide6.QtGui import QActionGroup

from stepnx.authoring.timeline import TimelineGeometry, TimelineLayout

EDITOR_ZOOM_PRESETS = (100, 125, 150, 175, 200, 225, 250, 275, 300)


def _validate_percent(percent: int) -> int:
    percent = int(percent)
    if percent not in EDITOR_ZOOM_PRESETS:
        raise ValueError(
            f"editor zoom must be one of {', '.join(map(str, EDITOR_ZOOM_PRESETS))}%"
        )
    return percent


def scale_editor_geometry(
    geometry: TimelineGeometry,
    old_percent: int,
    new_percent: int,
) -> TimelineGeometry:
    """Scale only Timeline/editor-field geometry between discrete presets.

    The surrounding Qt application chrome is deliberately untouched. Existing
    Ctrl+wheel vertical magnification remains independent because this function
    scales the current row height and its min/max bounds by the same ratio.
    """

    old_percent = _validate_percent(old_percent)
    new_percent = _validate_percent(new_percent)
    factor = new_percent / old_percent
    return TimelineGeometry(
        row_height=geometry.row_height * factor,
        block_header_height=geometry.block_header_height * factor,
        lane_width=geometry.lane_width * factor,
        ruler_width=geometry.ruler_width * factor,
        block_info_width=geometry.block_info_width * factor,
        footer_height=geometry.footer_height * factor,
        minimum_row_height=geometry.minimum_row_height * factor,
        maximum_row_height=geometry.maximum_row_height * factor,
    )


def set_timeline_editor_zoom(widget, percent: int) -> None:
    percent = _validate_percent(percent)
    old_percent = int(getattr(widget, "_stepnx_editor_zoom_percent", 100))
    if old_percent == percent:
        widget._stepnx_editor_zoom_percent = percent
        return

    ratio = percent / old_percent
    viewport = widget.viewport()
    anchor_x = viewport.width() / 2.0
    anchor_y = viewport.height() / 2.0
    old_x = widget.horizontalScrollBar().value()
    old_y = widget.verticalScrollBar().value()

    widget._geometry = scale_editor_geometry(widget._geometry, old_percent, percent)
    widget._layout = TimelineLayout(
        widget._snapshot,
        widget._geometry,
        playback=widget._playback_active,
    )
    widget._collapsed_hold_cells_cache = None
    widget._playback_y = (
        None
        if widget._playback_time_ms is None
        else widget._layout.y_for_chart_time(widget._playback_time_ms)
    )
    widget._stepnx_editor_zoom_percent = percent
    widget._sync_scrollbars()
    widget.horizontalScrollBar().setValue(round((old_x + anchor_x) * ratio - anchor_x))
    widget.verticalScrollBar().setValue(round((old_y + anchor_y) * ratio - anchor_y))
    viewport.update()


def _view_menu(window):
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu is not None and action.text().replace("&", "").strip().lower() == "view":
            return menu
    return window.menuBar().addMenu("&View")


def _timeline_widgets(window):
    import stepnx.gui.timeline_widget as timeline_module

    for index in range(window.tabs.count()):
        widget = window.tabs.widget(index)
        if isinstance(widget, timeline_module.TimelineWidget):
            yield widget


def install_editor_field_zoom(window) -> None:
    if getattr(window, "_stepnx_editor_field_zoom_installed", False):
        return
    window._stepnx_editor_field_zoom_installed = True
    window._stepnx_editor_zoom_percent = 100

    view_menu = _view_menu(window)
    zoom_menu = view_menu.addMenu("Editor zoom")
    group = QActionGroup(window)
    group.setExclusive(True)
    actions = {}

    def apply_zoom(percent: int) -> None:
        percent = _validate_percent(percent)
        window._stepnx_editor_zoom_percent = percent
        for widget in _timeline_widgets(window):
            set_timeline_editor_zoom(widget, percent)
        window.statusBar().showMessage(f"Editor zoom: {percent}%", 2500)

    for percent in EDITOR_ZOOM_PRESETS:
        action = zoom_menu.addAction(f"{percent}%")
        action.setCheckable(True)
        action.setChecked(percent == 100)
        action.triggered.connect(
            lambda checked=False, value=percent: checked and apply_zoom(value)
        )
        group.addAction(action)
        actions[percent] = action

    def sync_current_tab(_index: int) -> None:
        widget = window.tabs.currentWidget()
        if widget is None:
            return
        import stepnx.gui.timeline_widget as timeline_module

        if isinstance(widget, timeline_module.TimelineWidget):
            set_timeline_editor_zoom(widget, window._stepnx_editor_zoom_percent)

    window.tabs.currentChanged.connect(sync_current_tab)
    window.editor_zoom_menu = zoom_menu
    window.editor_zoom_actions = actions
    window.set_editor_zoom = apply_zoom
