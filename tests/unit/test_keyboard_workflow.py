from __future__ import annotations

import os
import unittest
from dataclasses import replace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QAction, QKeyEvent, QKeySequence, QShortcut
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QMainWindow,
        QTableWidget,
        QTabWidget,
        QTreeWidget,
        QTreeWidgetItem,
    )

    from stepnx.authoring.snapshot import create_authoring_snapshot
    from stepnx.codecs.nx20 import parse_bytes
    from stepnx.core.model import CompactRows, EmptyRow
    from stepnx.core.scalars import RawF32, RawU8, RawU32
    from stepnx.gui.keyboard_workflow import (
        KeyboardCursor,
        _TreeKeyboardFilter,
        _activate_current_tool,
        _cursor,
        _handle_timeline_key,
        _install_pane_shortcuts,
        _install_save_shortcuts,
        _move_cursor,
        _scope_selection_shortcuts,
        _scope_transport_shortcut,
        _select_function,
        _select_tool,
        _selection_to_cursor,
    )
    from stepnx.gui.timeline_widget import TimelineWidget
    from tests.fixture_factory import make_normal_nx20
except ImportError as exc:
    QApplication = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(QApplication is None, f"Qt runtime unavailable: {QT_UNAVAILABLE}")
class KeyboardWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def _timeline(self, parent=None) -> TimelineWidget:
        document = parse_bytes(make_normal_nx20(), row_storage="compact")
        return TimelineWidget(create_authoring_snapshot(document), parent)

    def _two_segment_timeline(self, parent=None) -> TimelineWidget:
        document = parse_bytes(make_normal_nx20(), row_storage="compact")
        first_split = document.splits[0]
        first_block = first_split.blocks[0]
        next_id = document.next_stable_id
        second_rows = tuple(
            EmptyRow(next_id + index, b"\x80\x00\x00\x00", None)
            for index in range(8)
        )
        next_id += len(second_rows)
        second_block = replace(
            first_block,
            stable_id=next_id,
            start_time=RawF32.from_value(1000.0),
            beat_split=RawU8.from_value(32),
            row_count=RawU32.from_value(len(second_rows)),
            rows=second_rows,
            span=None,
        )
        next_id += 1
        second_split = replace(
            first_split,
            stable_id=next_id,
            blocks=(second_block,),
            block_count=RawU32.from_value(1),
            span=None,
        )
        next_id += 1
        document = replace(
            document,
            splits=(first_split, second_split),
            split_count=RawU32.from_value(2),
            next_stable_id=next_id,
        )
        return TimelineWidget(create_authoring_snapshot(document), parent)

    def test_arrow_navigation_and_shift_extension_use_stable_cell_selection(self) -> None:
        widget = self._timeline()
        segment = widget._layout.segments[0]
        self.assertGreaterEqual(segment.block.row_count, 2)
        self.assertGreaterEqual(widget.snapshot.columns, 3)
        first_row = int(segment.block.rows._row_ids[0])
        widget.set_selected_cell(first_row, 1)

        cursor = _cursor(widget)
        self.assertEqual(cursor, KeyboardCursor(0, 0, 1))
        moved = _move_cursor(widget, cursor, Qt.Key.Key_Right, Qt.NoModifier)
        widget.set_selection(_selection_to_cursor(widget, moved, extend=False))
        self.assertEqual(widget.selection.anchor.lane, 2)

        moved_down = _move_cursor(widget, moved, Qt.Key.Key_Down, Qt.ShiftModifier)
        extended = _selection_to_cursor(widget, moved_down, extend=True)
        self.assertEqual(len(extended.targets), 2)
        self.assertEqual({target.lane for target in extended.targets}, {2})
        self.assertEqual(extended.anchor, widget.selection.anchor)

    def test_home_end_and_control_vertical_navigation_have_explicit_meaning(self) -> None:
        widget = self._timeline()
        segment = widget._layout.segments[0]
        cursor = KeyboardCursor(0, min(1, segment.block.row_count - 1), 2)
        self.assertEqual(
            _move_cursor(widget, cursor, Qt.Key.Key_Home, Qt.NoModifier).lane,
            0,
        )
        self.assertEqual(
            _move_cursor(widget, cursor, Qt.Key.Key_End, Qt.NoModifier).lane,
            widget.snapshot.columns - 1,
        )
        self.assertEqual(
            _move_cursor(widget, cursor, Qt.Key.Key_Home, Qt.ControlModifier).row_index,
            0,
        )
        self.assertEqual(
            _move_cursor(widget, cursor, Qt.Key.Key_End, Qt.ControlModifier).row_index,
            segment.block.row_count - 1,
        )

        first = KeyboardCursor(0, 0, 0)
        self.assertEqual(
            _move_cursor(widget, first, Qt.Key.Key_Up, Qt.ControlModifier),
            first,
        )
        last_index = len(widget._layout.segments) - 1
        last_segment = widget._layout.segments[last_index]
        last = KeyboardCursor(last_index, last_segment.block.row_count - 1, 0)
        self.assertEqual(
            _move_cursor(widget, last, Qt.Key.Key_Down, Qt.ControlModifier),
            last,
        )

    def test_timeline_key_handler_keeps_a_moving_shift_edge(self) -> None:
        window = QMainWindow()
        widget = self._timeline(window)
        window.setCentralWidget(widget)
        segment = widget._layout.segments[0]
        first_row = int(segment.block.rows._row_ids[0])
        widget.set_selected_cell(first_row, 0)

        shift_right = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.ShiftModifier
        )
        self.assertTrue(_handle_timeline_key(widget, shift_right))
        self.assertEqual(len(widget.selection.targets), 2)
        self.assertTrue(_handle_timeline_key(widget, shift_right))
        self.assertEqual(len(widget.selection.targets), 3)

        shift_down = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.ShiftModifier
        )
        self.assertTrue(_handle_timeline_key(widget, shift_down))
        self.assertEqual(len(widget.selection.targets), 6)
        self.assertEqual({target.lane for target in widget.selection.targets}, {0, 1, 2})

    def test_shift_selection_crosses_segment_boundary_by_encoded_row_count(self) -> None:
        window = QMainWindow()
        widget = self._two_segment_timeline(window)
        window.setCentralWidget(widget)
        first, second = widget._layout.segments
        last_first = int(first.block.rows._row_ids[-1])
        widget.set_selected_cell(last_first, 1)

        down = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.ShiftModifier)
        self.assertTrue(_handle_timeline_key(widget, down))
        selected_rows = {target.row_id for target in widget.selection.targets}
        self.assertEqual(
            selected_rows,
            {last_first, int(second.block.rows[0].stable_id)},
        )
        self.assertEqual(len(widget.selection.targets), 2)
        self.assertEqual(int(first.block.beat_split), 4)
        self.assertEqual(int(second.block.beat_split), 32)

    def test_compact_keyboard_selection_never_iterates_the_row_table(self) -> None:
        widget = self._timeline()
        segment = widget._layout.segments[0]
        first_row = int(segment.block.rows._row_ids[0])
        widget.set_selected_cell(first_row, 0)

        with mock.patch.object(
            CompactRows,
            "__iter__",
            side_effect=AssertionError("keyboard navigation materialized CompactRows"),
        ):
            cursor = _cursor(widget)
            moved = _move_cursor(widget, cursor, Qt.Key.Key_Down, Qt.NoModifier)
            selection = _selection_to_cursor(widget, moved, extend=True)

        self.assertEqual(len(selection.targets), 2)

    def test_number_keys_choose_tools_only_through_the_editor_combo(self) -> None:
        window = QMainWindow()
        combo = QComboBox(window)
        for label in (
            "Toggle",
            "Select",
            "Roll",
            "Tap",
            "Hold head",
            "Hold body",
            "Hold tail",
            "Item",
            "Division",
            "Erase",
        ):
            combo.addItem(label)
        window.tool_combo = combo

        self.assertTrue(_select_tool(window, Qt.Key.Key_3))
        self.assertEqual(combo.currentText(), "Roll")
        self.assertTrue(_select_tool(window, Qt.Key.Key_0))
        self.assertEqual(combo.currentText(), "Erase")

    def test_h_g_n_choose_note_function_without_touching_other_widgets(self) -> None:
        window = QMainWindow()
        combo = QComboBox(window)
        for label in ("Normal", "Bonus / Hidden (H)", "Ghost (G)"):
            combo.addItem(label)
        window.function_combo = combo

        self.assertTrue(_select_function(window, Qt.Key.Key_H))
        self.assertEqual(combo.currentText(), "Bonus / Hidden (H)")
        self.assertTrue(_select_function(window, Qt.Key.Key_G))
        self.assertEqual(combo.currentText(), "Ghost (G)")
        self.assertTrue(_select_function(window, Qt.Key.Key_N))
        self.assertEqual(combo.currentText(), "Normal")

    def test_enter_toggle_uses_toggle_callback_instead_of_bulk_tap_apply(self) -> None:
        window = QMainWindow()
        widget = self._timeline(window)
        window.setCentralWidget(widget)
        segment = widget._layout.segments[0]
        widget.set_selected_cell(int(segment.block.rows._row_ids[0]), 0)
        combo = QComboBox(window)
        combo.addItem("Toggle")
        window.tool_combo = combo
        toggled = []
        applied = []
        window._stepnx_toggle_selection = lambda current: toggled.append(current) or True
        window._apply_tool_to_selection = lambda: applied.append(True)

        self.assertTrue(_activate_current_tool(window, widget))
        self.assertEqual(toggled, [widget])
        self.assertEqual(applied, [])

    def test_chart_edit_shortcuts_are_removed_from_window_scope(self) -> None:
        window = QMainWindow()
        names = (
            "apply_selection_action",
            "clear_selection_notes_action",
            "clear_selection_action",
            "copy_selection_action",
            "cut_selection_action",
            "paste_selection_action",
            "flip_horizontal_selection_action",
            "flip_vertical_selection_action",
            "mirror_selection_action",
        )
        for name in names:
            action = QAction(name, window)
            action.setShortcut(QKeySequence("X"))
            setattr(window, name, action)

        _scope_selection_shortcuts(window)

        for name in names:
            self.assertTrue(getattr(window, name).shortcut().isEmpty())

    def test_space_transport_is_removed_from_window_scope(self) -> None:
        window = QMainWindow()
        shortcut = QShortcut(QKeySequence("Space"), window)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        window.phase10_space_shortcut = shortcut

        _scope_transport_shortcut(window)

        self.assertFalse(shortcut.isEnabled())
        self.assertTrue(shortcut.key().isEmpty())

    def test_save_all_accepts_standard_ctrl_s_and_keeps_legacy_shortcut(self) -> None:
        window = QMainWindow()
        window.save_action = QAction("Save All", window)

        _install_save_shortcuts(window)

        self.assertEqual(
            window.save_action.shortcuts(),
            [QKeySequence("Ctrl+S"), QKeySequence("Ctrl+Shift+S")],
        )

    def test_alt_number_shortcuts_cover_panes_without_overriding_native_tab_keys(self) -> None:
        window = QMainWindow()
        window.tree = QTreeWidget(window)
        window.tabs = QTabWidget(window)
        timeline = self._timeline(window.tabs)
        window.tabs.addTab(timeline, "Chart")
        window.side_tabs = QTabWidget(window)
        window.diagnostics = QTreeWidget(window.side_tabs)
        window.inspector = QTableWidget(window.side_tabs)
        window.routes = QTreeWidget(window.side_tabs)
        window.side_tabs.addTab(window.diagnostics, "Diagnostics")
        window.side_tabs.addTab(window.inspector, "Inspector")
        window.side_tabs.addTab(window.routes, "Routes")

        _install_pane_shortcuts(window)

        self.assertEqual(
            [shortcut.key() for shortcut in window.keyboard_pane_shortcuts],
            [
                QKeySequence("Alt+1"),
                QKeySequence("Alt+2"),
                QKeySequence("Alt+3"),
                QKeySequence("Alt+4"),
                QKeySequence("Alt+5"),
            ],
        )
        self.assertTrue(
            all(
                shortcut.context() == Qt.ShortcutContext.WindowShortcut
                for shortcut in window.keyboard_pane_shortcuts
            )
        )
        self.assertNotIn(
            QKeySequence("Ctrl+PageUp"),
            [shortcut.key() for shortcut in window.keyboard_pane_shortcuts],
        )
        self.assertNotIn(
            QKeySequence("Ctrl+PageDown"),
            [shortcut.key() for shortcut in window.keyboard_pane_shortcuts],
        )

    def test_tree_enter_metadata_and_structure_keys_call_existing_actions(self) -> None:
        class Window(QMainWindow):
            def __init__(self):
                super().__init__()
                self.activated = 0

            def _tree_activated(self, item, column):
                self.activated += 1

        window = Window()
        tree = QTreeWidget(window)
        item = QTreeWidgetItem(tree, ["Block"])
        item.setData(0, Qt.ItemDataRole.UserRole, ("block", 0, 1, 2))
        tree.setCurrentItem(item)
        inserted = []
        metadata = []
        window.insert_block_action = QAction("Insert Block", window)
        window.insert_block_action.triggered.connect(lambda: inserted.append("block"))
        window.edit_metadata_action = QAction("Edit metadata", window)
        window.edit_metadata_action.triggered.connect(lambda: metadata.append("metadata"))
        filter_ = _TreeKeyboardFilter(window)

        enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.NoModifier)
        self.assertTrue(filter_.eventFilter(tree, enter))
        self.assertEqual(window.activated, 1)

        control_enter = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.ControlModifier,
        )
        self.assertTrue(filter_.eventFilter(tree, control_enter))
        self.assertEqual(metadata, ["metadata"])

        insert = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Insert, Qt.NoModifier)
        self.assertTrue(filter_.eventFilter(tree, insert))
        self.assertEqual(inserted, ["block"])

    def test_routes_enter_is_keyboard_equivalent_of_activation(self) -> None:
        class Window(QMainWindow):
            def __init__(self):
                super().__init__()
                self.activated = 0

            def _route_activated(self, item, column):
                self.activated += 1

        window = Window()
        routes = QTreeWidget(window)
        item = QTreeWidgetItem(routes, ["Route"])
        routes.setCurrentItem(item)
        filter_ = _TreeKeyboardFilter(window, routes=True)
        enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.NoModifier)

        self.assertTrue(filter_.eventFilter(routes, enter))
        self.assertEqual(window.activated, 1)


if __name__ == "__main__":
    unittest.main()
