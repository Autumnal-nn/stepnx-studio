from __future__ import annotations

from dataclasses import replace

from PySide6.QtGui import QPainter, QPicture


_WAVEFORM_CACHE_LIMIT = 24


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


def _waveform_picture_key(widget, visible, waveform) -> tuple:
    segment = visible.segment
    block = segment.block
    alignment = getattr(widget, "_audio_alignment", None)
    offset = 0.0 if alignment is None else float(alignment.offset_ms)
    channels = len(getattr(waveform, "channels", ()))
    return (
        int(block.stable_id),
        int(visible.first_row),
        int(visible.last_row),
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
    """Record expensive Python waveform projection once per visible slice."""

    import stepnx.gui.phase11_waveform as waveform_module

    if getattr(waveform_module, "_phase11_picture_cache_installed", False):
        return

    original_draw = waveform_module._draw_waveform_field

    def draw_waveform_cached(widget, painter, visible, waveform) -> None:
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
                original_draw(widget, recorder, visible, waveform)
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


def install_phase11_render_performance(window) -> None:
    if getattr(window, "_phase11_render_performance_installed", False):
        return
    window._phase11_render_performance_installed = True

    _install_waveform_picture_cache()
    _install_fast_note_snapshot_patch()
