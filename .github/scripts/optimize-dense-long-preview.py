from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected fragment not found in {path}: {old[:180]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


path = "src/stepnx/gui/preview_widget.py"

replace_once(
    path,
    '''        self._event_times = tuple(event.time_ms for event in stream.events)\n        self._hold_pairs = self._pair_holds(stream.events)\n        self._hold_pair_by_event = {\n            event: (head, tail)\n            for head, tail in self._hold_pairs\n            for event in (head, tail)\n        }\n        self._paint_timestamps: deque[float] = deque(maxlen=120)\n        self._paint_cost_ms = 0.0\n''',
    '''        self._event_times = tuple(event.time_ms for event in stream.events)\n        # Long bodies (0xB) participate in judgment/runtime state, but the\n        # renderer never draws them as standalone notes. Keep a separate draw\n        # index so pathological BeatSplit=128 holds do not make paintEvent walk\n        # thousands of invisible body ticks every frame.\n        self._render_events = tuple(\n            event for event in stream.events if event.note_type != 0xB\n        )\n        self._render_event_times = tuple(\n            event.time_ms for event in self._render_events\n        )\n        self._duration_ms = stream.duration_ms\n        self._hold_pairs = self._pair_holds(stream.events)\n        self._hold_pair_by_event = {\n            event: (head, tail)\n            for head, tail in self._hold_pairs\n            for event in (head, tail)\n        }\n        hold_pairs_by_visibility: dict[int, list[tuple[PreviewEvent, PreviewEvent]]] = {\n            0: [], 1: [], 2: [], 3: []\n        }\n        for head, tail in self._hold_pairs:\n            visibility = resolved_command.effective_visibility(int(head.visibility))\n            hold_pairs_by_visibility.setdefault(visibility, []).append((head, tail))\n        self._hold_pairs_by_visibility = {\n            visibility: tuple(pairs)\n            for visibility, pairs in hold_pairs_by_visibility.items()\n        }\n\n        self._lane_map_cache = resolved_command.lane_map(\n            self.columns, seed=stream.route.seed or 0\n        )\n        inverse_lanes = list(range(self.columns))\n        for visual_lane, source_lane in enumerate(self._lane_map_cache):\n            if 0 <= source_lane < self.columns:\n                inverse_lanes[source_lane] = visual_lane\n        self._visual_lane_cache = tuple(inverse_lanes)\n\n        block_styles: dict[int, PlayfieldStyle] = {}\n        for block_id, params in stream.block_step_params:\n            for param in params:\n                if param.metadata_id != 200:\n                    continue\n                try:\n                    block_styles[block_id] = PlayfieldStyle(param.raw_value)\n                except ValueError:\n                    pass\n                break\n        self._block_playfield_styles = block_styles\n        self._native_state_time = 0.0\n        self._native_state = stream.native_state_at(0.0)\n        self._geometry_cache_key: tuple[float, PlayfieldStyle] | None = None\n        self._geometry_cache: PlayfieldGeometry | None = None\n\n        self._paint_timestamps: deque[float] = deque(maxlen=120)\n        self._paint_cost_ms = 0.0\n''',
)

replace_once(
    path,
    '''        self._chart_time_ms = float(chart_time_ms)\n        self.session.advance(self._chart_time_ms)\n        self.update()\n''',
    '''        self._chart_time_ms = float(chart_time_ms)\n        self._native_state_time = self._chart_time_ms\n        self._native_state = self.stream.native_state_at(self._chart_time_ms)\n        self.session.advance(self._chart_time_ms)\n        self.update()\n''',
)

replace_once(
    path,
    '''    def _default_playfield_style(self) -> PlayfieldStyle:\n        return default_playfield_style(self.columns)\n\n    def _active_playfield_style(self) -> PlayfieldStyle:\n''',
    '''    def _default_playfield_style(self) -> PlayfieldStyle:\n        return default_playfield_style(self.columns)\n\n    def _current_native_state(self):\n        timing = self.stream.native_timing\n        if timing is None:\n            return None\n        if self._native_state_time != self._chart_time_ms:\n            self._native_state_time = self._chart_time_ms\n            self._native_state = timing.state_at(self._chart_time_ms)\n        return self._native_state\n\n    def _active_playfield_style(self) -> PlayfieldStyle:\n''',
)

replace_once(
    path,
    '''        default = self._default_playfield_style()\n        timing = self.stream.native_timing\n        if timing is None or not timing.blocks:\n            return default\n        state = timing.state_at(self._chart_time_ms)\n        block_id = timing.blocks[state.block_index].block_id\n        for current_block_id, params in self.stream.block_step_params:\n            if current_block_id != block_id:\n                continue\n            for param in params:\n                if param.metadata_id != 200:\n                    continue\n                try:\n                    return PlayfieldStyle(param.raw_value)\n                except ValueError:\n                    return default\n            break\n        return default\n\n    def _geometry(self) -> PlayfieldGeometry:\n        return PlayfieldGeometry(\n            max(1.0, float(self.width())),\n            self.columns,\n            self._active_playfield_style(),\n            self.start_column,\n        )\n''',
    '''        default = self._default_playfield_style()\n        timing = self.stream.native_timing\n        state = self._current_native_state()\n        if timing is None or not timing.blocks or state is None:\n            return default\n        block_id = timing.blocks[state.block_index].block_id\n        return self._block_playfield_styles.get(block_id, default)\n\n    def _geometry(self) -> PlayfieldGeometry:\n        width = max(1.0, float(self.width()))\n        style = self._active_playfield_style()\n        key = (width, style)\n        if self._geometry_cache_key != key or self._geometry_cache is None:\n            self._geometry_cache_key = key\n            self._geometry_cache = PlayfieldGeometry(\n                width,\n                self.columns,\n                style,\n                self.start_column,\n            )\n        return self._geometry_cache\n''',
)

replace_once(
    path,
    '''    def _lane_map(self) -> tuple[int, ...]:\n        return self.command.lane_map(self.columns, seed=self.stream.route.seed or 0)\n''',
    '''    def _lane_map(self) -> tuple[int, ...]:\n        return self._lane_map_cache\n''',
)

replace_once(
    path,
    '''    def _visual_lane(self, source_lane: int) -> int:\n        try:\n            return self._lane_map().index(source_lane)\n        except ValueError:\n            return source_lane\n''',
    '''    def _visual_lane(self, source_lane: int) -> int:\n        lane = int(source_lane)\n        if 0 <= lane < len(self._visual_lane_cache):\n            return self._visual_lane_cache[lane]\n        return lane\n''',
)

replace_once(
    path,
    '''    def _event_beat_distance(self, event: PreviewEvent) -> float:\n        return self.stream.beat_distance_at(event, self._chart_time_ms)\n''',
    '''    def _event_beat_distance(self, event: PreviewEvent) -> float:\n        return self.stream.beat_distance_at(\n            event,\n            self._chart_time_ms,\n            state=self._current_native_state(),\n        )\n''',
)

# Preserve the public visible_events contract, but give paintEvent a body-free
# render path and share one culling implementation between both.
replace_once(
    path,
    '''    def visible_events(self) -> tuple[PreviewEvent, ...]:\n        geometry = self._geometry()\n''',
    '''    def _visible_events_from(\n        self,\n        events: tuple[PreviewEvent, ...],\n        event_times: tuple[float, ...],\n    ) -> tuple[PreviewEvent, ...]:\n        geometry = self._geometry()\n''',
)

# Replace the references inside the newly renamed helper only.
text = Path(path).read_text(encoding="utf-8")
helper_start = text.index("    def _visible_events_from(")
helper_end = text.index("\n    @staticmethod\n    def _pair_holds", helper_start)
helper = text[helper_start:helper_end]
helper = helper.replace("if not timing or not self.stream.events:", "if not timing or not events:")
helper = helper.replace(
    "if self._chart_time_ms > self.stream.duration_ms + 250.0:",
    "if self._chart_time_ms > self._duration_ms + 250.0:",
)
helper = helper.replace("bisect_left(self._event_times,", "bisect_left(event_times,")
helper = helper.replace("bisect_right(self._event_times,", "bisect_right(event_times,")
helper = helper.replace("for event in self.stream.events[first:last]", "for event in events[first:last]")
helper += '''\n    def visible_events(self) -> tuple[PreviewEvent, ...]:\n        """Return all visible runtime events, including long-body judgment ticks."""\n\n        return self._visible_events_from(self.stream.events, self._event_times)\n\n    def _visible_render_events(self) -> tuple[PreviewEvent, ...]:\n        """Return only events that can produce standalone draw calls."""\n\n        return self._visible_events_from(self._render_events, self._render_event_times)\n'''
text = text[:helper_start] + helper + text[helper_end:]
Path(path).write_text(text, encoding="utf-8")

replace_once(
    path,
    '''        for head, tail in self._hold_pairs:\n            if self._effective_visibility(head) != int(visibility_filter):\n                continue\n''',
    '''        for head, tail in self._hold_pairs_by_visibility.get(\n            int(visibility_filter), ()\n        ):\n''',
)

replace_once(
    path,
    '''    def _draw_note_group(\n        self,\n        painter: QPainter,\n        geometry: PlayfieldGeometry,\n        visibility_filter: int,\n    ) -> None:\n        self._draw_hold_shafts(painter, geometry.note_size, visibility_filter)\n        for note in self.visible_events():\n            if note.note_type == 0xB:\n                continue\n''',
    '''    def _draw_note_group(\n        self,\n        painter: QPainter,\n        geometry: PlayfieldGeometry,\n        visibility_filter: int,\n        visible_notes: tuple[PreviewEvent, ...] | list[PreviewEvent] | None = None,\n    ) -> None:\n        self._draw_hold_shafts(painter, geometry.note_size, visibility_filter)\n        notes = self._visible_render_events() if visible_notes is None else visible_notes\n        for note in notes:\n''',
)

replace_once(
    path,
    '''    def _render_visibility_layer(\n        self,\n        geometry: PlayfieldGeometry,\n        visibility: int,\n    ) -> QImage:\n''',
    '''    def _render_visibility_layer(\n        self,\n        geometry: PlayfieldGeometry,\n        visibility: int,\n        visible_notes: tuple[PreviewEvent, ...] | list[PreviewEvent],\n    ) -> QImage:\n''',
)

replace_once(
    path,
    '''            layer.setRenderHint(QPainter.RenderHint.Antialiasing, True)\n            layer.setTransform(self._playfield_transform(), False)\n            self._draw_note_group(layer, geometry, visibility)\n''',
    '''            layer.setRenderHint(QPainter.RenderHint.Antialiasing, True)\n            layer.setTransform(self._playfield_transform(), False)\n            self._draw_note_group(\n                layer, geometry, visibility, visible_notes=visible_notes\n            )\n''',
)

# Add a cheap active-hold check so full-size Appear/Vanish QImages are created
# only when that family can actually contribute pixels in the current frame.
replace_once(
    path,
    '''    def _draw_sequence_zone(\n''',
    '''    def _active_hold_visibilities(self) -> frozenset[int]:\n        time_ms = self._chart_time_ms\n        active: set[int] = set()\n        for visibility, pairs in self._hold_pairs_by_visibility.items():\n            if visibility not in (1, 2):\n                continue\n            if any(head.time_ms <= time_ms <= tail.time_ms for head, tail in pairs):\n                active.add(visibility)\n        return frozenset(active)\n\n    def _draw_sequence_zone(\n''',
)

# Replace the repeated draw/cull path inside paintEvent with one render-event
# cull and per-visibility buckets. Judgment bodies stay in GameplaySession.
replace_once(
    path,
    '''        self._draw_sequence_zone(painter, geometry, receptor_y)\n        if self._flash_visible():\n            self._draw_note_group(painter, geometry, 3)\n        painter.restore()\n\n        if self._flash_visible():\n            # NXA/Prime apply Appear/Vanish through a screen-space alpha texture.\n            # Render each transition family into a device-space layer, then\n            # multiply by that exact vertical mask after all 3-D transforms.\n            for visibility in (1, 2):\n                layer = self._render_visibility_layer(geometry, visibility)\n                painter.drawImage(0, 0, layer)\n''',
    '''        self._draw_sequence_zone(painter, geometry, receptor_y)\n        flash_visible = self._flash_visible()\n        visible_by_visibility: dict[int, list[PreviewEvent]] = {1: [], 2: [], 3: []}\n        if flash_visible:\n            for note in self._visible_render_events():\n                visibility = self._effective_visibility(note)\n                if visibility in visible_by_visibility:\n                    visible_by_visibility[visibility].append(note)\n            self._draw_note_group(\n                painter,\n                geometry,\n                3,\n                visible_notes=visible_by_visibility[3],\n            )\n        painter.restore()\n\n        if flash_visible:\n            # NXA/Prime apply Appear/Vanish through a screen-space alpha texture.\n            # Full-size intermediate images are expensive, so create them only\n            # when a transition-family note is visible or a matching long is\n            # currently held across the receptor.\n            active_hold_visibilities = self._active_hold_visibilities()\n            for visibility in (1, 2):\n                notes = visible_by_visibility[visibility]\n                if not notes and visibility not in active_hold_visibilities:\n                    continue\n                layer = self._render_visibility_layer(\n                    geometry, visibility, visible_notes=notes\n                )\n                painter.drawImage(0, 0, layer)\n''',
)

# Tests: deterministic workload assertions, not wall-clock thresholds.
test = Path("tests/unit/test_qt_preview.py")
text = test.read_text(encoding="utf-8")
text = text.replace("import unittest\n", "import unittest\nfrom unittest.mock import patch\n", 1)
anchor = "    def test_event_culling_uses_chart_time_without_mutating_stream(self) -> None:\n"
if anchor not in text:
    raise SystemExit("Qt test insertion anchor missing")
insert = '''    def test_dense_long_bodies_stay_in_runtime_but_out_of_render_index(self) -> None:\n        base = self._widget()\n        try:\n            source = base.stream.events[0]\n            bodies = tuple(\n                replace(\n                    source,\n                    time_ms=source.time_ms + index * 3.125,\n                    row_index=1000 + index,\n                    raw=bytes((0x0B, 0x03, source.raw[2], source.raw[3])),\n                )\n                for index in range(1024)\n            )\n            stream = replace(\n                base.stream,\n                events=tuple(sorted(base.stream.events + bodies, key=lambda event: event.time_ms)),\n            )\n            widget = GameplayPreviewWidget(\n                stream,\n                columns=base.columns,\n                start_column=base.start_column,\n                command=parse_gameplay_command(""),\n            )\n            try:\n                self.assertEqual(\n                    sum(event.note_type == 0xB for event in widget.stream.events),\n                    1024,\n                )\n                self.assertFalse(any(event.note_type == 0xB for event in widget._render_events))\n                self.assertLess(len(widget._render_events), len(widget.stream.events))\n            finally:\n                widget.close()\n        finally:\n            base.close()\n\n    def test_paint_culls_render_events_once_and_skips_empty_visibility_layers(self) -> None:\n        widget = self._widget()\n        try:\n            widget.resize(640, 480)\n            widget.show()\n            widget.set_playback_time(widget.stream.events[0].time_ms)\n            image = QImage(widget.size(), QImage.Format.Format_ARGB32)\n            image.fill(0)\n            painter = QPainter(image)\n            try:\n                with patch.object(\n                    widget,\n                    "_visible_render_events",\n                    wraps=widget._visible_render_events,\n                ) as visible, patch.object(\n                    widget,\n                    "_render_visibility_layer",\n                    wraps=widget._render_visibility_layer,\n                ) as layer:\n                    widget.render(painter, QPoint())\n                    self.assertEqual(visible.call_count, 1)\n                    self.assertEqual(layer.call_count, 0)\n            finally:\n                painter.end()\n        finally:\n            widget.close()\n\n    def test_event_beat_distance_reuses_one_native_state_per_frame(self) -> None:\n        widget = self._widget()\n        try:\n            widget.set_playback_time(widget.stream.events[0].time_ms)\n            timing_type = type(widget.stream.native_timing)\n            with patch.object(\n                timing_type,\n                "state_at",\n                wraps=timing_type.state_at,\n                autospec=True,\n            ) as state_at:\n                for event in widget.stream.events[:8]:\n                    widget._event_beat_distance(event)\n                self.assertEqual(state_at.call_count, 0)\n        finally:\n            widget.close()\n\n'''
text = text.replace(anchor, insert + anchor, 1)
test.write_text(text, encoding="utf-8")

# Record the performance boundary and fixture used to find it.
audit = Path("docs/PRIME2_PATH_MODIFIER_AUDIT.md")
text = audit.read_text(encoding="utf-8")
section = '''\n## Dense long-note preview performance\n\nFiesta 2 `/D/EF1299` is the stress reference for runtime preview density. Its NX contains 12,817 long-body cells and several BeatSplit=128 sections, including a block with 2,890 body ticks over 320 rows. A 60 fps screen capture exposed 7-10 repeated display frames (roughly 120-170 ms) while those walls were active.\n\nLong-body `0x0B` events remain fully present in `RuntimeEventStream` and `GameplaySession` for judgment, combo, score and gauge semantics, but they are now excluded from the standalone render-event index because the renderer already represents them through paired hold shafts. The preview also caches one native timing state, playfield geometry and lane map per frame/state, culls render events once per paint, groups them by visibility once, and avoids allocating full-screen Appear/Vanish intermediate images when that family cannot contribute pixels. These are projection-only optimizations; authored NX and runtime judgment semantics are unchanged.\n'''
if "## Dense long-note preview performance" not in text:
    text += section
audit.write_text(text, encoding="utf-8")
