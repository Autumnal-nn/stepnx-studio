from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected fragment not found in {path}: {old[:180]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# GameplaySession hot path -------------------------------------------------
replace_once(
    "src/stepnx/preview/session.py",
    "import random\nfrom collections import defaultdict\n",
    "import random\nfrom bisect import bisect_left, bisect_right\nfrom collections import defaultdict\n",
)
replace_once(
    "src/stepnx/preview/session.py",
    "@dataclass(frozen=True, slots=True)\nclass GameplayStats:\n",
    "@dataclass(slots=True)\nclass GameplayStats:\n",
)
replace_once(
    "src/stepnx/preview/session.py",
    '''EventKey = tuple[int, int, int, int]\nGroupKey = tuple[int, int, int, int, int]\n\n\nclass GameplaySession:\n''',
    '''EventKey = tuple[int, int, int, int]\nGroupKey = tuple[int, int, int, int, int]\n\n\n@dataclass(frozen=True, slots=True)\nclass _AutoplayGroup:\n    time_ms: float\n    group_key: GroupKey\n    events: tuple[PreviewEvent, ...]\n    event_keys: tuple[EventKey, ...]\n    projection: JudgeUnitProjection | None\n    step_effect_events: tuple[PreviewEvent, ...]\n\n\nclass GameplaySession:\n''',
)
old_init = '''        groups: dict[GroupKey, list[PreviewEvent]] = defaultdict(list)\n        for event in stream.events:\n            if self.is_judged_note(event):\n                groups[self.group_key(event)].append(event)\n        self._groups = {key: tuple(events) for key, events in groups.items()}\n        self._resolved_groups: set[GroupKey] = set()\n        self._event_cursor = 0\n        self._miss_cursor = 0\n'''
new_init = '''        groups: dict[GroupKey, list[PreviewEvent]] = defaultdict(list)\n        event_group_keys: dict[EventKey, GroupKey] = {}\n        for event in stream.events:\n            if not self.is_judged_note(event):\n                continue\n            event_key = self.event_key(event)\n            group_key = self.group_key(event)\n            groups[group_key].append(event)\n            event_group_keys[event_key] = group_key\n        self._groups = {key: tuple(events) for key, events in groups.items()}\n        self._group_event_keys = {\n            group_key: tuple(self.event_key(event) for event in events)\n            for group_key, events in self._groups.items()\n        }\n        self._event_group_keys = event_group_keys\n\n        # Everything needed to project an autoplay Perfect is static for the\n        # lifetime of this session. Precompute it once while loading the chart\n        # instead of repeatedly decoding long-note attributes in the 60-Hz hot\n        # path. This is particularly important for BeatSplit/TickCount 128.\n        self._autoplay_groups = tuple(\n            _AutoplayGroup(\n                time_ms=float(events[0].time_ms),\n                group_key=group_key,\n                events=events,\n                event_keys=self._group_event_keys[group_key],\n                projection=self._project_group(events, Judgment.PERFECT),\n                step_effect_events=tuple(\n                    event for event in events if self.starts_pad_press(event)\n                ),\n            )\n            for group_key, events in self._groups.items()\n        )\n        self._autoplay_group_times = tuple(\n            group.time_ms for group in self._autoplay_groups\n        )\n        self._event_times = tuple(event.time_ms for event in stream.events)\n        self._resolved_groups: set[GroupKey] = set()\n        self._autoplay_cursor = 0\n        self._event_cursor = 0\n        self._miss_cursor = 0\n        self.last_advance_event_count = 0\n        self.last_advance_group_count = 0\n'''
replace_once("src/stepnx/preview/session.py", old_init, new_init)

replace_once(
    "src/stepnx/preview/session.py",
    '''        self._resolved_groups.clear()\n        self._event_cursor = 0\n        self._miss_cursor = 0\n''',
    '''        self._resolved_groups.clear()\n        self._autoplay_cursor = 0\n        self._event_cursor = 0\n        self._miss_cursor = 0\n        self.last_advance_event_count = 0\n        self.last_advance_group_count = 0\n''',
)

old_stats = '''        current = self.stats\n        self.stats = GameplayStats(\n            perfect=current.perfect + (grade == 0),\n            great=current.great + (grade == 1),\n            good=current.good + (grade == 2),\n            bad=current.bad + (grade == 3),\n            miss=current.miss + (grade == 4),\n            combo=self._bank_combos[3],\n            max_combo=max(current.max_combo, self._bank_max_combos[3]),\n            score=score,\n            gauge=self._gauge.life,\n        )\n'''
new_stats = '''        # This object is read continuously by the renderer. Mutating its slot\n        # fields avoids allocating and garbage-collecting a new dataclass for\n        # every long-body tick while preserving the same public values.\n        current = self.stats\n        current.perfect += grade == 0\n        current.great += grade == 1\n        current.good += grade == 2\n        current.bad += grade == 3\n        current.miss += grade == 4\n        current.combo = self._bank_combos[3]\n        current.max_combo = max(current.max_combo, self._bank_max_combos[3])\n        current.score = score\n        current.gauge = self._gauge.life\n'''
replace_once("src/stepnx/preview/session.py", old_stats, new_stats)

old_finalize = '''        events = self._groups[group_key]\n        if any(self.event_key(event) not in self.judgments for event in events):\n            return\n        judgment = max(\n            (self.judgments[self.event_key(event)] for event in events),\n            key=_JUDGMENT_RANK.__getitem__,\n        )\n        representative = events[0]\n        judged_at = max(\n            self.judged_at_ms[self.event_key(event)] for event in events\n        )\n        worst_errors = [\n            self._errors[self.event_key(event)]\n            for event in events\n            if self.judgments[self.event_key(event)] is judgment\n            and self._errors[self.event_key(event)] is not None\n        ]\n'''
new_finalize = '''        events = self._groups[group_key]\n        event_keys = self._group_event_keys[group_key]\n        if any(key not in self.judgments for key in event_keys):\n            return\n        judgment = max(\n            (self.judgments[key] for key in event_keys),\n            key=_JUDGMENT_RANK.__getitem__,\n        )\n        representative = events[0]\n        judged_at = max(self.judged_at_ms[key] for key in event_keys)\n        worst_errors = [\n            self._errors[key]\n            for key in event_keys\n            if self.judgments[key] is judgment\n            and self._errors.get(key) is not None\n        ]\n'''
replace_once("src/stepnx/preview/session.py", old_finalize, new_finalize)

replace_once(
    "src/stepnx/preview/session.py",
    '''        self._errors[key] = error_ms\n        self._finalize_group(self.group_key(event))\n\n    def _held_at(self, event: PreviewEvent) -> bool:\n''',
    '''        self._errors[key] = error_ms\n        self._finalize_group(\n            self._event_group_keys.get(key, self.group_key(event))\n        )\n\n    def _record_autoplay_group(\n        self, group: _AutoplayGroup, judged_at_ms: float\n    ) -> None:\n        """Record one predecoded autoplay group without per-cell finalization.\n\n        Ordinary runtime still exposes one judgment entry per cell. The fast\n        path only removes redundant structural work: all members are known to\n        receive the same Perfect grade, so the group can be finalized exactly\n        once instead of once after every inserted body tick.\n        """\n\n        if group.group_key in self._resolved_groups:\n            return\n        if any(key in self.judgments for key in group.event_keys):\n            # Autoplay toggled on after partial manual interaction. Preserve the\n            # generic mixed-state behavior rather than overwriting prior grades.\n            for event, key in zip(group.events, group.event_keys):\n                if key not in self.judgments:\n                    self._record_event(\n                        event,\n                        Judgment.PERFECT,\n                        0.0,\n                        judged_at_ms=judged_at_ms,\n                    )\n            return\n\n        for key in group.event_keys:\n            self.judgments[key] = Judgment.PERFECT\n            self.judged_at_ms[key] = float(judged_at_ms)\n        self._resolved_groups.add(group.group_key)\n        representative = group.events[0]\n        self.judgment_history.append((float(judged_at_ms), representative))\n        self.last_judgment = Judgment.PERFECT\n        self.last_error_ms = 0.0\n        if group.projection is not None:\n            self._apply_native_postprocess(group.projection)\n\n    def _held_at(self, event: PreviewEvent) -> bool:\n''',
)

old_advance = '''    def advance(self, time_ms: float) -> None:\n        time_ms = float(time_ms)\n        if time_ms < self.time_ms:\n            self.reset()\n        previous_time = self.time_ms\n        self._advance_speed(previous_time, time_ms)\n        self.time_ms = time_ms\n        events = self.stream.events\n\n        while self._event_cursor < len(events):\n            event = events[self._event_cursor]\n            if event.time_ms > time_ms:\n                break\n            self._event_cursor += 1\n            if not self.is_judged_note(event):\n                continue\n            if self.autoplay:\n                self._record_event(\n                    event,\n                    Judgment.PERFECT,\n                    0.0,\n                    judged_at_ms=event.time_ms,\n                )\n                if (\n                    self.starts_pad_press(event)\n                    and event.time_ms > previous_time\n                    and event.time_ms >= time_ms - 250.0\n                ):\n                    self._emit_step_effect(event, event.time_ms)\n            elif event.note_type in (0xB, 0xF) and self._held_at(event):\n                self._record_event(\n                    event,\n                    Judgment.PERFECT,\n                    0.0,\n                    judged_at_ms=event.time_ms,\n                )\n\n        miss_cutoff = time_ms - self.windows.late_limit_ms\n        while self._miss_cursor < len(events):\n            event = events[self._miss_cursor]\n            if event.time_ms >= miss_cutoff:\n                break\n            self._miss_cursor += 1\n            if self.is_judged_note(event):\n                self._record_event(event, Judgment.MISS, None)\n'''
new_advance = '''    def advance(self, time_ms: float) -> None:\n        time_ms = float(time_ms)\n        if time_ms < self.time_ms:\n            self.reset()\n        previous_time = self.time_ms\n        self._advance_speed(previous_time, time_ms)\n        self.time_ms = time_ms\n        self.last_advance_event_count = 0\n        self.last_advance_group_count = 0\n\n        if self.autoplay:\n            groups = self._autoplay_groups\n            while self._autoplay_cursor < len(groups):\n                group = groups[self._autoplay_cursor]\n                if group.time_ms > time_ms:\n                    break\n                self._autoplay_cursor += 1\n                self.last_advance_group_count += 1\n                self.last_advance_event_count += len(group.events)\n                self._record_autoplay_group(group, group.time_ms)\n                if (\n                    group.time_ms > previous_time\n                    and group.time_ms >= time_ms - 250.0\n                ):\n                    for event in group.step_effect_events:\n                        self._emit_step_effect(event, group.time_ms)\n\n            # Every eligible past group is already Perfect. Running the manual\n            # miss cursor here used to traverse the same dense body stream a\n            # second time just to rediscover those dictionary entries.\n            return\n\n        events = self.stream.events\n        while self._event_cursor < len(events):\n            event = events[self._event_cursor]\n            if event.time_ms > time_ms:\n                break\n            self._event_cursor += 1\n            self.last_advance_event_count += 1\n            if not self.is_judged_note(event):\n                continue\n            if event.note_type in (0xB, 0xF) and self._held_at(event):\n                self._record_event(\n                    event,\n                    Judgment.PERFECT,\n                    0.0,\n                    judged_at_ms=event.time_ms,\n                )\n\n        miss_cutoff = time_ms - self.windows.late_limit_ms\n        while self._miss_cursor < len(events):\n            event = events[self._miss_cursor]\n            if event.time_ms >= miss_cutoff:\n                break\n            self._miss_cursor += 1\n            if self.is_judged_note(event):\n                self._record_event(event, Judgment.MISS, None)\n'''
replace_once("src/stepnx/preview/session.py", old_advance, new_advance)

replace_once(
    "src/stepnx/preview/session.py",
    '''    def toggle_autoplay(self) -> bool:\n        self.autoplay = not self.autoplay\n        return self.autoplay\n''',
    '''    def toggle_autoplay(self) -> bool:\n        self.autoplay = not self.autoplay\n        if self.autoplay:\n            # Do not retroactively Perfect notes from the manual past, but keep\n            # a group exactly at the toggle timestamp eligible for the next tick.\n            self._autoplay_cursor = bisect_left(\n                self._autoplay_group_times, self.time_ms\n            )\n        else:\n            # Autoplay already resolved everything through the current time.\n            # Start manual cursors at the first future / not-yet-expired event.\n            self._event_cursor = bisect_right(self._event_times, self.time_ms)\n            miss_cutoff = self.time_ms - self.windows.late_limit_ms\n            self._miss_cursor = bisect_left(self._event_times, miss_cutoff)\n        return self.autoplay\n''',
)

# Measure runtime independently from paint in F6 diagnostics ----------------
replace_once(
    "src/stepnx/gui/preview_widget.py",
    '''        self._paint_timestamps: deque[float] = deque(maxlen=120)\n        self._paint_cost_ms = 0.0\n''',
    '''        self._paint_timestamps: deque[float] = deque(maxlen=120)\n        self._paint_cost_ms = 0.0\n        self._advance_cost_ms = 0.0\n''',
)
replace_once(
    "src/stepnx/gui/preview_widget.py",
    '''        self._native_state_time = self._chart_time_ms\n        self._native_state = self.stream.native_state_at(self._chart_time_ms)\n        self.session.advance(self._chart_time_ms)\n        self.update()\n''',
    '''        self._native_state_time = self._chart_time_ms\n        self._native_state = self.stream.native_state_at(self._chart_time_ms)\n        advance_started = perf_counter()\n        self.session.advance(self._chart_time_ms)\n        self._advance_cost_ms = (perf_counter() - advance_started) * 1000.0\n        self.update()\n''',
)
replace_once(
    "src/stepnx/gui/preview_widget.py",
    '''            f"RENDER {fps:6.1f} fps  PAINT {self._paint_cost_ms:6.2f} ms",\n''',
    '''            (\n                f"RENDER {fps:6.1f} fps  PAINT {self._paint_cost_ms:6.2f} ms  "\n                f"ADV {self._advance_cost_ms:6.2f} ms  "\n                f"E/G {self.session.last_advance_event_count}/"\n                f"{self.session.last_advance_group_count}"\n            ),\n''',
)

# Tests --------------------------------------------------------------------
test = Path("tests/unit/test_preview.py")
text = test.read_text(encoding="utf-8")
anchor = '''    def test_chord_produces_one_normal_judgment_not_jn_per_cell(self) -> None:\n'''
if anchor not in text:
    raise SystemExit("runtime test anchor missing")
dense_tests = '''    def test_dense_autoplay_batches_groups_without_running_manual_miss_cursor(self) -> None:\n        stream = self._hold_stream()\n        template = stream.events[1]\n        dense_events = tuple(\n            replace(\n                template,\n                time_ms=float(index) / 3.0,\n                beat=float(index) / 384.0,\n                row_index=index,\n                lane=index % 5,\n            )\n            for index in range(3000)\n        )\n        stream = replace(stream, events=dense_events)\n        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=True)\n        stats_identity = id(session.stats)\n\n        session.advance(1001.0)\n\n        self.assertEqual(len(session.judgments), 3000)\n        self.assertEqual(session.stats.perfect, 3000)\n        self.assertEqual(session.stats.combo, 3000)\n        self.assertEqual(id(session.stats), stats_identity)\n        self.assertEqual(session.last_advance_event_count, 3000)\n        self.assertEqual(session.last_advance_group_count, 3000)\n        self.assertEqual(session._miss_cursor, 0)\n\n    def test_autoplay_toggle_keeps_manual_past_and_future_cursor_boundaries(self) -> None:\n        stream = self._hold_stream()\n        session = GameplaySession(stream, parse_gameplay_command(""), autoplay=False)\n        head, body, tail = stream.events\n        session.advance(body.time_ms + 0.1)\n        self.assertGreaterEqual(session._event_cursor, 2)\n\n        self.assertTrue(session.toggle_autoplay())\n        session.advance(tail.time_ms + 0.1)\n        self.assertIn(session.event_key(tail), session.judgments)\n\n        self.assertFalse(session.toggle_autoplay())\n        self.assertGreaterEqual(session._event_cursor, len(stream.events))\n\n'''
text = text.replace(anchor, dense_tests + anchor, 1)
test.write_text(text, encoding="utf-8")

qt_test = Path("tests/unit/test_qt_preview.py")
text = qt_test.read_text(encoding="utf-8")
anchor = '''    def test_event_culling_uses_chart_time_without_mutating_stream(self) -> None:\n'''
if anchor not in text:
    raise SystemExit("qt debug test anchor missing")
debug_test = '''    def test_runtime_advance_cost_is_measured_separately_from_paint(self) -> None:\n        widget = self._widget()\n        try:\n            widget.set_playback_time(100.0)\n            self.assertGreaterEqual(widget._advance_cost_ms, 0.0)\n            self.assertIsInstance(widget.session.last_advance_event_count, int)\n            self.assertIsInstance(widget.session.last_advance_group_count, int)\n        finally:\n            widget.close()\n\n'''
text = text.replace(anchor, debug_test + anchor, 1)
qt_test.write_text(text, encoding="utf-8")

handoff = Path("docs/RISE_RUNTIME_PARITY_HANDOFF.md")
text = handoff.read_text(encoding="utf-8")
addition = '''\n- Dense-long runtime optimization: autoplay now advances predecoded judgment groups instead of feeding every body through `_record_event`/`_finalize_group` and then traversing the same stream again through the manual Miss cursor. Per-cell `judgments` and native score/combo/gauge semantics remain intact. Perfect-group projection is prepared at session construction, group event keys are cached, and `GameplayStats` mutates in place to remove one dataclass allocation per judged group. F6 now reports `ADV` separately from `PAINT`, plus events/groups consumed by the latest runtime tick.\n'''
if "Dense-long runtime optimization:" not in text:
    text += addition
handoff.write_text(text, encoding="utf-8")
