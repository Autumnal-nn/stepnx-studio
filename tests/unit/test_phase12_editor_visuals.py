from __future__ import annotations

import unittest
from types import SimpleNamespace

from PySide6.QtCore import QRectF

from stepnx.gui.phase12_editor_note_visuals import (
    _effective_hold_raw,
    _hold_visual_contexts,
    _render_target_rect,
    _visibility_alpha,
)


class Phase12EditorLongVisualTests(unittest.TestCase):
    @staticmethod
    def _row(raw: bytes):
        return SimpleNamespace(cells=(SimpleNamespace(raw=raw),))

    def test_hold_head_visual_flags_project_to_body_and_tail_without_rewriting_type(self) -> None:
        rows = (
            self._row(bytes.fromhex("67 01 00 00")),  # Hidden + Appear Hold Head.
            self._row(bytes.fromhex("4B 03 00 00")),  # Neutral Hold Body.
            self._row(bytes.fromhex("4F 03 00 00")),  # Neutral Hold Tail.
        )
        segment = SimpleNamespace(
            block=SimpleNamespace(rows=rows),
            row_height=48.0,
            y_for_row=lambda index: index * 48.0,
        )
        geometry = SimpleNamespace(
            note_rect=lambda lane, y, row_height: (2.0, y + 2.0, 44.0, 44.0)
        )
        widget = SimpleNamespace(
            _snapshot=SimpleNamespace(columns=1),
            _geometry=geometry,
        )

        contexts = _hold_visual_contexts(widget, segment)
        body_context = contexts[(0, 48.0)]
        body = _effective_hold_raw(rows[1].cells[0].raw, body_context)
        tail = _effective_hold_raw(rows[2].cells[0].raw, contexts[(0, 96.0)])

        self.assertEqual(body[0] & 0x0F, 0xB)
        self.assertEqual(tail[0] & 0x0F, 0xF)
        self.assertEqual(body[0] & 0x60, 0x60)
        self.assertEqual(tail[0] & 0x60, 0x60)
        self.assertEqual(body[1] & 0x07, 1)
        self.assertEqual(tail[1] & 0x07, 1)

    def test_visible_head_does_not_hide_explicit_body_decorations(self) -> None:
        rows = (
            self._row(bytes.fromhex("47 03 00 00")),
            self._row(bytes.fromhex("6B 00 00 00")),
            self._row(bytes.fromhex("4F 03 00 00")),
        )
        segment = SimpleNamespace(
            block=SimpleNamespace(rows=rows),
            row_height=48.0,
            y_for_row=lambda index: index * 48.0,
        )
        widget = SimpleNamespace(
            _snapshot=SimpleNamespace(columns=1),
            _geometry=SimpleNamespace(
                note_rect=lambda lane, y, row_height: (2.0, y + 2.0, 44.0, 44.0)
            ),
        )
        self.assertEqual(_hold_visual_contexts(widget, segment), {})

    def test_masked_hold_body_uses_row_span_instead_of_square_note_rect(self) -> None:
        square = QRectF(2.0, 50.0, 44.0, 44.0)
        target = _render_target_rect(0xB, square, 48.0, 48.0)
        self.assertEqual(target.top(), 48.0)
        self.assertEqual(target.height(), 48.0)
        self.assertEqual(target.width(), 44.0)

        terminal = _render_target_rect(0x7, square, 48.0, 48.0)
        self.assertEqual(terminal, square)

    def test_appear_and_vanish_cover_full_zero_to_one_alpha_range(self) -> None:
        self.assertEqual(_visibility_alpha(1, 0.0), 255)
        self.assertEqual(_visibility_alpha(1, 1.0), 0)
        self.assertEqual(_visibility_alpha(2, 0.0), 0)
        self.assertEqual(_visibility_alpha(2, 1.0), 255)


if __name__ == "__main__":
    unittest.main()
