from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import QApplication, QMainWindow

    from stepnx.authoring.selection import CellSelection, CellTarget
    from stepnx.authoring.snapshot import create_authoring_snapshot
    from stepnx.authoring.timeline import TimelineGeometry, TimelineLayout
    from stepnx.codecs.nx20 import parse_bytes
    from stepnx.gui.phase11_ui_polish import (
        _install_shortcuts,
        _move_waveform_to_audio,
        _selection_outline_rects,
        _selection_rect,
        _timing_line_cell_hit,
        _timing_line_row_hit,
    )
    from stepnx.gui.phase11_waveform_precision import _install_timing_line_note_alignment
    from tests.fixture_factory import make_normal_nx20
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class Phase11UiPolishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _layout(self, row_height: float = 48.0):
        document = parse_bytes(make_normal_nx20(), row_storage="rich")
        snapshot = create_authoring_snapshot(document)
        geometry = TimelineGeometry(row_height=row_height)
        return TimelineLayout(snapshot, geometry), geometry

    def test_selection_is_centered_on_note_timing_line_even_for_empty_cell(self) -> None:
        _install_timing_line_note_alignment()
        geometry = TimelineGeometry()
        row_y = 120.0
        rect = _selection_rect(geometry, 2, row_y, 72.0)
        self.assertAlmostEqual(rect.center().y(), row_y)
        self.assertAlmostEqual(rect.width(), geometry.lane_width - 2.0)
        self.assertAlmostEqual(rect.height(), geometry.lane_width - 2.0)

    def test_shift_rectangle_draws_one_external_outline_at_dense_zoom(self) -> None:
        _install_timing_line_note_alignment()
        layout, geometry = self._layout(row_height=8.0)
        segment = layout.segments[0]
        count = min(4, segment.block.row_count)
        self.assertGreaterEqual(count, 2)
        targets = frozenset(
            CellTarget(segment.block.rows[index].stable_id, lane)
            for index in range(count)
            for lane in (1, 2)
        )
        outlines = _selection_outline_rects(
            geometry,
            segment,
            CellSelection(targets, next(iter(targets))),
        )
        self.assertEqual(len(outlines), 1)
        outline = outlines[0]
        first = _selection_rect(
            geometry, 1, segment.y_for_row(0), segment.row_height
        )
        last = _selection_rect(
            geometry, 2, segment.y_for_row(count - 1), segment.row_height
        )
        self.assertAlmostEqual(outline.left(), first.left())
        self.assertAlmostEqual(outline.right(), last.right())
        self.assertAlmostEqual(outline.top(), first.top())
        self.assertAlmostEqual(outline.bottom(), last.bottom())

    def test_sparse_ctrl_selection_does_not_claim_unselected_gap(self) -> None:
        _install_timing_line_note_alignment()
        layout, geometry = self._layout(row_height=8.0)
        segment = layout.segments[0]
        self.assertGreaterEqual(segment.block.row_count, 3)
        targets = frozenset(
            (
                CellTarget(segment.block.rows[0].stable_id, 1),
                CellTarget(segment.block.rows[2].stable_id, 1),
            )
        )
        outlines = _selection_outline_rects(
            geometry,
            segment,
            CellSelection(targets, next(iter(targets))),
        )
        self.assertEqual(len(outlines), 2)

    def test_mouse_hit_is_partitioned_around_timing_line_not_legacy_cell_top(self) -> None:
        layout, geometry = self._layout()
        segment = layout.segments[0]
        self.assertGreaterEqual(segment.block.row_count, 2)
        second_line = segment.y_for_row(1)

        # Twenty pixels above row 1 is still inside the upper half of a
        # 44-pixel note/selection centered on that timing line. Legacy
        # row_at_y() resolves this point to row 0; Phase 11 must resolve row 1.
        hit = _timing_line_row_hit(layout, second_line - 20.0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1], 1)

        # Cross the exact midpoint between row 0 and row 1 and ownership moves
        # back to row 0, so empty cells have the same unambiguous hit regions.
        hit = _timing_line_row_hit(layout, second_line - 25.0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit[1], 0)

        lane_x = geometry.ruler_width + geometry.lane_width * 2.5
        cell_hit = _timing_line_cell_hit(layout, lane_x, second_line - 20.0)
        self.assertIsNotNone(cell_hit)
        self.assertEqual(cell_hit[1:], (1, 2))

    def test_waveform_toggle_moves_from_lonely_view_menu_to_audio(self) -> None:
        window = QMainWindow()
        view_menu = window.menuBar().addMenu("&View")
        audio_menu = window.menuBar().addMenu("&Audio")
        audio_menu.addAction("Select audio…")
        separator = audio_menu.addSeparator()
        waveform = QAction("Show waveform", window)
        waveform.setCheckable(True)
        view_menu.addAction(waveform)
        window.phase11_waveform_action = waveform

        _move_waveform_to_audio(window)

        self.assertIn(waveform, audio_menu.actions())
        self.assertLess(audio_menu.actions().index(waveform), audio_menu.actions().index(separator))
        self.assertEqual(waveform.text(), "Show Waveform")
        menu_names = [
            action.text().replace("&", "") for action in window.menuBar().actions()
        ]
        self.assertNotIn("View", menu_names)

    def test_requested_folder_and_audio_shortcuts_are_installed(self) -> None:
        window = QMainWindow()
        file_menu = window.menuBar().addMenu("&File")
        open_action = file_menu.addAction("Open folder…")
        audio_menu = window.menuBar().addMenu("&Audio")
        select_audio = audio_menu.addAction("Select audio…")

        _install_shortcuts(window)

        self.assertEqual(open_action.shortcut(), QKeySequence("Ctrl+O"))
        close_action = next(
            action for action in file_menu.actions() if action.text() == "Close folder"
        )
        self.assertEqual(close_action.shortcut(), QKeySequence("Ctrl+W"))
        self.assertEqual(select_audio.shortcut(), QKeySequence("Ctrl+3"))


if __name__ == "__main__":
    unittest.main()
