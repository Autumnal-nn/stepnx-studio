from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected fragment not found in {path}: {old[:180]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Authoring timeline: do not bake shaft continuation into terminal sprites.
# The game draws body/shaft behind the terminals, tail before head. At low
# projected length the body+tail collapse under the head and the hold reads as
# one ordinary arrow. Keep that rule screen-space driven so zoom/Scroll=0 work
# without changing authored rows.
# ---------------------------------------------------------------------------

timeline = Path("src/stepnx/gui/timeline_widget.py")
text = timeline.read_text(encoding="utf-8")
text = text.replace(
    "        self._hold_terminal_pixmaps: dict[tuple[str, int, int, bool], QPixmap] = {}\n",
    "        self._collapsed_hold_cells_cache: frozenset[tuple[int, int]] | None = None\n",
    1,
)
text = text.replace(
    "        self._hold_terminal_pixmaps.clear()\n",
    "",
    1,
)
text = text.replace(
    "        self._layout = TimelineLayout(\n            snapshot, self._geometry, playback=self._playback_active\n        )\n",
    "        self._layout = TimelineLayout(\n            snapshot, self._geometry, playback=self._playback_active\n        )\n        self._collapsed_hold_cells_cache = None\n",
    1,
)
# wheelEvent creates a new layout.
text = text.replace(
    "            self._layout = TimelineLayout(\n                self._snapshot, self._geometry, playback=self._playback_active\n            )\n            self._sync_scrollbars()\n",
    "            self._layout = TimelineLayout(\n                self._snapshot, self._geometry, playback=self._playback_active\n            )\n            self._collapsed_hold_cells_cache = None\n            self._sync_scrollbars()\n",
    1,
)
# set_playback_active creates another layout.
needle = "        self._layout = TimelineLayout(\n            self._snapshot, self._geometry, playback=self._playback_active\n        )\n        self._playback_y = (\n"
replacement = "        self._layout = TimelineLayout(\n            self._snapshot, self._geometry, playback=self._playback_active\n        )\n        self._collapsed_hold_cells_cache = None\n        self._playback_y = (\n"
if needle not in text:
    raise SystemExit("playback layout anchor not found")
text = text.replace(needle, replacement, 1)

start = text.index("    def _hold_terminal_pixmap(\n")
end = text.index("    def _sync_scrollbars(\n", start)
text = text[:start] + text[end:]

# Insert one cached active-layout pass that identifies the body/tail cells whose
# complete projected hold fits underneath one note quad. It intentionally works
# in both paused authoring zoom and playback projection.
insert_at = text.index("    def _draw_segment(self, painter: QPainter, visible) -> None:\n")
helper = '''    def _collapsed_hold_cells(self) -> frozenset[tuple[int, int]]:\n        cached = self._collapsed_hold_cells_cache\n        if cached is not None:\n            return cached\n\n        note_size = max(1.0, self._geometry.lane_width - 4.0)\n        hidden: set[tuple[int, int]] = set()\n        open_holds: dict[int, tuple[float, list[tuple[int, int]]]] = {}\n\n        for segment in self._layout.segments:\n            for row_index, row in enumerate(segment.block.rows):\n                if not isinstance(row, (NoteRow, PackedNoteRow)):\n                    continue\n                centre_y = segment.y_for_row(row_index) + segment.row_height / 2.0\n                for lane in range(row.cell_count):\n                    cell = row.cell(lane) if isinstance(row, PackedNoteRow) else row.cells[lane]\n                    note_type = cell.note_type\n                    key = (row.stable_id, lane)\n                    if note_type == 0x7:\n                        open_holds[lane] = (centre_y, [])\n                    elif note_type == 0xB:\n                        if lane in open_holds:\n                            open_holds[lane][1].append(key)\n                    elif note_type == 0xF and lane in open_holds:\n                        head_y, interior = open_holds.pop(lane)\n                        if abs(centre_y - head_y) <= note_size + 1e-6:\n                            hidden.update(interior)\n                            hidden.add(key)\n\n        result = frozenset(hidden)\n        self._collapsed_hold_cells_cache = result\n        return result\n\n'''
text = text[:insert_at] + helper + text[insert_at:]

# Resolve once for the paint and skip body/tail cells in collapsed holds. Head
# remains deferred to the top terminal layer.
text = text.replace(
    "        deferred_hold_heads: list[tuple[int, float, float, bytes]] = []\n        body_runs: dict[int, tuple[bytes, float, float]] = {}\n",
    "        deferred_hold_heads: list[tuple[int, float, float, bytes]] = []\n        body_runs: dict[int, tuple[bytes, float, float]] = {}\n        collapsed_hold_cells = self._collapsed_hold_cells()\n",
    1,
)
old = """                    cell = row.cell(lane) if isinstance(row, PackedNoteRow) else row.cells[lane]\n                    if self._playback_active and cell.note_type == 0xB:\n"""
new = """                    cell = row.cell(lane) if isinstance(row, PackedNoteRow) else row.cells[lane]\n                    if (row.stable_id, lane) in collapsed_hold_cells:\n                        if self._playback_active:\n                            flush_body(lane)\n                        continue\n                    if self._playback_active and cell.note_type == 0xB:\n"""
if old not in text:
    raise SystemExit("timeline cell draw anchor not found")
text = text.replace(old, new, 1)

# Zero-scroll BODY runs must not manufacture a one-pixel strip.
text = text.replace(
    "            self._draw_hold_body_span(\n                painter, lane, start_y, max(1.0, end_y - start_y), raw\n            )\n",
    "            self._draw_hold_body_span(\n                painter, lane, start_y, end_y - start_y, raw\n            )\n",
    1,
)
text = text.replace(
    "        span_height = max(1.0, float(span_height))\n        rect = QRectF(*self._geometry.note_rect(lane, y, span_height))\n",
    "        span_height = float(span_height)\n        if span_height <= 0.5:\n            return\n        rect = QRectF(*self._geometry.note_rect(lane, y, span_height))\n",
    1,
)

# Terminals use the actual atlas tiles. No synthetic body is pre-composed into
# their transparent area. The separately drawn shaft is already behind them.
old = '''            # Clip terminal continuation per source column. A global boundary\n            # leaves gaps on diagonal silhouettes; a full strip leaks through\n            # transparent pixels behind the arrow.\n            plan = hold_atlas_plan(note_type)\n            tile_x, tile_y, tile_width, tile_height = atlas.tile(atlas_lane, 0)\n            body_source = QRectF(tile_x, tile_y, tile_width, min(8, tile_height))\n            if plan.shaft_above_terminal or plan.shaft_below_terminal:\n                assert plan.terminal_row is not None\n                terminal = self._hold_terminal_pixmap(\n                    pixmap,\n                    atlas,\n                    atlas_lane,\n                    plan.terminal_row,\n                    shaft_above=plan.shaft_above_terminal,\n                )\n                painter.drawPixmap(rect, terminal, QRectF(terminal.rect()))\n                return True\n            if plan.terminal_row is not None:\n                return self._draw_atlas_tile(\n                    painter, atlas, atlas_lane, plan.terminal_row, rect\n                )\n            body_target = QRectF(\n                rect.x(),\n                y,\n                rect.width(),\n                max(1.0, row_height),\n            )\n            painter.drawPixmap(body_target, pixmap, body_source)\n            return plan.repeat_shaft\n'''
new = '''            plan = hold_atlas_plan(note_type)\n            tile_x, tile_y, tile_width, tile_height = atlas.tile(atlas_lane, 0)\n            body_source = QRectF(tile_x, tile_y, tile_width, min(8, tile_height))\n            if plan.terminal_row is not None:\n                return self._draw_atlas_tile(\n                    painter, atlas, atlas_lane, plan.terminal_row, rect\n                )\n            body_target = QRectF(\n                rect.x(),\n                y,\n                rect.width(),\n                max(1.0, row_height),\n            )\n            painter.drawPixmap(body_target, pixmap, body_source)\n            return plan.repeat_shaft\n'''
if old not in text:
    raise SystemExit("timeline terminal compositor block not found")
text = text.replace(old, new, 1)
timeline.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Gameplay preview: shafts are already a separate behind-terminal pass. Add the
# missing game rule: if the complete projected hold fits beneath one terminal,
# suppress the tail as well. The head is already drawn last.
# ---------------------------------------------------------------------------
preview = Path("src/stepnx/gui/preview_widget.py")
text = preview.read_text(encoding="utf-8")
anchor = "    def _draw_note_group(\n"
idx = text.index(anchor)
helper = '''    def _projected_note_centre_and_extent(\n        self, event: PreviewEvent\n    ) -> tuple[QPointF, float]:\n        centre_x, centre_y, rendered_note_size = self._event_render_geometry(event)\n        transform = self._playfield_transform(\n            self._event_throw_z(event) if self._effective_nx_mode() else 0.0\n        )\n        centre = transform.map(QPointF(centre_x, centre_y))\n        top = transform.map(\n            QPointF(centre_x, centre_y - rendered_note_size / 2.0)\n        )\n        bottom = transform.map(\n            QPointF(centre_x, centre_y + rendered_note_size / 2.0)\n        )\n        extent = math.hypot(bottom.x() - top.x(), bottom.y() - top.y())\n        return centre, max(1.0, extent)\n\n    def _collapsed_hold_tail(self, event: PreviewEvent) -> bool:\n        if event.note_type != 0xF:\n            return False\n        pair = self._hold_pair_by_event.get(event)\n        if pair is None:\n            return False\n        head, tail = pair\n        head_centre, head_extent = self._projected_note_centre_and_extent(head)\n        tail_centre, tail_extent = self._projected_note_centre_and_extent(tail)\n        distance = math.hypot(\n            tail_centre.x() - head_centre.x(),\n            tail_centre.y() - head_centre.y(),\n        )\n        return distance <= max(head_extent, tail_extent) + 1e-6\n\n'''
text = text[:idx] + helper + text[idx:]
old = '''        notes = self._visible_render_events() if visible_notes is None else visible_notes\n        # Prime-era charts deliberately use very short high-tick holds as\n        # tap-like ornaments. Preserve chronological order inside each layer,\n        # but draw every head last so a collapsed head/tail pair reads as head.\n        ordered_notes = tuple(note for note in notes if note.note_type != 0x7) + tuple(\n            note for note in notes if note.note_type == 0x7\n        )\n'''
new = '''        notes = self._visible_render_events() if visible_notes is None else visible_notes\n        # The native game collapses a hold whose complete projected length fits\n        # underneath one terminal into the head silhouette. Shaft is already\n        # suppressed by _hold_shaft_height; suppress the covered tail too.\n        drawable_notes = tuple(\n            note for note in notes if not self._collapsed_hold_tail(note)\n        )\n        ordered_notes = tuple(\n            note for note in drawable_notes if note.note_type != 0x7\n        ) + tuple(note for note in drawable_notes if note.note_type == 0x7)\n'''
if old not in text:
    raise SystemExit("preview ordered note block not found")
text = text.replace(old, new, 1)
preview.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
qt_viewport = Path("tests/unit/test_qt_viewport.py")
text = qt_viewport.read_text(encoding="utf-8")
start = text.index("    def test_hold_terminals_meet_their_per_column_silhouettes(self) -> None:\n")
end = text.index("    def test_playback_geometry_is_restored_on_pause(self) -> None:\n", start)
replacement = '''    def test_hold_terminals_do_not_bake_shaft_into_head_artwork(self) -> None:\n        document = parse_bytes(\n            make_large_lightmap(rows=4), source="LM.NX", row_storage="compact"\n        )\n        widget = TimelineWidget(create_authoring_snapshot(document))\n        try:\n            with tempfile.TemporaryDirectory() as temporary:\n                bank = Path(temporary) / "00"\n                bank.mkdir()\n                atlas = QImage(480, 288, QImage.Format.Format_ARGB32)\n                atlas.fill(Qt.GlobalColor.transparent)\n                atlas_painter = QPainter(atlas)\n                try:\n                    atlas_painter.fillRect(QRectF(0, 0, 96, 8), QColor("#00ff00"))\n                    atlas_painter.fillRect(\n                        QRectF(0, 96 + 20, 96, 31), QColor("#0000ff")\n                    )\n                finally:\n                    atlas_painter.end()\n                for frame in range(6):\n                    self.assertTrue(atlas.save(str(bank / f"{frame}.png")))\n                widget.set_noteskin_pack(load_noteskin_pack(temporary))\n                canvas = QImage(96, 96, QImage.Format.Format_ARGB32)\n                canvas.fill(Qt.GlobalColor.transparent)\n                painter = QPainter(canvas)\n                try:\n                    self.assertTrue(\n                        widget._draw_noteskin_note(\n                            painter,\n                            0,\n                            0.0,\n                            24.0,\n                            bytes((0x07, 0, 0, 0)),\n                            QRectF(0, 0, 96, 96),\n                        )\n                    )\n                finally:\n                    painter.end()\n                self.assertEqual(canvas.pixelColor(48, 35), QColor("#0000ff"))\n                self.assertEqual(canvas.pixelColor(48, 70).alpha(), 0)\n        finally:\n            widget.close()\n\n    def test_low_projection_collapses_body_and_tail_to_head_in_editor(self) -> None:\n        document = parse_bytes(\n            make_normal_nx20(), source="collapsed.NX", row_storage="rich"\n        )\n        split = document.splits[0]\n        block = split.blocks[0]\n        rows = list(block.rows)\n        next_id = document.next_stable_id\n        for index, note_type in enumerate((0x07, 0x0B, 0x0F)):\n            row = rows[index]\n            if hasattr(row, "cells"):\n                cells = list(row.cells)\n                cells[0] = replace(cells[0], raw=bytes((note_type, 0x03, 0, 0)))\n            else:\n                cells = []\n                for lane in range(int(document.columns.value)):\n                    raw = bytes((note_type, 0x03, 0, 0)) if lane == 0 else bytes(4)\n                    cells.append(NoteCell(next_id, raw, None))\n                    next_id += 1\n            rows[index] = NoteRow(row.stable_id, tuple(cells), None)\n        block = replace(block, rows=tuple(rows), scroll=block.scroll.with_value(0.1))\n        document = replace(\n            document,\n            splits=(replace(split, blocks=(block,)),),\n            next_stable_id=next_id,\n        )\n        widget = TimelineWidget(create_authoring_snapshot(document))\n        try:\n            widget.resize(640, 900)\n            widget.set_playback_active(True)\n            collapsed = widget._collapsed_hold_cells()\n            self.assertIn((rows[1].stable_id, 0), collapsed)\n            self.assertIn((rows[2].stable_id, 0), collapsed)\n            self.assertNotIn((rows[0].stable_id, 0), collapsed)\n            visible = widget._layout.visible_segments(\n                0.0, float(widget.viewport().height()), overscan_rows=2\n            )[0]\n            image = QImage(widget.viewport().size(), QImage.Format.Format_ARGB32)\n            image.fill(0)\n            painter = QPainter(image)\n            notes = []\n            spans = []\n            original_note = widget._draw_note\n            original_span = widget._draw_hold_body_span\n            try:\n                def record_note(painter_arg, lane, y, row_height, raw):\n                    notes.append(raw[0] & 0x0F)\n                    return original_note(painter_arg, lane, y, row_height, raw)\n\n                def record_span(painter_arg, lane, y, span_height, raw):\n                    spans.append((lane, y, span_height))\n                    return original_span(painter_arg, lane, y, span_height, raw)\n\n                with patch.object(widget, "_draw_note", side_effect=record_note), patch.object(\n                    widget, "_draw_hold_body_span", side_effect=record_span\n                ):\n                    widget._draw_segment(painter, visible)\n            finally:\n                painter.end()\n            self.assertIn(0x07, notes)\n            self.assertNotIn(0x0F, notes)\n            self.assertEqual(spans, [])\n        finally:\n            widget.close()\n\n'''
text = text[:start] + replacement + text[end:]
qt_viewport.write_text(text, encoding="utf-8")

qt_preview = Path("tests/unit/test_qt_preview.py")
text = qt_preview.read_text(encoding="utf-8")
old = '''            widget._chart_time_ms = 0.0\n            image = QImage(widget.size(), QImage.Format.Format_ARGB32)\n            image.fill(0)\n            painter = QPainter(image)\n            draw_order = []\n            try:\n                with patch.object(\n                    widget,\n                    "_draw_asset",\n                    side_effect=lambda _painter, note, _rect: draw_order.append(\n                        note.note_type\n                    )\n                    or True,\n                ):\n                    widget._draw_note_group(\n                        painter,\n                        widget._geometry(),\n                        3,\n                        visible_notes=(head, tail),\n                    )\n            finally:\n                painter.end()\n            self.assertEqual(draw_order, [0x0F, 0x07])\n'''
new = '''            widget._chart_time_ms = 0.0\n            widget._hold_pair_by_event = {head: (head, tail), tail: (head, tail)}\n            image = QImage(widget.size(), QImage.Format.Format_ARGB32)\n            image.fill(0)\n            painter = QPainter(image)\n            draw_order = []\n            try:\n                with patch.object(\n                    widget,\n                    "_draw_asset",\n                    side_effect=lambda _painter, note, _rect: draw_order.append(\n                        note.note_type\n                    )\n                    or True,\n                ), patch.object(\n                    widget,\n                    "_projected_note_centre_and_extent",\n                    side_effect=lambda note: (\n                        QPointF(100.0, 100.0 if note.note_type == 0x07 else 110.0),\n                        64.0,\n                    ),\n                ):\n                    widget._draw_note_group(\n                        painter,\n                        widget._geometry(),\n                        3,\n                        visible_notes=(head, tail),\n                    )\n            finally:\n                painter.end()\n            self.assertEqual(draw_order, [0x07])\n'''
if old not in text:
    raise SystemExit("gameplay collapsed draw order test anchor not found")
text = text.replace(old, new, 1)
# Add a non-collapsed companion immediately after the collapsed test.
needle = "    def test_dense_long_bodies_stay_in_runtime_but_out_of_render_index(self) -> None:\n"
assert needle in text
extra = '''    def test_separated_long_keeps_tail_then_head_order_in_gameplay_preview(self) -> None:\n        widget = self._widget()\n        try:\n            source = widget.stream.events[0]\n            head = replace(\n                source,\n                time_ms=1000.0,\n                row_index=100,\n                raw=bytes((0x07, 0x03, source.raw[2], source.raw[3])),\n            )\n            tail = replace(\n                source,\n                time_ms=1200.0,\n                row_index=200,\n                raw=bytes((0x0F, 0x03, source.raw[2], source.raw[3])),\n            )\n            widget._hold_pair_by_event = {head: (head, tail), tail: (head, tail)}\n            image = QImage(640, 480, QImage.Format.Format_ARGB32)\n            image.fill(0)\n            painter = QPainter(image)\n            draw_order = []\n            try:\n                with patch.object(\n                    widget,\n                    "_draw_asset",\n                    side_effect=lambda _painter, note, _rect: draw_order.append(note.note_type) or True,\n                ), patch.object(\n                    widget,\n                    "_projected_note_centre_and_extent",\n                    side_effect=lambda note: (\n                        QPointF(100.0, 100.0 if note.note_type == 0x07 else 220.0),\n                        64.0,\n                    ),\n                ):\n                    widget._draw_note_group(\n                        painter, widget._geometry(), 3, visible_notes=(head, tail)\n                    )\n            finally:\n                painter.end()\n            self.assertEqual(draw_order, [0x0F, 0x07])\n        finally:\n            widget.close()\n\n'''
text = text.replace(needle, extra + needle, 1)
qt_preview.write_text(text, encoding="utf-8")

# Record the visual evidence so the synthetic terminal compositor is not
# reintroduced later.
audit = Path("docs/PRIME2_PATH_MODIFIER_AUDIT.md")
text = audit.read_text(encoding="utf-8")
section = '''\n## Hold terminal collapse\n\nLegacy gameplay capture (Fiesta 2 EF1299) confirms that high-tick/low-projection holds can collapse visually into a single ordinary head arrow. The renderer must not bake a repeatable shaft into head/tail terminal sprites. StepNX therefore draws the shaft as a separate behind-terminal layer, tail before head, and suppresses body/tail cells when the complete projected hold fits beneath one terminal. This applies to authoring zoom and gameplay projection, including Scroll=0, without removing encoded BODY/tail cells from the document or runtime judgment stream.\n'''
if "## Hold terminal collapse" not in text:
    audit.write_text(text.rstrip() + "\n" + section, encoding="utf-8")
