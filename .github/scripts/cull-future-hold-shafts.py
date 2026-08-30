from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected fragment not found in {path}: {old[:200]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


path = "src/stepnx/gui/preview_widget.py"

replace_once(
    path,
    '''        self._hold_pairs_by_visibility = {\n            visibility: tuple(pairs)\n            for visibility, pairs in hold_pairs_by_visibility.items()\n        }\n\n        self._lane_map_cache = resolved_command.lane_map(\n''',
    '''        self._hold_pairs_by_visibility = {\n            visibility: tuple(pairs)\n            for visibility, pairs in hold_pairs_by_visibility.items()\n        }\n        # Shaft rendering is an interval query, not a chart-tail scan. Keep both\n        # endpoint orders so each frame can approach the visible window from the\n        # cheaper side while preserving arbitrarily long holds that span it.\n        self._hold_head_times_by_visibility = {\n            visibility: tuple(head.time_ms for head, _ in pairs)\n            for visibility, pairs in self._hold_pairs_by_visibility.items()\n        }\n        self._hold_pairs_by_tail_visibility = {\n            visibility: tuple(sorted(pairs, key=lambda pair: pair[1].time_ms))\n            for visibility, pairs in self._hold_pairs_by_visibility.items()\n        }\n        self._hold_tail_times_by_visibility = {\n            visibility: tuple(tail.time_ms for _, tail in pairs)\n            for visibility, pairs in self._hold_pairs_by_tail_visibility.items()\n        }\n        self._render_time_window: tuple[float, float] | None = None\n\n        self._lane_map_cache = resolved_command.lane_map(\n''',
)

replace_once(
    path,
    '''    ) -> tuple[PreviewEvent, ...]:\n        geometry = self._geometry()\n''',
    '''    ) -> tuple[PreviewEvent, ...]:\n        # paintEvent calls this once before drawing notes and shafts. Store the\n        # exact time-domain projection of its screen-space culling window so\n        # long shafts can share it instead of examining the rest of the chart.\n        self._render_time_window = None\n        geometry = self._geometry()\n''',
)

replace_once(
    path,
    '''        if not time_bounds:\n            return ()\n        first = bisect_left(event_times, min(time_bounds) - 250.0)\n        last = bisect_right(event_times, max(time_bounds) + 250.0)\n''',
    '''        if not time_bounds:\n            return ()\n        self._render_time_window = (\n            min(time_bounds) - 250.0,\n            max(time_bounds) + 250.0,\n        )\n        first = bisect_left(event_times, self._render_time_window[0])\n        last = bisect_right(event_times, self._render_time_window[1])\n''',
)

replace_once(
    path,
    '''    def _draw_hold_shafts(\n        self,\n        painter: QPainter,\n        note_size: float,\n        visibility_filter: int,\n    ) -> None:\n        for head, tail in self._hold_pairs_by_visibility.get(\n            int(visibility_filter), ()\n        ):\n''',
    '''    def _visible_hold_pairs(\n        self, visibility_filter: int\n    ) -> tuple[tuple[PreviewEvent, PreviewEvent], ...]:\n        """Return holds whose [head, tail] interval overlaps the draw window.\n\n        The old renderer walked every hold whose tail had not passed yet. On\n        dense charts that made frame cost proportional to the *remaining song*:\n        expensive at the start and progressively cheaper toward the end.\n        """\n\n        window = self._render_time_window\n        if window is None:\n            return ()\n        visibility = int(visibility_filter)\n        pairs_by_head = self._hold_pairs_by_visibility.get(visibility, ())\n        if not pairs_by_head:\n            return ()\n        head_times = self._hold_head_times_by_visibility.get(visibility, ())\n        pairs_by_tail = self._hold_pairs_by_tail_visibility.get(visibility, ())\n        tail_times = self._hold_tail_times_by_visibility.get(visibility, ())\n        window_start, window_end = window\n\n        head_last = bisect_right(head_times, window_end)\n        tail_first = bisect_left(tail_times, window_start)\n\n        # Query from whichever endpoint leaves fewer candidates. Filtering the\n        # opposite endpoint keeps long holds spanning the complete window. This\n        # avoids the previous O(all future holds) behaviour without imposing a\n        # maximum hold duration or assuming monotonic scrolling.\n        if head_last <= len(pairs_by_tail) - tail_first:\n            candidates = pairs_by_head[:head_last]\n        else:\n            candidates = pairs_by_tail[tail_first:]\n        return tuple(\n            (head, tail)\n            for head, tail in candidates\n            if head.time_ms <= window_end and tail.time_ms >= window_start\n        )\n\n    def _draw_hold_shafts(\n        self,\n        painter: QPainter,\n        note_size: float,\n        visibility_filter: int,\n    ) -> None:\n        for head, tail in self._visible_hold_pairs(visibility_filter):\n''',
)

replace_once(
    path,
    '''    def _active_hold_visibilities(self) -> frozenset[int]:\n        time_ms = self._chart_time_ms\n        active: set[int] = set()\n        for visibility, pairs in self._hold_pairs_by_visibility.items():\n            if visibility not in (1, 2):\n                continue\n            if any(head.time_ms <= time_ms <= tail.time_ms for head, tail in pairs):\n                active.add(visibility)\n        return frozenset(active)\n''',
    '''    def _active_hold_visibilities(self) -> frozenset[int]:\n        time_ms = self._chart_time_ms\n        active: set[int] = set()\n        for visibility in (1, 2):\n            if any(\n                head.time_ms <= time_ms <= tail.time_ms\n                for head, tail in self._visible_hold_pairs(visibility)\n            ):\n                active.add(visibility)\n        return frozenset(active)\n''',
)

# Add deterministic regressions around interval selection. No wall-clock test is
# needed: we assert that a huge future tail does not enter the render candidate
# set and that a long spanning the window is retained even when both endpoints
# are outside it.
test_path = "tests/unit/test_qt_preview.py"
anchor = '''    def test_event_beat_distance_reuses_one_native_state_per_frame(self) -> None:\n'''
insert = '''    def test_hold_shaft_candidates_are_windowed_instead_of_chart_tail_scanned(self) -> None:\n        widget = self._widget()\n        try:\n            source = widget.stream.events[0]\n            pairs = []\n            for index in range(1000):\n                head_time = float(index * 1000)\n                head = replace(\n                    source,\n                    time_ms=head_time,\n                    row_index=2000 + index * 2,\n                    raw=bytes((0x07, 0x03, source.raw[2], source.raw[3])),\n                )\n                tail = replace(\n                    source,\n                    time_ms=head_time + 100.0,\n                    row_index=2001 + index * 2,\n                    raw=bytes((0x0F, 0x03, source.raw[2], source.raw[3])),\n                )\n                pairs.append((head, tail))\n            pairs = tuple(pairs)\n            widget._hold_pairs_by_visibility[3] = pairs\n            widget._hold_head_times_by_visibility[3] = tuple(\n                head.time_ms for head, _ in pairs\n            )\n            by_tail = tuple(sorted(pairs, key=lambda pair: pair[1].time_ms))\n            widget._hold_pairs_by_tail_visibility[3] = by_tail\n            widget._hold_tail_times_by_visibility[3] = tuple(\n                tail.time_ms for _, tail in by_tail\n            )\n            widget._render_time_window = (0.0, 1250.0)\n\n            candidates = widget._visible_hold_pairs(3)\n            self.assertEqual(len(candidates), 2)\n            self.assertTrue(all(head.time_ms <= 1250.0 for head, _ in candidates))\n        finally:\n            widget.close()\n\n    def test_hold_shaft_window_keeps_a_long_that_spans_both_screen_edges(self) -> None:\n        widget = self._widget()\n        try:\n            source = widget.stream.events[0]\n            head = replace(\n                source,\n                time_ms=1000.0,\n                row_index=5000,\n                raw=bytes((0x07, 0x03, source.raw[2], source.raw[3])),\n            )\n            tail = replace(\n                source,\n                time_ms=9000.0,\n                row_index=5001,\n                raw=bytes((0x0F, 0x03, source.raw[2], source.raw[3])),\n            )\n            pair = ((head, tail),)\n            widget._hold_pairs_by_visibility[3] = pair\n            widget._hold_head_times_by_visibility[3] = (head.time_ms,)\n            widget._hold_pairs_by_tail_visibility[3] = pair\n            widget._hold_tail_times_by_visibility[3] = (tail.time_ms,)\n            widget._render_time_window = (4000.0, 5000.0)\n\n            self.assertEqual(widget._visible_hold_pairs(3), pair)\n        finally:\n            widget.close()\n\n'''
replace_once(test_path, anchor, insert + anchor)
