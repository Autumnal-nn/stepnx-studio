from __future__ import annotations

import math
from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QPicture

from stepnx.authoring.timeline import VisibleSegment
from stepnx.core.model import CompactRows, OverlayRows


_WAVEFORM_CACHE_LIMIT = 24
_PLAYBACK_TILE_CACHE_LIMIT = 64
_PLAYBACK_TILE_TARGET_PX = 256.0
_PLAYBACK_TILE_MAX_ROWS = 4096
_WAVEFORM_GAIN = 0.85


def _block_layout_signature(block) -> tuple:
    """Fields that can change TimelineSegment geometry or timing projection."""

    return (
        int(block.stable_id),
        int(block.index),
        int(block.row_count),
        float(block.bpm),
        int(block.beat_split),
        int(block.beat_measure),
        float(block.scroll),
        float(block.start_time),
    )


def _snapshot_block(snapshot, block_id: int):
    for split in snapshot.splits:
        for block in split.blocks:
            if int(block.stable_id) == int(block_id):
                return split.stable_id, block
    return None, None


def _source_backed_row_ids(rows):
    """Return row IDs without materializing a compact Block's row objects."""

    base = rows.base if isinstance(rows, OverlayRows) else rows
    if isinstance(base, CompactRows):
        return base._row_ids
    return tuple(row.stable_id for row in rows)


def _install_fast_selection_row_ids() -> None:
    """Keep Shift-drag rectangle selection O(row-id lookup), not O(row decode)."""

    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_phase11_fast_selection_row_ids", False):
        return

    original_row_ids = timeline_class._row_ids

    def row_ids_fast(segment):
        return _source_backed_row_ids(segment.block.rows)

    # _row_ids is a static helper on TimelineWidget. Preserve that binding so
    # existing self._row_ids(segment) calls do not receive an extra self arg.
    timeline_class._row_ids = staticmethod(row_ids_fast)
    timeline_class._phase11_fast_selection_row_ids = True
    timeline_class._phase11_original_row_ids = original_row_ids


def _install_fast_note_snapshot_patch() -> None:
    """Avoid rebuilding TimelineLayout when an edit changes row bytes only."""

    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_phase11_fast_snapshot_patch", False):
        return

    original_set_snapshot = timeline_class.set_snapshot

    def set_snapshot_fast(self, snapshot) -> None:
        host = self.window()
        block_id = getattr(host, "_phase11_fast_note_block_id", None)
        if block_id is None:
            original_set_snapshot(self, snapshot)
            return

        split_id, new_block = _snapshot_block(snapshot, int(block_id))
        old_segment = next(
            (
                segment
                for segment in self._layout.segments
                if int(segment.block.stable_id) == int(block_id)
            ),
            None,
        )
        if (
            new_block is None
            or old_segment is None
            or _block_layout_signature(new_block)
            != _block_layout_signature(old_segment.block)
            or int(snapshot.columns) != int(self._snapshot.columns)
            or int(snapshot.start_column) != int(self._snapshot.start_column)
            or bool(snapshot.effective_lightmap)
            != bool(self._snapshot.effective_lightmap)
        ):
            original_set_snapshot(self, snapshot)
            return

        # Rows changed, but every layout-affecting field is identical. Keep the
        # already-built segment geometry, scroll ranges, and waveform cache.
        # Only replace the BlockSnapshot held by the active segment.
        self._snapshot = snapshot
        self._layout.snapshot = snapshot
        self._layout.segments = tuple(
            replace(segment, block=new_block)
            if int(segment.block.stable_id) == int(block_id)
            else segment
            for segment in self._layout.segments
        )
        self.viewport().update()
        self.snapshotChanged.emit(snapshot)

    timeline_class.set_snapshot = set_snapshot_fast
    timeline_class._phase11_fast_snapshot_patch = True
    timeline_class._phase11_original_set_snapshot = original_set_snapshot


def _waveform_viewport_bounds(widget, visible) -> tuple[float, float] | None:
    """Return the actual on-screen content-y interval for one visible segment.

    VisibleSegment is row-granular. At extreme zoom one encoded row can be
    thousands of pixels tall, so using its full row bounds makes the waveform
    renderer generate thousands of off-screen line primitives. Clamp again at
    the real viewport after layout culling.
    """

    segment = visible.segment
    viewport_top = float(widget.verticalScrollBar().value())
    viewport_bottom = viewport_top + float(widget.viewport().height())
    first_y = max(
        segment.rows_top,
        segment.y_for_row(visible.first_row),
        viewport_top,
    )
    last_y = min(
        segment.bottom,
        segment.y_for_row(visible.last_row),
        viewport_bottom,
    )
    if last_y <= first_y:
        return None
    return first_y, last_y


def _draw_waveform_viewport(widget, painter, visible, waveform) -> None:
    """Draw waveform detail only for pixels that can reach the viewport."""

    segment = visible.segment
    block = segment.block
    if (
        segment.row_height <= 0.0
        or block.bpm <= 0.0
        or block.beat_split <= 0
        or waveform.duration_ms <= 0.0
    ):
        return

    bounds = _waveform_viewport_bounds(widget, visible)
    if bounds is None:
        return
    first_y, last_y = bounds

    geometry = widget._geometry
    field_width = widget._layout.lane_area_width
    if field_width <= 0.0:
        return
    field_left = geometry.ruler_width
    row_duration = 60_000.0 / (block.bpm * block.beat_split)
    channel_series = getattr(waveform, "channels", ())

    if len(channel_series) >= 2:
        channel_count = 2
        slot_width = field_width / channel_count
        centres = tuple(
            field_left + slot_width * (index + 0.5)
            for index in range(channel_count)
        )
        maximum_half = max(4.0, slot_width * 0.20)
    else:
        channel_count = 1
        centres = (field_left + field_width / 2.0,)
        maximum_half = max(4.0, field_width * 0.16)

    painter.save()
    try:
        painter.setClipRect(
            QRectF(field_left, first_y, field_width, last_y - first_y)
        )
        painter.setPen(QPen(QColor(116, 124, 146, 112), 1.0))
        start = math.floor(first_y)
        stop = math.ceil(last_y)
        for y in range(start, stop):
            row_a = (y - segment.rows_top) / segment.row_height
            row_b = (y + 1.0 - segment.rows_top) / segment.row_height
            chart_time_a = block.start_time + row_a * row_duration
            chart_time_b = block.start_time + row_b * row_duration
            audio_time_a = widget._audio_alignment.chart_to_audio(chart_time_a)
            audio_time_b = widget._audio_alignment.chart_to_audio(chart_time_b)

            for channel in range(channel_count):
                if hasattr(waveform, "channel_range_at"):
                    low, high = waveform.channel_range_at(
                        channel, audio_time_a, audio_time_b
                    )
                    if low == 0.0 and high == 0.0:
                        continue
                    left = centres[channel] + low * _WAVEFORM_GAIN * maximum_half
                    right = centres[channel] + high * _WAVEFORM_GAIN * maximum_half
                else:
                    middle = (audio_time_a + audio_time_b) / 2.0
                    amplitude = waveform.amplitude_at(middle)
                    if amplitude <= 0.0:
                        continue
                    half = min(1.0, amplitude * _WAVEFORM_GAIN) * maximum_half
                    left = centres[channel] - half
                    right = centres[channel] + half
                painter.drawLine(
                    QPointF(left, y + 0.5), QPointF(right, y + 0.5)
                )
    finally:
        painter.restore()


def _waveform_picture_key(widget, visible, waveform) -> tuple:
    segment = visible.segment
    block = segment.block
    alignment = getattr(widget, "_audio_alignment", None)
    offset = 0.0 if alignment is None else float(alignment.offset_ms)
    channels = len(getattr(waveform, "channels", ()))
    bounds = _waveform_viewport_bounds(widget, visible)
    return (
        int(block.stable_id),
        int(visible.first_row),
        int(visible.last_row),
        None if bounds is None else round(bounds[0], 3),
        None if bounds is None else round(bounds[1], 3),
        float(segment.rows_top),
        float(segment.row_height),
        float(block.start_time),
        float(block.bpm),
        int(block.beat_split),
        float(widget._layout.lane_area_width),
        float(widget._geometry.ruler_width),
        offset,
        float(waveform.duration_ms),
        channels,
    )


def _install_waveform_picture_cache() -> None:
    """Cache paused waveform slices, but draw playback directly.

    During follow-playback first_row/last_row changes continually. Recording a
    fresh QPicture for a one-frame lifetime costs more than drawing the bounded
    waveform directly, then immediately evicts useful paused-editor entries.
    """

    import stepnx.gui.phase11_waveform as waveform_module

    if getattr(waveform_module, "_phase11_picture_cache_installed", False):
        return

    original_draw = waveform_module._draw_waveform_field

    def draw_waveform_cached(widget, painter, visible, waveform) -> None:
        if getattr(widget, "_playback_active", False):
            _draw_waveform_viewport(widget, painter, visible, waveform)
            return

        cached_source = getattr(widget, "_phase11_waveform_picture_source", None)
        if cached_source is not waveform:
            widget._phase11_waveform_picture_source = waveform
            widget._phase11_waveform_picture_cache = {}

        cache = getattr(widget, "_phase11_waveform_picture_cache", None)
        if cache is None:
            cache = {}
            widget._phase11_waveform_picture_cache = cache

        key = _waveform_picture_key(widget, visible, waveform)
        picture = cache.get(key)
        if picture is None:
            picture = QPicture()
            recorder = QPainter(picture)
            try:
                _draw_waveform_viewport(widget, recorder, visible, waveform)
            finally:
                recorder.end()
            cache[key] = picture
            while len(cache) > _WAVEFORM_CACHE_LIMIT:
                cache.pop(next(iter(cache)))

        # QPicture replays the already-projected vector commands in Qt/C++.
        # Ordinary note/selection repaints no longer execute the per-pixel
        # Python waveform range loop again.
        painter.drawPicture(0, 0, picture)

    waveform_module._draw_waveform_field = draw_waveform_cached
    waveform_module._phase11_picture_cache_installed = True
    waveform_module._phase11_original_draw_waveform_field = original_draw


def _playback_tile_ranges(visible) -> tuple[tuple[int, int], ...]:
    """Partition a sub-pixel playback slice into stable row-aligned cache tiles."""

    row_height = float(visible.segment.row_height)
    first = int(visible.first_row)
    last = int(visible.last_row)
    if row_height <= 0.0 or last <= first:
        return ()
    rows_per_tile = max(
        1,
        min(
            _PLAYBACK_TILE_MAX_ROWS,
            math.ceil(_PLAYBACK_TILE_TARGET_PX / row_height),
        ),
    )
    tile_first = (first // rows_per_tile) * rows_per_tile
    ranges = []
    while tile_first < last:
        tile_last = min(visible.segment.block.row_count, tile_first + rows_per_tile)
        if tile_last > first:
            ranges.append((max(0, tile_first), tile_last))
        tile_first += rows_per_tile
    return tuple(ranges)


def _playback_tile_key(widget, visible, first: int, last: int) -> tuple:
    segment = visible.segment
    block = segment.block
    return (
        id(widget._snapshot),
        int(block.stable_id),
        id(block.rows),
        first,
        last,
        float(segment.row_height),
        float(widget._geometry.lane_width),
        float(widget._geometry.ruler_width),
        float(widget._layout.chart_width),
        float(getattr(widget, "_snap_beats", 0.0)),
        id(getattr(widget, "_selection", None)),
        id(getattr(widget, "_visual_pack", None)),
        id(getattr(widget, "_noteskin_pack", None)),
    )


def _install_subpixel_playback_tile_cache() -> None:
    """Replay static note/grid tiles when many encoded rows share each pixel.

    At extreme zoom-out the gameplay layout can place tens of thousands of NX
    rows in one viewport. The chart drawing is static while transport scrolls,
    so record row-aligned tiles once and let Qt replay the vector commands. The
    waveform remains dynamic and is drawn separately with viewport clipping.
    """

    import stepnx.gui.phase11_waveform as waveform_module
    import stepnx.gui.timeline_widget as timeline_module

    timeline_class = timeline_module.TimelineWidget
    if getattr(timeline_class, "_phase11_subpixel_tile_cache", False):
        return

    current_draw = timeline_class._draw_segment
    base_draw = getattr(timeline_class, "_phase11_original_draw_segment", None)
    if base_draw is None:
        return

    def draw_segment_tiled(self, painter, visible) -> None:
        segment = visible.segment
        if not self._playback_active or segment.row_height >= 1.0:
            current_draw(self, painter, visible)
            return

        waveform = getattr(self, "_waveform", None)
        host = self.window()
        action = getattr(host, "phase11_waveform_action", None)
        enabled = action is None or action.isChecked()
        if waveform is not None and enabled:
            waveform_module._draw_waveform_field(self, painter, visible, waveform)

        cache = getattr(self, "_phase11_playback_tile_cache", None)
        if cache is None:
            cache = {}
            self._phase11_playback_tile_cache = cache

        for first, last in _playback_tile_ranges(visible):
            key = _playback_tile_key(self, visible, first, last)
            picture = cache.get(key)
            if picture is None:
                picture = QPicture()
                recorder = QPainter(picture)
                saved_waveform = self._waveform
                self._waveform = None
                try:
                    base_draw(self, recorder, VisibleSegment(segment, first, last))
                finally:
                    self._waveform = saved_waveform
                    recorder.end()
                cache[key] = picture
                while len(cache) > _PLAYBACK_TILE_CACHE_LIMIT:
                    cache.pop(next(iter(cache)))
            painter.drawPicture(0, 0, picture)

    timeline_class._draw_segment = draw_segment_tiled
    timeline_class._phase11_subpixel_tile_cache = True
    timeline_class._phase11_pre_tile_draw_segment = current_draw


def install_phase11_render_performance(window) -> None:
    if getattr(window, "_phase11_render_performance_installed", False):
        return
    window._phase11_render_performance_installed = True

    _install_waveform_picture_cache()
    _install_subpixel_playback_tile_cache()
    _install_fast_selection_row_ids()
    _install_fast_note_snapshot_patch()
