from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QCheckBox, QMessageBox, QToolBar

from stepnx.authoring import BlockTimingValues, ShiftBlockStartTimes
from stepnx.core.errors import ModelInvariantError


_TIMING_FIELDS = {
    "BPM": ("bpm", "float"),
    "Start Time (ms)": ("start_time_ms", "float"),
    "Scroll": ("scroll_factor", "float"),
    "Offset / Delay": ("offset_or_delay_ms", "float"),
    "Speed / Freeze": ("speed_or_freeze", "float"),
    "Beat split": ("beat_split", "int"),
    "Beat measure": ("beat_measure", "int"),
    "Smooth Speed": ("smooth_speed", "int"),
    "Raw Flag": ("raw_flag", "int"),
}


def _parse_timing_value(label: str, text: str):
    field = _TIMING_FIELDS.get(label)
    if field is None:
        raise ValueError(f"{label} is not an editable Block timing field")
    _attribute, kind = field
    value = text.strip()
    if kind == "int":
        return int(value, 0)
    return float(value)


def _find_edit_menu(window):
    for action in window.menuBar().actions():
        if action.text().replace("&", "").casefold() == "edit":
            return action.menu()
    return None


def _insert_global_start_toggle(window) -> QCheckBox:
    checkbox = QCheckBox("All splits", window)
    checkbox.setChecked(False)
    checkbox.setToolTip(
        "When enabled, changing Start Time shifts every Block by the same delta, "
        "preserving the relative timing between Splits and branches."
    )

    for toolbar in window.findChildren(QToolBar):
        actions = toolbar.actions()
        for index, action in enumerate(actions):
            if toolbar.widgetForAction(action) is not window.chart_start_time:
                continue
            if index + 1 < len(actions):
                toolbar.insertWidget(actions[index + 1], checkbox)
            else:
                toolbar.addWidget(checkbox)
            return checkbox
    return checkbox


def _configure_inspector(window) -> None:
    context = getattr(window, "_phase11_inspector_context", None)
    editable = bool(
        getattr(window, "phase11_inspector_edit_action", None)
        and window.phase11_inspector_edit_action.isChecked()
        and context is not None
        and context[0] == "block"
    )

    for row in range(window.inspector.rowCount()):
        label_item = window.inspector.item(row, 0)
        label = "" if label_item is None else label_item.text()
        for column in range(window.inspector.columnCount()):
            item = window.inspector.item(row, column)
            if item is None:
                continue
            flags = item.flags() & ~Qt.ItemFlag.ItemIsEditable
            if editable and column == 2 and label in _TIMING_FIELDS:
                flags |= Qt.ItemFlag.ItemIsEditable
                item.setToolTip("Double-click to edit this Block timing value.")
            else:
                item.setToolTip("")
            item.setFlags(flags)


def _refresh_inspector(window) -> None:
    context = getattr(window, "_phase11_inspector_context", None)
    if context is not None:
        window._inspect(*context)


def _install_inspector_editing(window) -> None:
    edit_menu = _find_edit_menu(window)
    if edit_menu is None:
        return

    edit_menu.addSeparator()
    action = edit_menu.addAction("Editable Inspector timing values")
    action.setCheckable(True)
    action.setChecked(False)
    action.setToolTip(
        "Allow direct editing of the Value column for typed Block timing fields. "
        "Raw storage, metadata, and derived rows remain read-only."
    )
    window.phase11_inspector_edit_action = action

    original_inspect = window._inspect

    def inspect_with_editing(kind, document_index, split_id, block_id) -> None:
        window._phase11_inspector_populating = True
        try:
            original_inspect(kind, document_index, split_id, block_id)
            window._phase11_inspector_context = (
                kind,
                document_index,
                split_id,
                block_id,
            )
            _configure_inspector(window)
        finally:
            window._phase11_inspector_populating = False

    window._inspect = inspect_with_editing

    def toggle_editable(_checked: bool) -> None:
        _refresh_inspector(window)

    action.toggled.connect(toggle_editable)

    def inspector_item_changed(item) -> None:
        if getattr(window, "_phase11_inspector_populating", False):
            return
        context = getattr(window, "_phase11_inspector_context", None)
        if (
            context is None
            or context[0] != "block"
            or not action.isChecked()
            or item.column() != 2
        ):
            return

        row = item.row()
        label_item = window.inspector.item(row, 0)
        label = "" if label_item is None else label_item.text()
        field = _TIMING_FIELDS.get(label)
        if field is None:
            return

        kind, document_index, split_id, block_id = context
        try:
            parsed = _parse_timing_value(label, item.text())
            document = window.sessions[document_index].current
            split = next(
                candidate
                for candidate in document.splits
                if candidate.stable_id == split_id
            )
            block = next(
                candidate
                for candidate in split.blocks
                if candidate.stable_id == block_id
            )
            attribute, _kind = field
            values = replace(
                BlockTimingValues.from_block(block),
                **{attribute: parsed},
            )
            command = values.command(block.stable_id)
        except (StopIteration, ValueError, ModelInvariantError) as exc:
            QMessageBox.critical(window, "Invalid Block timing", str(exc))
            _refresh_inspector(window)
            return

        window._execute_structure(
            document_index,
            command,
            (kind, document_index, split_id, block_id),
            f"Updated {label} from Inspector",
        )
        active = window.tabs.currentWidget()
        if active is not None and hasattr(active, "snapshot"):
            window._refresh_chart_start_time(active)
        _refresh_inspector(window)

    window.inspector.itemChanged.connect(inspector_item_changed)


def _install_global_start_time(window) -> None:
    checkbox = _insert_global_start_toggle(window)
    window.phase11_all_start_times = checkbox
    original_changed = window._chart_start_time_changed

    try:
        window.chart_start_time.valueChanged.disconnect()
    except (RuntimeError, TypeError):
        pass

    def start_time_changed(value: float) -> None:
        if not checkbox.isChecked():
            original_changed(value)
            _refresh_inspector(window)
            return

        document_index = window._current_document_index()
        widget = window.tabs.currentWidget()
        if document_index is None or widget is None or not hasattr(widget, "snapshot"):
            return
        document = window.sessions[document_index].current
        first_block = next(
            (block for split in document.splits for block in split.blocks), None
        )
        if first_block is None:
            return
        delta = value - float(first_block.start_time.value)
        if abs(delta) < 0.0001:
            return

        try:
            updated = window.sessions[document_index].execute(
                ShiftBlockStartTimes(delta)
            )
        except (ValueError, ModelInvariantError) as exc:
            QMessageBox.critical(window, "Invalid Start Time", str(exc))
            window._refresh_chart_start_time(widget)
            return

        window._apply_document(document_index, widget, updated)
        window._refresh_chart_start_time(widget)
        _refresh_inspector(window)
        window.statusBar().showMessage(
            f"Shifted every Block Start Time by {delta:g} ms",
            5000,
        )

    window.chart_start_time.valueChanged.connect(start_time_changed)


def _install_hold_head_underlay() -> None:
    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_phase11_hold_head_underlay", False):
        return
    original_draw = timeline_class._draw_noteskin_note

    def draw_noteskin_with_head_body(self, painter, lane, y, row_height, raw, rect):
        if (raw[0] & 0x0F) == 0x7 and row_height > 0.0:
            pack = getattr(self, "_noteskin_pack", None)
            if pack is not None:
                bank = pack.bank(raw[2])
                if bank is not None and bank.animation:
                    atlas = bank.animation[0]
                    pixmap = self._pixmap(atlas.path)
                    if pixmap is not None:
                        atlas_lane = (self._snapshot.start_column + lane) % 5
                        tile_x, tile_y, tile_width, tile_height = atlas.tile(
                            atlas_lane, 0
                        )
                        # Use the exact same repeat strip as a body cell, but
                        # start it at the head's timing line. The terminal is
                        # drawn afterwards and therefore masks the overlap.
                        body_source = QRectF(
                            tile_x,
                            tile_y,
                            tile_width,
                            min(8, tile_height),
                        )
                        body_target = QRectF(
                            rect.x(),
                            y,
                            rect.width(),
                            max(1.0, row_height),
                        )
                        painter.drawPixmap(body_target, pixmap, body_source)
        return original_draw(self, painter, lane, y, row_height, raw, rect)

    timeline_class._draw_noteskin_note = draw_noteskin_with_head_body
    timeline_class._phase11_hold_head_underlay = True


def install_phase11_authoring_polish(window) -> None:
    if getattr(window, "_phase11_authoring_polish_installed", False):
        return
    window._phase11_authoring_polish_installed = True

    _install_global_start_time(window)
    _install_inspector_editing(window)
    _install_hold_head_underlay()
