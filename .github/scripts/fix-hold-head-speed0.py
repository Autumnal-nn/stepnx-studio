from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected fragment not found in {path}: {old[:180]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Header 0 has different runtime normalization in R!SE versus the Prime-era
# engines. Keep apply_step_params source-exact for R!SE, and add a profile-aware
# entry point for NX20 preview snapshots/streams.
replace_once(
    "src/stepnx/preview/modifiers.py",
    '''def _judge_parameter(value: int) -> tuple[float, float]:\n''',
    '''LEGACY_DIRECT_HEADER_SPEED_PROFILES = frozenset(\n    {"nxa-native", "fiesta2", "prime2", "nxa-step5-patched"}\n)\n\n\ndef _judge_parameter(value: int) -> tuple[float, float]:\n''',
)
replace_once(
    "src/stepnx/preview/modifiers.py",
    '''    return result\n''',
    '''    return result\n''',
)
# Insert the profile-aware wrapper after apply_step_params, where it can reuse
# the exact R!SE dispatcher for every other Header field and preserve 1111 order.
modifiers = Path("src/stepnx/preview/modifiers.py")
text = modifiers.read_text(encoding="utf-8")
anchor = '''    return result\n'''
# Use the last return of apply_step_params rather than the many helper returns.
position = text.rfind(anchor)
if position < 0:
    raise SystemExit("could not locate apply_step_params terminal return")
position += len(anchor)
wrapper = '''\n\ndef apply_header_step_params(\n    params: tuple[StepParam, ...],\n    profile: str,\n    base: EffectiveModifier | None = None,\n) -> EffectiveModifier:\n    """Apply Header params using the selected engine family's Speed semantics.\n\n    R!SE's ApplyStepParamToMod normalizes Header 0 by 0.25 for float values in\n    0..255. Prime/Fiesta-era NX20 charts serialize the *final* speed multiplier\n    as an IEEE-754 float instead. Corpus examples include 2.80, 3.66, 4.35 and\n    5.50, so applying R!SE's quarter-speed conversion to those profiles turns\n    EF1299's authored 4.0 into the erroneous 1.0x seen in preview.\n\n    Header 1111 remains downstream: the direct legacy Header-0 value is placed\n    into the base modifier first, then the recovered dispatcher handles all\n    remaining fields and multiplies speed by 1111 in its native order.\n    """\n\n    allow_mid = profile == "nxa-step5-patched"\n    if profile not in LEGACY_DIRECT_HEADER_SPEED_PROFILES:\n        return apply_step_params(params, base, allow_mid=allow_mid)\n\n    speed = _present_float(params, 0)\n    if speed is None:\n        return apply_step_params(params, base, allow_mid=allow_mid)\n\n    result = EffectiveModifier() if base is None else base\n    result = replace(result, speed=float(speed))\n    without_speed = tuple(param for param in params if param.metadata_id != 0)\n    return apply_step_params(without_speed, result, allow_mid=allow_mid)\n'''
text = text[:position] + wrapper + text[position:]
modifiers.write_text(text, encoding="utf-8")

replace_once(
    "src/stepnx/preview/events.py",
    "from stepnx.preview.modifiers import EffectiveModifier, StepParam, apply_step_params\n",
    "from stepnx.preview.modifiers import (\n    EffectiveModifier,\n    StepParam,\n    apply_header_step_params,\n)\n",
)
replace_once(
    "src/stepnx/preview/events.py",
    '''        base = EffectiveModifier(speed=float(speed))\n        return apply_step_params(\n            self.header_step_params,\n            base,\n            allow_mid=self.profile == "nxa-step5-patched",\n        )\n''',
    '''        base = EffectiveModifier(speed=float(speed))\n        return apply_header_step_params(\n            self.header_step_params,\n            self.profile,\n            base,\n        )\n''',
)
replace_once(
    "src/stepnx/preview/snapshot.py",
    "from stepnx.preview.modifiers import EffectiveModifier, StepParam, apply_step_params\n",
    "from stepnx.preview.modifiers import (\n    EffectiveModifier,\n    StepParam,\n    apply_header_step_params,\n)\n",
)
replace_once(
    "src/stepnx/preview/snapshot.py",
    '''        return apply_step_params(\n            self.header_step_params,\n            base,\n            allow_mid=self.profile == "nxa-step5-patched",\n        )\n''',
    '''        return apply_header_step_params(\n            self.header_step_params,\n            self.profile,\n            base,\n        )\n''',
)

# Preview z-order: shafts remain lowest, then every ordinary terminal/note, then
# hold heads. A short high-tick long therefore collapses visually toward its
# head instead of exposing the later tail sprite.
replace_once(
    "src/stepnx/gui/preview_widget.py",
    '''        notes = self._visible_render_events() if visible_notes is None else visible_notes\n        for note in notes:\n''',
    '''        notes = self._visible_render_events() if visible_notes is None else visible_notes\n        # Prime-era charts deliberately use very short high-tick holds as\n        # tap-like ornaments. Preserve chronological order inside each layer,\n        # but draw every head last so a collapsed head/tail pair reads as head.\n        ordered_notes = tuple(note for note in notes if note.note_type != 0x7) + tuple(\n            note for note in notes if note.note_type == 0x7\n        )\n        for note in ordered_notes:\n''',
)

# Authoring timeline uses the same terminal priority. Defer only heads; do not
# reorder bodies/tails/items/taps relative to each other.
replace_once(
    "src/stepnx/gui/timeline_widget.py",
    '''        beat_markers = {marker.row_index: marker for marker in self._layout.beat_markers(visible)}\n        for row_index in range(visible.first_row, visible.last_row):\n''',
    '''        beat_markers = {marker.row_index: marker for marker in self._layout.beat_markers(visible)}\n        deferred_hold_heads: list[tuple[int, float, float, bytes]] = []\n        for row_index in range(visible.first_row, visible.last_row):\n''',
)
replace_once(
    "src/stepnx/gui/timeline_widget.py",
    '''                    if cell.note_type:\n                        self._draw_note(painter, lane, y, segment.row_height, cell.raw)\n\n        painter.setPen(QColor("#303641"))\n''',
    '''                    if cell.note_type:\n                        if cell.note_type == 0x7:\n                            deferred_hold_heads.append(\n                                (lane, y, segment.row_height, cell.raw)\n                            )\n                        else:\n                            self._draw_note(\n                                painter, lane, y, segment.row_height, cell.raw\n                            )\n\n        # Hold heads are the top terminal layer. This matters when BeatSplit is\n        # high enough that head/body/tail artwork overlaps into one tap-sized\n        # silhouette, as in Fiesta 2 EF1299.\n        for lane, y, row_height, raw in deferred_hold_heads:\n            self._draw_note(painter, lane, y, row_height, raw)\n\n        painter.setPen(QColor("#303641"))\n''',
)

# Core runtime regression: legacy profiles consume Header 0 as a direct float,
# while the R!SE dispatcher test remains untouched and continues to verify /4.
test_preview = Path("tests/unit/test_preview.py")
text = test_preview.read_text(encoding="utf-8")
text = text.replace("import unittest\n", "import struct\nimport unittest\n", 1)
insert_anchor = '''class GameplayCommandTests(unittest.TestCase):\n'''
if insert_anchor not in text:
    raise SystemExit("test_preview insertion anchor missing")
header_test = '''class LegacyHeaderSpeedTests(unittest.TestCase):\n    @staticmethod\n    def _f32_bits(value: float) -> int:\n        return struct.unpack("<I", struct.pack("<f", value))[0]\n\n    def test_prime_family_header_zero_is_direct_float_and_overrides_launch_speed(self) -> None:\n        for profile in ("nxa-native", "fiesta2", "prime2", "nxa-step5-patched"):\n            with self.subTest(profile=profile):\n                document = parse_bytes(\n                    make_normal_nx20(),\n                    source="EF1299.NX",\n                    profile=profile,\n                    row_storage="compact",\n                )\n                document = InsertMetadata.from_ints(\n                    document.stable_id, 0, self._f32_bits(4.0)\n                ).apply(document)\n                snapshot = create_preview_snapshot(document)\n                route = resolve_route(snapshot, RoutePolicy.MANUAL)\n                stream = build_event_stream(snapshot, route)\n                session = GameplaySession(\n                    stream,\n                    parse_gameplay_command("").with_speed(9),\n                    autoplay=True,\n                )\n                self.assertEqual(session.selected_speed, 4.0)\n                self.assertEqual(session.runtime_modifier.speed, 4.0)\n\n    def test_prime_family_preserves_non_quarter_header_speed_values(self) -> None:\n        document = parse_bytes(\n            make_normal_nx20(),\n            source="Prime.NX",\n            profile="prime2",\n            row_storage="compact",\n        )\n        document = InsertMetadata.from_ints(\n            document.stable_id, 0, self._f32_bits(4.35)\n        ).apply(document)\n        snapshot = create_preview_snapshot(document)\n        route = resolve_route(snapshot, RoutePolicy.MANUAL)\n        session = GameplaySession(\n            build_event_stream(snapshot, route),\n            parse_gameplay_command("").with_speed(1),\n            autoplay=True,\n        )\n        self.assertAlmostEqual(session.selected_speed, 4.35, places=5)\n\n\n'''
text = text.replace(insert_anchor, header_test + insert_anchor, 1)
test_preview.write_text(text, encoding="utf-8")

# Preview draw-order regression uses the actual group renderer and intercepts
# atlas drawing, proving tail/non-head is emitted before the head.
qt_preview = Path("tests/unit/test_qt_preview.py")
text = qt_preview.read_text(encoding="utf-8")
anchor = '''    def test_dense_long_bodies_stay_in_runtime_but_out_of_render_index(self) -> None:\n'''
if anchor not in text:
    raise SystemExit("qt preview insertion anchor missing")
order_test = '''    def test_collapsed_long_draws_head_after_tail_in_gameplay_preview(self) -> None:\n        widget = self._widget()\n        try:\n            widget.resize(640, 480)\n            source = widget.stream.events[0]\n            head = replace(\n                source,\n                time_ms=1000.0,\n                row_index=100,\n                raw=bytes((0x07, 0x03, source.raw[2], source.raw[3])),\n            )\n            tail = replace(\n                source,\n                time_ms=1001.0,\n                row_index=101,\n                raw=bytes((0x0F, 0x03, source.raw[2], source.raw[3])),\n            )\n            widget._chart_time_ms = 0.0\n            image = QImage(widget.size(), QImage.Format.Format_ARGB32)\n            image.fill(0)\n            painter = QPainter(image)\n            draw_order = []\n            try:\n                with patch.object(\n                    widget,\n                    "_draw_asset",\n                    side_effect=lambda _painter, note, _rect: draw_order.append(\n                        note.note_type\n                    )\n                    or True,\n                ):\n                    widget._draw_note_group(\n                        painter,\n                        widget._geometry(),\n                        3,\n                        visible_notes=(head, tail),\n                    )\n            finally:\n                painter.end()\n            self.assertEqual(draw_order, [0x0F, 0x07])\n        finally:\n            widget.close()\n\n\n'''
text = text.replace(anchor, order_test + anchor, 1)
qt_preview.write_text(text, encoding="utf-8")

# Timeline regression intercepts _draw_note while drawing a real authoring row.
qt_viewport = Path("tests/unit/test_qt_viewport.py")
text = qt_viewport.read_text(encoding="utf-8")
text = text.replace("import unittest\n", "import unittest\nfrom unittest.mock import patch\n", 1)
text = text.replace(
    "from tests.fixture_factory import make_large_lightmap\n",
    "from tests.fixture_factory import make_large_lightmap, make_normal_nx20\n",
    1,
)
anchor = '''    def test_hold_terminals_meet_their_per_column_silhouettes(self) -> None:\n'''
if anchor not in text:
    raise SystemExit("qt viewport insertion anchor missing")
editor_test = '''    def test_collapsed_long_draws_head_as_top_terminal_in_editor(self) -> None:\n        document = parse_bytes(\n            make_normal_nx20(), source="short-long.NX", row_storage="rich"\n        )\n        split = document.splits[0]\n        block = split.blocks[0]\n        row = block.rows[0]\n        cells = list(row.cells)\n        cells[0] = replace(cells[0], raw=bytes((0x07, 0x03, 0, 0)))\n        cells[3] = replace(cells[3], raw=bytes((0x0F, 0x03, 0, 0)))\n        row = replace(row, cells=tuple(cells))\n        block = replace(block, rows=(row,) + tuple(block.rows[1:]))\n        document = replace(document, splits=(replace(split, blocks=(block,)),))\n        widget = TimelineWidget(create_authoring_snapshot(document))\n        try:\n            widget.resize(640, 360)\n            visible = widget._layout.visible_segments(\n                0.0, float(widget.viewport().height()), overscan_rows=2\n            )[0]\n            image = QImage(widget.viewport().size(), QImage.Format.Format_ARGB32)\n            image.fill(0)\n            painter = QPainter(image)\n            order = []\n            original = widget._draw_note\n\n            def record(painter_arg, lane, y, row_height, raw):\n                order.append(raw[0] & 0x0F)\n                return original(painter_arg, lane, y, row_height, raw)\n\n            try:\n                with patch.object(widget, "_draw_note", side_effect=record):\n                    widget._draw_segment(painter, visible)\n            finally:\n                painter.end()\n            self.assertIn(0x0F, order)\n            self.assertEqual(order[-1], 0x07)\n            self.assertLess(order.index(0x0F), order.index(0x07))\n        finally:\n            widget.close()\n\n\n'''
text = text.replace(anchor, editor_test + anchor, 1)
qt_viewport.write_text(text, encoding="utf-8")

# Record both fixes and keep the performance finding visible for the next pass.
handoff = Path("docs/RISE_RUNTIME_PARITY_HANDOFF.md")
text = handoff.read_text(encoding="utf-8")
addition = '''\n- Prime/Fiesta/NXA Header Metadata 0 is an already-final IEEE-754 speed multiplier, not R!SE's quarter-normalized Header 0. EF1299 stores `4.0` (`0x40800000`), and the local corpora contain non-quarter values such as `2.80`, `3.66`, `4.35`, and `5.50`; legacy preview launch must therefore use the float directly before downstream Header 1111 multiplication.\n- Hold-terminal z-order is intentionally head-last in both authoring and gameplay renderers. Dense high-BeatSplit charts use very short holds as tap-like visuals; when head/tail artwork overlaps, the head must remain the visible top terminal.\n- EF1299 paint cost is now stable near the user's ~2 ms after body and shaft culling. Remaining temporary ~20 fps drops in BeatSplit/TickCount-128 sections occur with paint staying low and therefore point to GameplaySession judgment/tick processing rather than anticipatory rendering.\n'''
if "Prime/Fiesta/NXA Header Metadata 0 is an already-final" not in text:
    handoff.write_text(text.rstrip() + "\n" + addition, encoding="utf-8")
