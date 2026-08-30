from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected fragment not found in {path}: {old[:180]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# The gameplay preview had already been reduced to ~2 ms paint and ~0.3 ms ADV,
# but the authoring TimelineWidget shares the same Qt GUI thread. During playback
# dense split-128 longs caused it to issue one pixmap draw for every explicit
# BODY row. Coalesce contiguous BODY rows into one visual shaft only while the
# timeline is in playback projection. Paused authoring stays row-lossless.
replace_once(
    "src/stepnx/gui/timeline_widget.py",
    "from math import ceil, isfinite\n",
    "from math import ceil, isfinite\nfrom time import perf_counter\n",
)
replace_once(
    "src/stepnx/gui/timeline_widget.py",
    "        self._playback_active = False\n        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)\n",
    "        self._playback_active = False\n        self._paint_cost_ms = 0.0\n        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)\n",
)
replace_once(
    "src/stepnx/gui/timeline_widget.py",
    '''        beat_markers = {marker.row_index: marker for marker in self._layout.beat_markers(visible)}\n        deferred_hold_heads: list[tuple[int, float, float, bytes]] = []\n        for row_index in range(visible.first_row, visible.last_row):\n''',
    '''        beat_markers = {marker.row_index: marker for marker in self._layout.beat_markers(visible)}\n        deferred_hold_heads: list[tuple[int, float, float, bytes]] = []\n        body_runs: dict[int, tuple[bytes, float, float]] = {}\n\n        def flush_body(lane: int) -> None:\n            run = body_runs.pop(lane, None)\n            if run is None:\n                return\n            raw, start_y, end_y = run\n            self._draw_hold_body_span(\n                painter, lane, start_y, max(1.0, end_y - start_y), raw\n            )\n\n        def flush_all_bodies() -> None:\n            for lane in tuple(body_runs):\n                flush_body(lane)\n\n        for row_index in range(visible.first_row, visible.last_row):\n''',
)
replace_once(
    "src/stepnx/gui/timeline_widget.py",
    '''            row = segment.block.rows[row_index]\n            selected_lanes = sorted(\n''',
    '''            row = segment.block.rows[row_index]\n            selected_lanes = sorted(\n''',
)
replace_once(
    "src/stepnx/gui/timeline_widget.py",
    '''            if isinstance(row, EmptyRow):\n                continue\n            if isinstance(row, LightmapRow):\n                self._draw_lightmap_row(\n                    painter, row.raw_channels, y, segment.row_height\n                )\n                continue\n            if isinstance(row, (NoteRow, PackedNoteRow)):\n                for lane in range(row.cell_count):\n                    cell = row.cell(lane) if isinstance(row, PackedNoteRow) else row.cells[lane]\n                    if cell.note_type:\n                        if cell.note_type == 0x7:\n                            deferred_hold_heads.append(\n                                (lane, y, segment.row_height, cell.raw)\n                            )\n                        else:\n                            self._draw_note(\n                                painter, lane, y, segment.row_height, cell.raw\n                            )\n\n        # Hold heads are the top terminal layer. This matters when BeatSplit is\n''',
    '''            if isinstance(row, EmptyRow):\n                if self._playback_active:\n                    flush_all_bodies()\n                continue\n            if isinstance(row, LightmapRow):\n                if self._playback_active:\n                    flush_all_bodies()\n                self._draw_lightmap_row(\n                    painter, row.raw_channels, y, segment.row_height\n                )\n                continue\n            if isinstance(row, (NoteRow, PackedNoteRow)):\n                for lane in range(row.cell_count):\n                    cell = row.cell(lane) if isinstance(row, PackedNoteRow) else row.cells[lane]\n                    if self._playback_active and cell.note_type == 0xB:\n                        run = body_runs.get(lane)\n                        end_y = y + segment.row_height\n                        if (\n                            run is not None\n                            and run[0] == cell.raw\n                            and abs(run[2] - y) <= 1e-6\n                        ):\n                            body_runs[lane] = (run[0], run[1], end_y)\n                        else:\n                            flush_body(lane)\n                            body_runs[lane] = (cell.raw, y, end_y)\n                        continue\n                    if self._playback_active:\n                        flush_body(lane)\n                    if cell.note_type:\n                        if cell.note_type == 0x7:\n                            deferred_hold_heads.append(\n                                (lane, y, segment.row_height, cell.raw)\n                            )\n                        else:\n                            self._draw_note(\n                                painter, lane, y, segment.row_height, cell.raw\n                            )\n\n        if self._playback_active:\n            flush_all_bodies()\n\n        # Hold heads are the top terminal layer. This matters when BeatSplit is\n''',
)
replace_once(
    "src/stepnx/gui/timeline_widget.py",
    '''    def _draw_note(\n        self, painter: QPainter, lane: int, y: float, row_height: float, raw: bytes\n    ) -> None:\n''',
    '''    def _draw_hold_body_span(\n        self,\n        painter: QPainter,\n        lane: int,\n        y: float,\n        span_height: float,\n        raw: bytes,\n    ) -> None:\n        """Draw one playback-only shaft for a contiguous explicit BODY run.\n\n        The encoded BODY rows remain present in the snapshot and paused editor.\n        This is only a rasterization reduction: a split-128 run that would issue\n        hundreds of identical 8-pixel atlas-strip draws becomes one stretched\n        strip over the exact same screen-space interval.\n        """\n\n        span_height = max(1.0, float(span_height))\n        rect = QRectF(*self._geometry.note_rect(lane, y, span_height))\n        if self._draw_noteskin_note(painter, lane, y, span_height, raw, rect):\n            return\n        color = _NOTE_COLORS.get(0xB, QColor("#5f91cf"))\n        shaft_width = max(4.0, rect.width() * 0.28)\n        painter.fillRect(\n            QRectF(\n                rect.center().x() - shaft_width / 2.0,\n                y,\n                shaft_width,\n                span_height,\n            ),\n            color,\n        )\n\n    def _draw_note(\n        self, painter: QPainter, lane: int, y: float, row_height: float, raw: bytes\n    ) -> None:\n''',
)
replace_once(
    "src/stepnx/gui/timeline_widget.py",
    '''    def paintEvent(self, event) -> None:\n        painter = QPainter(self.viewport())\n''',
    '''    def paintEvent(self, event) -> None:\n        paint_started = perf_counter()\n        painter = QPainter(self.viewport())\n''',
)
replace_once(
    "src/stepnx/gui/timeline_widget.py",
    '''        if self._playback_y is not None:\n            painter.setPen(QPen(QColor("#ff5a5f"), 2.0))\n            painter.drawLine(\n                QPointF(0, self._playback_y),\n                QPointF(self._layout.chart_width, self._playback_y),\n            )\n\n    def _draw_segment(self, painter: QPainter, visible) -> None:\n''',
    '''        if self._playback_y is not None:\n            painter.setPen(QPen(QColor("#ff5a5f"), 2.0))\n            painter.drawLine(\n                QPointF(0, self._playback_y),\n                QPointF(self._layout.chart_width, self._playback_y),\n            )\n        self._paint_cost_ms = (perf_counter() - paint_started) * 1000.0\n\n    def _draw_segment(self, painter: QPainter, visible) -> None:\n''',
)

# Surface the host TimelineWidget cost in F6. It is intentionally one event-loop
# iteration behind the gameplay paint, which is sufficient to correlate stalls.
replace_once(
    "src/stepnx/gui/preview_widget.py",
    "        self._advance_cost_ms = 0.0\n        self.setMinimumSize(420, 360)\n",
    "        self._advance_cost_ms = 0.0\n        self._host_paint_cost_ms = 0.0\n        self.setMinimumSize(420, 360)\n",
)
replace_once(
    "src/stepnx/gui/preview_widget.py",
    '''                f"RENDER {fps:6.1f} fps  PAINT {self._paint_cost_ms:6.2f} ms  "\n                f"ADV {self._advance_cost_ms:6.2f} ms  "\n                f"E/G {self.session.last_advance_event_count}/"\n''',
    '''                f"RENDER {fps:6.1f} fps  PAINT {self._paint_cost_ms:6.2f} ms  "\n                f"ADV {self._advance_cost_ms:6.2f} ms  "\n                f"HOST {self._host_paint_cost_ms:6.2f} ms  "\n                f"E/G {self.session.last_advance_event_count}/"\n''',
)

replace_once(
    "src/stepnx/gui/phase10_install.py",
    '''def _sync_external_previews(window, audio_ms: int):\n    chart_ms = window.audio_alignment.audio_to_chart(float(audio_ms))\n    for preview in tuple(getattr(window, "phase10_preview_windows", ())):\n        if preview is not None and hasattr(preview, "set_playback_time"):\n            preview.set_playback_time(chart_ms)\n''',
    '''def _sync_external_previews(window, audio_ms: int):\n    chart_ms = window.audio_alignment.audio_to_chart(float(audio_ms))\n    active = window.tabs.currentWidget() if hasattr(window, "tabs") else None\n    host_paint_ms = float(getattr(active, "_paint_cost_ms", 0.0))\n    for preview in tuple(getattr(window, "phase10_preview_windows", ())):\n        if preview is not None and hasattr(preview, "set_playback_time"):\n            preview._host_paint_cost_ms = host_paint_ms\n            preview.set_playback_time(chart_ms)\n''',
)

# Regression: BODY rows are preserved and individually drawn while paused, but
# contiguous playback bodies collapse into one raster shaft per lane/raw run.
test = Path("tests/unit/test_qt_viewport.py")
text = test.read_text(encoding="utf-8")
anchor = "    def test_hold_terminals_meet_their_per_column_silhouettes(self) -> None:\n"
if anchor not in text:
    raise SystemExit("viewport test anchor not found")
addition = '''    def test_dense_playback_bodies_coalesce_into_one_raster_shaft(self) -> None:\n        document = parse_bytes(\n            make_normal_nx20(), source="dense-body.NX", row_storage="rich"\n        )\n        split = document.splits[0]\n        block = split.blocks[0]\n        rows = list(block.rows)\n        body_count = min(4, len(rows))\n        self.assertGreaterEqual(body_count, 2)\n        for index in range(body_count):\n            row = rows[index]\n            cells = list(row.cells)\n            cells[0] = replace(cells[0], raw=bytes((0x0B, 0x03, 0, 0)))\n            rows[index] = replace(row, cells=tuple(cells))\n        block = replace(block, rows=tuple(rows))\n        document = replace(document, splits=(replace(split, blocks=(block,)),))\n        widget = TimelineWidget(create_authoring_snapshot(document))\n        try:\n            widget.resize(640, 900)\n            widget.set_playback_active(True)\n            visible = widget._layout.visible_segments(\n                0.0, float(widget.viewport().height()), overscan_rows=2\n            )[0]\n            image = QImage(widget.viewport().size(), QImage.Format.Format_ARGB32)\n            image.fill(0)\n            painter = QPainter(image)\n            spans = []\n            notes = []\n            original_span = widget._draw_hold_body_span\n            original_note = widget._draw_note\n\n            def record_span(painter_arg, lane, y, span_height, raw):\n                spans.append((lane, y, span_height, raw))\n                return original_span(painter_arg, lane, y, span_height, raw)\n\n            def record_note(painter_arg, lane, y, row_height, raw):\n                notes.append(raw[0] & 0x0F)\n                return original_note(painter_arg, lane, y, row_height, raw)\n\n            try:\n                with patch.object(widget, "_draw_hold_body_span", side_effect=record_span), patch.object(\n                    widget, "_draw_note", side_effect=record_note\n                ):\n                    widget._draw_segment(painter, visible)\n            finally:\n                painter.end()\n            self.assertEqual(len(spans), 1)\n            self.assertEqual(spans[0][0], 0)\n            self.assertNotIn(0x0B, notes)\n\n            widget.set_playback_active(False)\n            visible = widget._layout.visible_segments(\n                0.0, float(widget.viewport().height()), overscan_rows=2\n            )[0]\n            image = QImage(widget.viewport().size(), QImage.Format.Format_ARGB32)\n            image.fill(0)\n            painter = QPainter(image)\n            paused_notes = []\n            try:\n                def record_paused(painter_arg, lane, y, row_height, raw):\n                    paused_notes.append(raw[0] & 0x0F)\n                    return original_note(painter_arg, lane, y, row_height, raw)\n\n                with patch.object(widget, "_draw_note", side_effect=record_paused):\n                    widget._draw_segment(painter, visible)\n            finally:\n                painter.end()\n            self.assertEqual(paused_notes.count(0x0B), body_count)\n        finally:\n            widget.close()\n\n'''
text = text.replace(anchor, addition + anchor, 1)
test.write_text(text, encoding="utf-8")

# Document why gameplay F6 has a HOST metric and why body coalescing is visual-only.
audit = Path("docs/RISE_RUNTIME_PARITY_HANDOFF.md")
text = audit.read_text(encoding="utf-8")
line = "- Dense playback host optimization: authoring TimelineWidget coalesces contiguous explicit long BODY rows into one raster shaft only while playback projection is active. Encoded rows and paused authoring remain lossless. Gameplay F6 exposes the host timeline's previous paint cost as HOST to distinguish shared-Qt-thread stalls from gameplay PAINT/ADV.\n"
if line not in text:
    text += "\n" + line
audit.write_text(text, encoding="utf-8")
