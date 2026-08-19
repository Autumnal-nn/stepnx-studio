from __future__ import annotations

import argparse
import secrets
import sys
from dataclasses import replace
from pathlib import Path


def _qt_import_error(exc: ImportError) -> int:
    print(
        "StepNX Studio's desktop UI requires the optional GUI dependencies. "
        "Install the project with: pip install -e '.[gui]'\n"
        f"Qt import failed: {exc}",
        file=sys.stderr,
    )
    return 2


def _run(folder: Path | None, profile: str = "nxa-native") -> int:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QActionGroup
        from PySide6.QtWidgets import (
            QApplication,
            QCheckBox,
            QComboBox,
            QDialog,
            QDoubleSpinBox,
            QFileDialog,
            QInputDialog,
            QLabel,
            QMainWindow,
            QMenu,
            QMessageBox,
            QPushButton,
            QSlider,
            QSpinBox,
            QSplitter,
            QTableWidget,
            QTableWidgetItem,
            QTabWidget,
            QToolButton,
            QTreeWidget,
            QTreeWidgetItem,
        )
    except ImportError as exc:
        return _qt_import_error(exc)

    from stepnx.authoring import (
        AudioAlignment,
        BlockTimingValues,
        CellSelection,
        MetadataBatchMode,
        MetronomeClock,
        NoteClipboard,
        NoteFunction,
        NoteMetronomeClock,
        NoteTool,
        NoteVisibility,
        ReplaceMetadataCollection,
        SetTrailerStringSameSize,
        ShiftBlockStartTimes,
        StructureEditError,
        StructureTarget,
        TimingProjection,
        WaveformError,
        copy_selection,
        create_authoring_snapshot,
        insert_empty_block_after,
        insert_empty_split_after,
        load_noteskin_pack,
        load_pcm_wav_waveform,
        estimate_bpm,
        load_visual_pack,
        metadata_drafts,
        metadata_owner,
        mirror_selection,
        modify_selection_notes,
        move_block,
        move_split,
        note_tool_raw,
        paste_clipboard,
        plan_batch_header_metadata,
        plan_batch_shift_start_times,
        project_brain_shower,
        project_routes,
        project_trailer_strings,
        remove_block,
        remove_split,
        replace_selection_type,
        set_selection_raw,
        validate_authoring,
    )
    from stepnx.authoring.glyphs import VisualPackError
    from stepnx.authoring.noteskin import NoteskinPackError
    from stepnx.core.commands import CommandStack, SetNoteAt
    from stepnx.core.diff import diff_documents
    from stepnx.core.errors import ModelInvariantError
    from stepnx.core.model import EmptyRow, LightmapRow, PackedNoteRow
    from stepnx.core.profiles import MetadataScope, metadata_definition
    from stepnx.core.validation import Severity
    from stepnx.gui.audio_transport import AudioTransport
    from stepnx.gui.metadata_dialog import MetadataCollectionDialog
    from stepnx.gui.preview_dialog import (
        GameplayInitializationDialog,
        PreviewChartChoice,
    )
    from stepnx.gui.preview_widget import GameplayPreviewWidget
    from stepnx.gui.timeline_widget import TimelineWidget
    from stepnx.gui.timing_dialog import BlockTimingDialog
    from stepnx.preview import (
        RoutePolicy,
        build_event_stream,
        create_preview_snapshot,
        parse_gameplay_command,
        resolve_route,
    )
    from stepnx.resources import bundled_metronome_path, bundled_noteskin_root
    from stepnx.workspace import (
        WorkspaceError,
        compare_mirror,
        execute_save_plan,
        open_folder,
        plan_mirror_export,
        plan_save_all,
    )

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("StepNX Studio")
            self.resize(1440, 900)
            self.workspace = None
            self.pack = None
            self.noteskin = None
            self.waveform = None
            self.audio_alignment = AudioAlignment()
            self.metronome_clock = None
            self.note_metronome_clock = None
            self.last_metronome_beat = None
            self.audio_playing = False
            self.metronome_path: Path | None = None
            self.note_clipboard: NoteClipboard | None = None
            self.audio_transport = AudioTransport(self)
            self.audio_transport.positionChanged.connect(self._audio_position_changed)
            self.audio_transport.durationChanged.connect(self._audio_duration_changed)
            self.audio_transport.playbackChanged.connect(self._audio_playback_changed)
            self.audio_transport.errorOccurred.connect(
                lambda message: self.statusBar().showMessage(
                    f"Audio error: {message}", 8000
                )
            )
            self.sessions: dict[int, CommandStack] = {}
            self.baselines = {}
            self.widget_documents: dict[TimelineWidget, int] = {}
            self.preview_snapshots = {}
            self.gesture_keys: dict[TimelineWidget, object] = {}
            self.tree = QTreeWidget()
            self.tree.setHeaderLabels(["Workspace", "Details"])
            self.tree.itemDoubleClicked.connect(self._tree_activated)
            self.tree.currentItemChanged.connect(self._refresh_structure_actions)
            self.tabs = QTabWidget()
            self.tabs.setTabsClosable(True)
            self.tabs.tabCloseRequested.connect(self.tabs.removeTab)
            self.tabs.currentChanged.connect(self._refresh_edit_actions)
            self.tabs.currentChanged.connect(self._active_tab_changed)
            self.side_tabs = QTabWidget()
            self.diagnostics = QTreeWidget()
            self.diagnostics.setHeaderLabels(["Severity", "Code", "Path", "Message"])
            self.inspector = QTableWidget(0, 4)
            self.inspector.setHorizontalHeaderLabels(
                ["Scope / field", "ID", "Value", "Raw"]
            )
            self.routes = QTreeWidget()
            self.routes.setHeaderLabels(
                ["Route", "Selection", "Conditions", "Triggers"]
            )
            self.routes.itemDoubleClicked.connect(self._route_activated)
            self.side_tabs.addTab(self.diagnostics, "Diagnostics")
            self.side_tabs.addTab(self.inspector, "Inspector")
            self.side_tabs.addTab(self.routes, "Routes")
            splitter = QSplitter()
            splitter.addWidget(self.tree)
            splitter.addWidget(self.tabs)
            splitter.addWidget(self.side_tabs)
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.setStretchFactor(2, 0)
            self.setCentralWidget(splitter)

            file_menu = self.menuBar().addMenu("&File")
            file_menu.addAction("Open folder…", self._choose_folder)
            self.save_action = file_menu.addAction("Save All…", self._save_all)
            self.save_action.setShortcut("Ctrl+Shift+S")
            file_menu.addAction("Compare / export NFO mirror…", self._export_nfo_mirror)
            file_menu.addSeparator()
            file_menu.addAction("Load local visual pack…", self._choose_pack)
            file_menu.addAction("Load local noteskin atlases…", self._choose_noteskin)
            self.settings_menu = file_menu.addMenu("Settings")
            profile_menu = self.settings_menu.addMenu("Engine profile")
            self.profile_actions = {}
            profile_group = QActionGroup(self)
            profile_group.setExclusive(True)
            for label, value in (
                ("NXA native", "nxa-native"),
                ("Fiesta 2", "fiesta2"),
                ("Prime 2", "prime2"),
                ("NXA Step5 patched", "nxa-step5-patched"),
            ):
                action = profile_menu.addAction(label)
                action.setCheckable(True)
                action.setData(value)
                action.setChecked(value == profile)
                profile_group.addAction(action)
                self.profile_actions[value] = action
            profile_menu.setToolTipsVisible(True)
            profile_menu.setToolTip(
                "Engine semantics affect labels and validation; choose before opening a folder."
            )
            snap_menu = self.settings_menu.addMenu("Snap")
            self.snap_actions = {}
            snap_group = QActionGroup(self)
            snap_group.setExclusive(True)
            for label, beats in (
                ("Off", 0.0),
                ("1 beat", 1.0),
                ("1/2 beat", 0.5),
                ("1/4 beat", 0.25),
                ("1/8 beat", 0.125),
            ):
                action = snap_menu.addAction(label)
                action.setCheckable(True)
                action.setData(beats)
                action.setChecked(beats == 0.0)
                action.triggered.connect(self._snap_changed)
                snap_group.addAction(action)
                self.snap_actions[beats] = action
            file_menu.addSeparator()
            file_menu.addAction("Exit", self.close)
            edit_menu = self.menuBar().addMenu("&Edit")
            self.undo_action = edit_menu.addAction("Undo", self._undo)
            self.undo_action.setShortcut("Ctrl+Z")
            self.redo_action = edit_menu.addAction("Redo", self._redo)
            self.redo_action.setShortcut("Ctrl+Y")
            self.advanced_split_timing_action = edit_menu.addAction(
                "Show advanced Split timing"
            )
            self.advanced_split_timing_action.setCheckable(True)
            edit_menu.addSeparator()
            self.apply_selection_action = edit_menu.addAction(
                "Apply current tool to selection", self._apply_tool_to_selection
            )
            self.apply_selection_action.setShortcut("Ctrl+Enter")
            self.clear_selection_notes_action = edit_menu.addAction(
                "Erase selected notes", self._erase_selected_notes
            )
            self.clear_selection_notes_action.setShortcut("Delete")
            self.mirror_selection_action = edit_menu.addAction(
                "Mirror selected notes", self._mirror_selected_notes
            )
            self.mirror_selection_action.setShortcut("Ctrl+M")
            self.clear_selection_action = edit_menu.addAction(
                "Clear selection", self._clear_selection
            )
            self.clear_selection_action.setShortcut("Escape")
            self.copy_selection_action = edit_menu.addAction(
                "Copy selected notes", self._copy_selected_notes
            )
            self.copy_selection_action.setShortcut("Ctrl+C")
            self.paste_selection_action = edit_menu.addAction(
                "Paste notes at selection anchor", self._paste_selected_notes
            )
            self.paste_selection_action.setShortcut("Ctrl+V")
            self.replace_selection_action = edit_menu.addAction(
                "Replace selected note type…", self._replace_selected_type
            )
            self.structure_menu = edit_menu.addMenu("Structure")
            self.insert_split_action = self.structure_menu.addAction(
                "Insert empty Split after", self._insert_split
            )
            self.remove_split_action = self.structure_menu.addAction(
                "Remove Split…", self._remove_split
            )
            self.move_split_up_action = self.structure_menu.addAction(
                "Move Split up", lambda: self._move_split(-1)
            )
            self.move_split_down_action = self.structure_menu.addAction(
                "Move Split down", lambda: self._move_split(1)
            )
            self.structure_menu.addSeparator()
            self.insert_block_action = self.structure_menu.addAction(
                "Insert empty Block after", self._insert_block
            )
            self.remove_block_action = self.structure_menu.addAction(
                "Remove Block…", self._remove_block
            )
            self.move_block_up_action = self.structure_menu.addAction(
                "Move Block up", lambda: self._move_block(-1)
            )
            self.move_block_down_action = self.structure_menu.addAction(
                "Move Block down", lambda: self._move_block(1)
            )
            self.structure_menu.addSeparator()
            self.edit_timing_action = self.structure_menu.addAction(
                "Edit Block timing…", self._edit_block_timing
            )
            self.shift_start_times_action = self.structure_menu.addAction(
                "Shift all Start Times…", self._shift_start_times
            )
            self.metadata_menu = edit_menu.addMenu("Metadata")
            self.edit_metadata_action = self.metadata_menu.addAction(
                "Edit selected scope…", self._edit_metadata
            )
            self.edit_brain_action = self.metadata_menu.addAction(
                "Edit Brain Shower fields…",
                lambda: self._edit_metadata(brain_only=True),
            )
            self.edit_trailer_action = self.metadata_menu.addAction(
                "Edit safe trailer string…", self._edit_trailer_string
            )
            self.batch_menu = edit_menu.addMenu("Batch folder")
            self.batch_metadata_action = self.batch_menu.addAction(
                "Set header metadata…", self._batch_header_metadata
            )
            self.batch_shift_action = self.batch_menu.addAction(
                "Shift chart Start Times…", self._batch_shift_start_times
            )
            audio_menu = self.menuBar().addMenu("&Audio")
            audio_menu.addAction("Select audio…", self._choose_audio)
            audio_menu.addAction("Select metronome WAV…", self._choose_metronome)
            audio_menu.addAction("Calibrate audio offset…", self._calibrate_audio_offset)
            audio_menu.addAction("Estimate BPM from waveform…", self._estimate_bpm)
            audio_menu.addSeparator()
            metronome_mode_menu = audio_menu.addMenu("Metronome mode")
            self.metronome_mode_actions = {}
            metronome_mode_group = QActionGroup(self)
            metronome_mode_group.setExclusive(True)
            for label, mode in (("Per arrow", "arrow"), ("Per beat", "beat")):
                action = metronome_mode_menu.addAction(label)
                action.setCheckable(True)
                action.setData(mode)
                action.setChecked(mode == "arrow")
                action.triggered.connect(self._metronome_mode_changed)
                metronome_mode_group.addAction(action)
                self.metronome_mode_actions[mode] = action
            self.follow_audio_action = audio_menu.addAction("Follow chart")
            self.follow_audio_action.setCheckable(True)
            self.follow_audio_action.setChecked(True)
            preview_menu = self.menuBar().addMenu("&Preview")
            self.open_preview_action = preview_menu.addAction(
                "Open gameplay preview…", self._open_gameplay_preview
            )
            self.open_preview_action.setShortcut("Ctrl+Shift+P")

            toolbar = self.addToolBar("Note tools")
            toolbar.setMovable(False)
            toolbar.addWidget(QLabel("Tool: "))
            self.tool_combo = QComboBox()
            for label, tool in (
                ("Tap", NoteTool.TAP),
                ("Select", NoteTool.SELECT),
                ("Hold head", NoteTool.HOLD_HEAD),
                ("Hold body", NoteTool.HOLD_BODY),
                ("Hold tail", NoteTool.HOLD_TAIL),
                ("Item", NoteTool.ITEM),
                ("Division", NoteTool.DIVISION),
                ("Erase", NoteTool.ERASE),
            ):
                self.tool_combo.addItem(label, tool.value)
            toolbar.addWidget(self.tool_combo)
            self.tool_combo.currentIndexChanged.connect(self._tool_changed)
            toolbar.addSeparator()
            toolbar.addWidget(QLabel("Bank / ID: "))
            self.tool_value = QSpinBox()
            self.tool_value.setRange(0, 255)
            toolbar.addWidget(self.tool_value)
            self.visual_value_button = QToolButton()
            self.visual_value_button.setText("Visual…")
            self.visual_value_button.clicked.connect(self._show_visual_value_menu)
            toolbar.addWidget(self.visual_value_button)
            toolbar.addSeparator()
            toolbar.addWidget(QLabel("Function: "))
            self.function_combo = QComboBox()
            for label, mode in (
                ("Normal", NoteFunction.NORMAL),
                ("Bonus / Hidden (H)", NoteFunction.BONUS),
                ("Ghost (G)", NoteFunction.GHOST),
            ):
                self.function_combo.addItem(label, mode.value)
            toolbar.addWidget(self.function_combo)
            toolbar.addWidget(QLabel("Visibility: "))
            self.visibility_combo = QComboBox()
            for label, mode in (
                ("Visible", NoteVisibility.VISIBLE),
                ("Appear (▿)", NoteVisibility.APPEAR),
                ("Vanish (▵)", NoteVisibility.VANISH),
                ("Invisible (X)", NoteVisibility.INVISIBLE),
            ):
                self.visibility_combo.addItem(label, int(mode))
            toolbar.addWidget(self.visibility_combo)
            self.apply_flags = QPushButton("Apply flags")
            self.apply_flags.clicked.connect(self._apply_flags_to_selection)
            self.apply_flags.setToolTip(
                "Apply only function/visibility bits to selected notes; bank, "
                "slot, Brain Shower byte, and note type are preserved."
            )
            toolbar.addWidget(self.apply_flags)
            audio_toolbar = self.addToolBar("Audio transport")
            audio_toolbar.setMovable(False)
            self.audio_play = QPushButton("Play")
            self.audio_play.clicked.connect(self._toggle_audio_playback)
            audio_toolbar.addWidget(self.audio_play)
            self.audio_position = QSlider(Qt.Orientation.Horizontal, self)
            self.audio_position.setRange(0, 0)
            self.audio_position.sliderMoved.connect(self.audio_transport.seek)
            self.audio_position.hide()
            audio_toolbar.addSeparator()
            audio_toolbar.addWidget(QLabel("Start Time ms: "))
            self.chart_start_time = QDoubleSpinBox()
            self.chart_start_time.setRange(-1_000_000.0, 1_000_000.0)
            self.chart_start_time.setDecimals(3)
            self.chart_start_time.valueChanged.connect(self._chart_start_time_changed)
            audio_toolbar.addWidget(self.chart_start_time)
            self.audio_offset = QDoubleSpinBox()
            self.audio_offset.setRange(-1_000_000.0, 1_000_000.0)
            self.audio_offset.setDecimals(3)
            self.audio_offset.valueChanged.connect(self._audio_offset_changed)
            self.metronome_enabled = QCheckBox("Metronome")
            audio_toolbar.addWidget(self.metronome_enabled)
            self._refresh_edit_actions()
            local_noteskin = Path.cwd() / "noteskin"
            default_noteskin = (
                local_noteskin if local_noteskin.is_dir() else bundled_noteskin_root()
            )
            self._load_noteskin(default_noteskin, report_error=False)
            local_beat = Path.cwd() / "BEAT.WAV"
            default_beat = (
                local_beat if local_beat.is_file() else bundled_metronome_path()
            )
            self._load_metronome(default_beat)

        def _choose_folder(self) -> None:
            selected = QFileDialog.getExistingDirectory(self, "Open chart folder")
            if selected:
                self.load_folder(Path(selected))

        def _has_unsaved_changes(self) -> bool:
            return bool(
                self.workspace
                and any(entry.is_modified for entry in self.workspace.documents)
            )

        def _confirm_discard(self) -> bool:
            if not self._has_unsaved_changes():
                return True
            answer = QMessageBox.warning(
                self,
                "Unsaved chart changes",
                "Discard the unsaved changes in this workspace?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            return answer == QMessageBox.StandardButton.Discard

        def closeEvent(self, event) -> None:
            if self._confirm_discard():
                event.accept()
            else:
                event.ignore()

        def _choose_pack(self) -> None:
            selected = QFileDialog.getExistingDirectory(
                self, "Select StepNX visual pack"
            )
            if not selected:
                return
            try:
                self.pack = load_visual_pack(selected)
            except VisualPackError as exc:
                QMessageBox.critical(self, "Invalid visual pack", str(exc))
                return
            for index in range(self.tabs.count()):
                widget = self.tabs.widget(index)
                if isinstance(widget, TimelineWidget):
                    widget.set_visual_pack(self.pack)
            self.statusBar().showMessage(
                f"Loaded local visual pack: {self.pack.name}", 5000
            )

        def _choose_noteskin(self) -> None:
            selected = QFileDialog.getExistingDirectory(
                self, "Select local noteskin folder"
            )
            if selected:
                self._load_noteskin(Path(selected), report_error=True)

        def _choose_audio(self) -> None:
            initial = str(self.workspace.root) if self.workspace is not None else ""
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select chart audio",
                initial,
                "Audio (*.wav *.flac *.ogg *.mp3 *.mp2 *.aud);;All files (*)",
            )
            if selected:
                self._load_audio(Path(selected))

        def _choose_metronome(self) -> None:
            initial = str(self.workspace.root) if self.workspace is not None else ""
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select metronome sound",
                initial,
                "PCM WAV (*.wav);;All files (*)",
            )
            if selected:
                self._load_metronome(Path(selected))

        def _calibrate_audio_offset(self) -> None:
            value, accepted = QInputDialog.getDouble(
                self, "Audio calibration", "Session-only audio offset (ms):",
                self.audio_offset.value(), -1_000_000.0, 1_000_000.0, 3,
            )
            if accepted:
                self.audio_offset.setValue(value)

        def _estimate_bpm(self) -> None:
            if self.waveform is None:
                QMessageBox.information(self, "Estimate BPM", "Load a PCM WAV first.")
                return
            try:
                bpm = estimate_bpm(self.waveform)
            except WaveformError as exc:
                QMessageBox.warning(self, "Estimate BPM", str(exc))
                return
            answer = QMessageBox.question(
                self, "Estimate BPM", f"Estimated tempo: {bpm:.3f} BPM\n\nApply to the active Block?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            selection = self._structure_selection()
            if selection is None or selection[0] != "block" or self.workspace is None:
                QMessageBox.information(self, "Estimate BPM", "Select a Block first.")
                return
            _, document_index, target = selection
            document = self.sessions[document_index].current
            block = next(
                block for split in document.splits for block in split.blocks
                if block.stable_id == target.block_id
            )
            command = replace(BlockTimingValues.from_block(block), bpm=bpm).command(block.stable_id)
            self._execute_structure(
                document_index, command,
                ("block", document_index, target.split_id, target.block_id),
                "Applied estimated BPM",
            )

        def _show_visual_value_menu(self) -> None:
            tool = NoteTool(self.tool_combo.currentData())
            maximum = 31 if tool is NoteTool.ITEM else 4 if tool is NoteTool.DIVISION else -1
            if maximum < 0:
                self.statusBar().showMessage("Visual IDs apply only to Item and Division tools", 4000)
                return
            menu = QMenu(self)
            for value in range(maximum + 1):
                action = menu.addAction(f"ID {value}")
                action.triggered.connect(lambda checked=False, selected=value: self.tool_value.setValue(selected))
            menu.exec(self.visual_value_button.mapToGlobal(self.visual_value_button.rect().bottomLeft()))

        def _show_structure_context(self, document_index: int, split_id: int, block_id: int, point) -> None:
            self._populate_tree(("block", document_index, split_id, block_id))
            self._inspect("block", document_index, split_id, block_id)
            menu = QMenu(self)
            menu.addAction("Add Split after", self._insert_split)
            menu.addAction("Delete Split…", self._remove_split)
            menu.addSeparator()
            menu.addAction("Create Block after", self._insert_block)
            menu.addAction("Delete Block…", self._remove_block)
            menu.addSeparator()
            menu.addAction("Edit Block timing…", self._edit_block_timing)
            menu.exec(point)

        def _load_metronome(self, path: Path) -> None:
            self.metronome_path = path.resolve()
            self.audio_transport.load_metronome(self.metronome_path)
            self.statusBar().showMessage(
                f"Loaded metronome sound: {self.metronome_path.name}", 5000
            )

        def _load_audio(self, path: Path) -> None:
            if self.workspace is not None:
                try:
                    self.workspace = self.workspace.select_audio(path)
                except WorkspaceError as exc:
                    QMessageBox.critical(self, "Cannot select audio", str(exc))
                    return
            if not self.audio_transport.load(path):
                return
            self.waveform = None
            if path.suffix.casefold() == ".wav":
                try:
                    self.waveform = load_pcm_wav_waveform(path)
                except WaveformError as exc:
                    self.statusBar().showMessage(f"Waveform unavailable: {exc}", 8000)
            for index in range(self.tabs.count()):
                widget = self.tabs.widget(index)
                if isinstance(widget, TimelineWidget):
                    widget.set_waveform(self.waveform, self.audio_alignment)
            self.statusBar().showMessage(f"Loaded audio: {path.name}", 5000)

        def _load_noteskin(self, path: Path, *, report_error: bool) -> None:
            try:
                self.noteskin = load_noteskin_pack(path)
            except NoteskinPackError as exc:
                if report_error:
                    QMessageBox.critical(self, "Invalid noteskin folder", str(exc))
                return
            for index in range(self.tabs.count()):
                widget = self.tabs.widget(index)
                if isinstance(widget, (TimelineWidget, GameplayPreviewWidget)):
                    widget.set_noteskin_pack(self.noteskin)
            banks = ", ".join(f"{bank.bank_id:02d}" for bank in self.noteskin.banks)
            self.statusBar().showMessage(f"Loaded local noteskin banks: {banks}", 5000)

        def load_folder(self, path: Path, *, discard_changes: bool = False) -> None:
            if not discard_changes and not self._confirm_discard():
                return
            try:
                self.workspace = open_folder(
                    path, profile=self._selected_profile()
                )
            except (OSError, WorkspaceError) as exc:
                QMessageBox.critical(self, "Cannot open folder", str(exc))
                return
            self.setWindowTitle(f"StepNX Studio — {self.workspace.root.name}")
            for action in self.profile_actions.values():
                action.setEnabled(False)
            self.sessions = {
                index: CommandStack(entry.document)
                for index, entry in enumerate(self.workspace.documents)
            }
            self.baselines = {
                index: entry.document
                for index, entry in enumerate(self.workspace.documents)
            }
            self.widget_documents.clear()
            self.preview_snapshots.clear()
            self.gesture_keys.clear()
            self.audio_transport.load(None)
            self.waveform = None
            self.audio_position.setRange(0, 0)
            self.last_metronome_beat = None
            self.tabs.clear()
            self._populate_tree()
            self._populate_diagnostics()
            self._populate_routes()
            if self.workspace.documents:
                self._open_document(0)
            preferred_audio_name = f"{self.workspace.root.name}.mp3".casefold()
            preferred_audio = next(
                (
                    candidate
                    for candidate in self.workspace.root.parent.iterdir()
                    if candidate.is_file()
                    and not candidate.is_symlink()
                    and candidate.name.casefold() == preferred_audio_name
                ),
                None,
            )
            if preferred_audio is not None:
                self._load_audio(preferred_audio)

        def _save_all(self) -> None:
            if self.workspace is None:
                return
            plan = plan_save_all(self.workspace)
            if not plan.is_ready:
                details = "\n".join(
                    f"{issue.code}: {issue.message}" for issue in plan.issues[:20]
                )
                QMessageBox.critical(
                    self,
                    "Save blocked by validation",
                    details or "The workspace is not ready for publication.",
                )
                return
            if not plan.operations:
                self.statusBar().showMessage("No modified documents to save", 5000)
                return

            summary = []
            for index, entry in enumerate(self.workspace.documents):
                baseline = self.baselines.get(index)
                if baseline is None or baseline == entry.document:
                    continue
                changes = diff_documents(baseline, entry.document)
                summary.append(
                    f"{entry.path.name}: {len(changes)} structural change(s)"
                )
                summary.extend(f"  • {change.path}" for change in changes[:8])
                if len(changes) > 8:
                    summary.append(f"  • …and {len(changes) - 8} more")
            targets = "\n".join(
                f"  • {operation.target.name}" for operation in plan.operations
            )
            message = "The following files will be replaced atomically:\n" + targets
            if summary:
                message += "\n\nStructural diff preview:\n" + "\n".join(summary)
            answer = QMessageBox.question(
                self,
                "Confirm Save All",
                message,
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Save:
                return
            try:
                written = execute_save_plan(plan)
            except (OSError, WorkspaceError) as exc:
                QMessageBox.critical(self, "Save failed", str(exc))
                return
            root = self.workspace.root
            self.statusBar().showMessage(f"Saved {len(written)} document(s)", 5000)
            self.load_folder(root, discard_changes=True)

        def _populate_tree(
            self, selected: tuple[str, int, int | None, int | None] | None = None
        ) -> None:
            self.tree.clear()
            if self.workspace is None:
                return
            root = QTreeWidgetItem([self.workspace.root.name, str(self.workspace.root)])
            root.setData(0, Qt.ItemDataRole.UserRole, ("root", -1, None, None))
            self.tree.addTopLevelItem(root)
            selected_item = root if selected == ("root", -1, None, None) else None
            for document_index, entry in enumerate(self.workspace.documents):
                document_item = QTreeWidgetItem(
                    [entry.path.name, entry.source_format.value]
                )
                payload = ("document", document_index, None, None)
                document_item.setData(0, Qt.ItemDataRole.UserRole, payload)
                if payload == selected:
                    selected_item = document_item
                root.addChild(document_item)
                header = QTreeWidgetItem(
                    ["Header metadata", str(len(entry.document.header_metadata))]
                )
                payload = ("header", document_index, None, None)
                header.setData(0, Qt.ItemDataRole.UserRole, payload)
                if payload == selected:
                    selected_item = header
                document_item.addChild(header)
                for split_index, split in enumerate(entry.document.splits):
                    split_item = QTreeWidgetItem(
                        [f"Split {split_index + 1}", f"{len(split.blocks)} block(s)"]
                    )
                    payload = ("split", document_index, split.stable_id, None)
                    split_item.setData(0, Qt.ItemDataRole.UserRole, payload)
                    if payload == selected:
                        selected_item = split_item
                    document_item.addChild(split_item)
                    for block_index, block in enumerate(split.blocks):
                        block_item = QTreeWidgetItem(
                            [f"Block {block_index + 1}", f"{len(block.rows)} rows"]
                        )
                        payload = (
                            "block",
                            document_index,
                            split.stable_id,
                            block.stable_id,
                        )
                        block_item.setData(0, Qt.ItemDataRole.UserRole, payload)
                        if payload == selected:
                            selected_item = block_item
                        split_item.addChild(block_item)
            for failure in self.workspace.failures:
                item = QTreeWidgetItem([failure.path.name, "Open failure"])
                item.setData(0, Qt.ItemDataRole.UserRole, ("failure", -1, None, None))
                root.addChild(item)
            root.setExpanded(True)
            if selected_item is not None:
                self.tree.setCurrentItem(selected_item)
                self.tree.scrollToItem(selected_item)
            self._refresh_structure_actions()

        def _populate_diagnostics(self) -> None:
            self.diagnostics.clear()
            if self.workspace is None:
                return
            for failure in self.workspace.failures:
                QTreeWidgetItem(
                    self.diagnostics,
                    ["error", "workspace.open", str(failure.path), failure.error],
                )
            for diagnostic in self.workspace.diagnostics:
                QTreeWidgetItem(
                    self.diagnostics,
                    [
                        diagnostic.severity.value,
                        diagnostic.code,
                        diagnostic.path,
                        diagnostic.message,
                    ],
                )
            for entry in self.workspace.documents:
                for issue in entry.validation.issues:
                    QTreeWidgetItem(
                        self.diagnostics,
                        [
                            issue.severity.value,
                            issue.code,
                            f"{entry.path.name}:{issue.path}",
                            issue.message,
                        ],
                    )
                for issue in validate_authoring(entry.document).issues:
                    QTreeWidgetItem(
                        self.diagnostics,
                        [
                            issue.severity.value,
                            issue.code,
                            f"{entry.path.name}:{issue.path}",
                            issue.message,
                        ],
                    )
                for issue in project_trailer_strings(entry.document).diagnostics:
                    QTreeWidgetItem(
                        self.diagnostics,
                        [
                            "warning",
                            issue.code,
                            f"{entry.path.name}:header_metadata#{issue.metadata_stable_id}",
                            issue.message,
                        ],
                    )
            self.diagnostics.resizeColumnToContents(0)
            self.diagnostics.resizeColumnToContents(1)

        def _populate_routes(self) -> None:
            self.routes.clear()
            if self.workspace is None:
                return
            for document_index, entry in enumerate(self.workspace.documents):
                document_item = QTreeWidgetItem(
                    self.routes,
                    [entry.path.name, entry.document.profile, "", ""],
                )
                for route in project_routes(entry.document):
                    modes = []
                    if route.random_at_start:
                        modes.append("random start")
                    if route.random_at_trigger:
                        modes.append("random trigger")
                    if route.force_select:
                        modes.append("force")
                    if route.group:
                        modes.append(f"group {route.group}")
                    split_item = QTreeWidgetItem(
                        document_item,
                        [
                            f"Split {route.split_index + 1}",
                            ", ".join(modes) or "ordered",
                            "",
                            "",
                        ],
                    )
                    split_item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        ("route", document_index, route.split_id, None),
                    )
                    for branch in route.branches:
                        conditions = "; ".join(
                            f"{item.metric} {item.minimum}..{item.maximum}"
                            for item in branch.conditions
                        )
                        triggers = ", ".join(
                            f"r{item.row_index + 1}/c{item.column + 1}:D{item.division_id}"
                            + ("*" if item.triggers else "")
                            for item in branch.triggers[:8]
                        )
                        if len(branch.triggers) > 8:
                            triggers += f", +{len(branch.triggers) - 8}"
                        branch_item = QTreeWidgetItem(
                            split_item,
                            [
                                f"Block {branch.block_index + 1}",
                                "candidate",
                                conditions or "unconditional",
                                triggers or "none",
                            ],
                        )
                        branch_item.setData(
                            0,
                            Qt.ItemDataRole.UserRole,
                            ("route", document_index, route.split_id, branch.block_id),
                        )
                document_item.setExpanded(True)
            for column in range(4):
                self.routes.resizeColumnToContents(column)

        def _route_activated(self, item, column) -> None:
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if not payload:
                return
            _, document_index, split_id, block_id = payload
            self._open_document(document_index)
            widget = self.tabs.currentWidget()
            if not isinstance(widget, TimelineWidget):
                return
            if block_id is not None:
                try:
                    widget.set_snapshot(
                        widget.snapshot.with_active_block(split_id, block_id)
                    )
                except KeyError:
                    return
                self._set_metronome_snapshot(widget.snapshot)
                self._populate_tree(("block", document_index, split_id, block_id))
                self._inspect("block", document_index, split_id, block_id)
            else:
                self._populate_tree(("split", document_index, split_id, None))
                self._inspect("split", document_index, split_id, None)

        def _tree_activated(self, item, column) -> None:
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if not payload:
                return
            kind, document_index, split_id, block_id = payload
            if document_index >= 0:
                self._open_document(document_index)
                self._inspect(kind, document_index, split_id, block_id)

        def _open_document(self, document_index: int) -> None:
            entry = self.workspace.documents[document_index]
            for index in range(self.tabs.count()):
                if self.tabs.tabToolTip(index) == str(entry.path):
                    self.tabs.setCurrentIndex(index)
                    return
            snapshot = create_authoring_snapshot(self.sessions[document_index].current)
            widget = TimelineWidget(snapshot)
            widget.set_visual_pack(self.pack)
            widget.set_noteskin_pack(self.noteskin)
            widget.set_selection_mode(
                NoteTool(self.tool_combo.currentData()) is NoteTool.SELECT
            )
            widget.set_snap_beats(self._selected_snap())
            widget.set_waveform(self.waveform, self.audio_alignment)
            widget.selectedCellsChanged.connect(self._refresh_edit_actions)
            widget.inspectionRequested.connect(
                lambda split_id, block_id, doc=document_index: self._inspect_ids(
                    doc, split_id, block_id
                )
            )
            widget.noteEditRequested.connect(
                lambda row_id, lane, doc=document_index, view=widget: self._edit_note(
                    doc, view, row_id, lane
                )
            )
            widget.holdEditRequested.connect(
                lambda row_ids, lane, doc=document_index, view=widget: self._edit_hold(
                    doc, view, row_ids, lane
                )
            )
            widget.contextStructureRequested.connect(
                lambda split_id, block_id, point, doc=document_index: self._show_structure_context(
                    doc, split_id, block_id, point
                )
            )
            widget.editGestureStarted.connect(
                lambda view=widget: self.gesture_keys.__setitem__(view, object())
            )
            widget.editGestureFinished.connect(
                lambda doc=document_index, view=widget: self._finish_note_gesture(
                    doc, view
                )
            )
            index = self.tabs.addTab(widget, entry.path.name)
            self.tabs.setTabToolTip(index, str(entry.path))
            self.tabs.setCurrentIndex(index)
            self.widget_documents[widget] = document_index
            self._set_metronome_snapshot(widget.snapshot)
            self._refresh_chart_start_time(widget)
            self._refresh_edit_actions()

        def _current_document_index(self) -> int | None:
            widget = self.tabs.currentWidget()
            return (
                self.widget_documents.get(widget)
                if isinstance(widget, TimelineWidget)
                else None
            )

        def _open_gameplay_preview(self) -> None:
            source_widget = self.tabs.currentWidget()
            current_document_index = self._current_document_index()
            if (
                current_document_index is None
                or not isinstance(source_widget, TimelineWidget)
                or self.workspace is None
            ):
                QMessageBox.information(
                    self,
                    "Gameplay preview",
                    "Select an authoring timeline before opening a gameplay preview.",
                )
                return
            charts = tuple(
                PreviewChartChoice(
                    document_index,
                    entry.path.name,
                )
                for document_index, entry in enumerate(self.workspace.documents)
                if not self.sessions[document_index].current.effective_lightmap
            )
            if not charts:
                QMessageBox.information(
                    self,
                    "Gameplay preview",
                    "The workspace has no playable NX chart.",
                )
                return
            dialog = GameplayInitializationDialog(
                charts,
                current_document_index=current_document_index,
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            options = dialog.options()
            document_index = options.document_index
            command = parse_gameplay_command(options.command).with_speed(options.speed)
            if command.unknown:
                QMessageBox.warning(
                    self,
                    "Unknown COMMAND",
                    "Unsupported character(s): " + ", ".join(command.unknown),
                )
                return

            snapshot = create_preview_snapshot(self.sessions[document_index].current)
            random_route = any(
                split.random_at_start or split.random_at_trigger
                for split in snapshot.splits
            )
            policy = RoutePolicy.SEEDED if random_route else RoutePolicy.MANUAL
            seed = secrets.randbits(64) if random_route else None
            errors = [
                diagnostic
                for diagnostic in snapshot.diagnostics
                if diagnostic.severity is Severity.ERROR
            ]
            if errors:
                QMessageBox.warning(
                    self,
                    "Gameplay preview unavailable",
                    "\n".join(f"{item.code}: {item.message}" for item in errors[:12]),
                )
                return
            selected_view = next(
                (
                    self.tabs.widget(index)
                    for index in range(self.tabs.count())
                    if isinstance(self.tabs.widget(index), TimelineWidget)
                    and self.widget_documents.get(self.tabs.widget(index))
                    == document_index
                ),
                None,
            )
            manual = (
                dict(selected_view.snapshot.active_blocks)
                if selected_view is not None
                else {
                    split.stable_id: split.blocks[0].stable_id
                    for split in snapshot.splits
                    if split.blocks
                }
            )
            route = resolve_route(snapshot, policy, seed=seed, manual=manual)
            if not route.is_executable:
                QMessageBox.warning(
                    self,
                    "Route cannot be previewed",
                    "\n".join(
                        f"{'Split ' + str(item.split_id) if item.split_id else 'Document'}: "
                        f"{item.message}"
                        for item in route.diagnostics
                    ),
                )
                return
            stream = build_event_stream(snapshot, route)
            preview = GameplayPreviewWidget(
                stream,
                columns=snapshot.columns,
                start_column=snapshot.start_column,
                command=command,
            )
            preview.seekRequested.connect(
                lambda chart_time: self.audio_transport.seek(
                    round(self.audio_alignment.chart_to_audio(chart_time))
                )
            )
            preview.statusChanged.connect(
                lambda message: self.statusBar().showMessage(message, 4000)
            )
            preview.exitRequested.connect(preview.close)
            preview.set_noteskin_pack(self.noteskin)
            preview.set_playback_time(
                self.audio_alignment.audio_to_chart(float(self.audio_position.value()))
            )
            entry = self.workspace.documents[document_index]
            preview.setWindowTitle(f"StepNX Preview — {entry.path.name}")
            preview.resize(720, 900)
            route_summary = ", ".join(
                f"S{decision.split_id}→B{decision.block_id}"
                for decision in route.decisions
            )
            metronome_snapshot = create_authoring_snapshot(
                self.sessions[document_index].current
            )
            for decision in route.decisions:
                metronome_snapshot = metronome_snapshot.with_active_block(
                    decision.split_id, decision.block_id
                )
            self.preview_snapshots[preview] = metronome_snapshot
            preview.destroyed.connect(lambda *_args, view=preview: self.preview_snapshots.pop(view, None))
            preview.show()
            warning = " · ".join(stream.warnings)
            command_status = []
            if command.approximate_effects:
                command_status.append(
                    "approximate COMMAND curves: "
                    + ",".join(command.approximate_effects)
                )
            if command.pending_effects:
                command_status.append(
                    "COMMAND flags pending projection: "
                    + ",".join(command.pending_effects)
                )
            if command_status:
                warning = " · ".join(filter(None, (warning, *command_status)))
            self.statusBar().showMessage(
                f"Opened read-only gameplay preview ({len(stream.events)} events)"
                + (f" · {warning}" if warning else ""),
                8000,
            )

        def _edit_note(
            self, document_index: int, widget: TimelineWidget, row_id: int, lane: int
        ) -> None:
            tool = NoteTool(self.tool_combo.currentData())
            if tool is NoteTool.SELECT:
                self.statusBar().showMessage(f"Selected row {row_id}, lane {lane + 1}")
                return
            try:
                current = self._cell_raw(document_index, row_id, lane)
                raw = (
                    b"\0\0\0\0"
                    if tool is NoteTool.ERASE or (tool in (NoteTool.TAP, NoteTool.ITEM, NoteTool.DIVISION) and current[0] & 0x0F)
                    else note_tool_raw(
                        tool,
                        self.tool_value.value(),
                        self._selected_function(),
                        self._selected_visibility(),
                    )
                )
                updated = self.sessions[document_index].execute(
                    SetNoteAt(row_id, lane, raw),
                    coalesce_key=self.gesture_keys.get(widget),
                )
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Cannot edit note", str(exc))
                return
            self._apply_document(document_index, widget, updated)

        def _cell_raw(self, document_index: int, row_id: int, lane: int) -> bytes:
            document = self.sessions[document_index].current
            for split in document.splits:
                for block in split.blocks:
                    for row in block.rows:
                        if row.stable_id != row_id:
                            continue
                        if isinstance(row, (EmptyRow, LightmapRow)):
                            return b"\0\0\0\0"
                        return row.cell(lane).raw if isinstance(row, PackedNoteRow) else row.cells[lane].raw
            raise ModelInvariantError(f"row {row_id} does not exist")

        def _edit_hold(self, document_index: int, widget: TimelineWidget, row_ids, lane: int) -> None:
            row_ids = tuple(row_ids)
            if len(row_ids) < 2:
                self._edit_note(document_index, widget, row_ids[0], lane)
                return
            raws = (
                note_tool_raw(NoteTool.HOLD_HEAD, self.tool_value.value(), self._selected_function(), self._selected_visibility()),
                note_tool_raw(NoteTool.HOLD_BODY, self.tool_value.value(), self._selected_function(), self._selected_visibility()),
                note_tool_raw(NoteTool.HOLD_TAIL, self.tool_value.value(), self._selected_function(), self._selected_visibility()),
            )
            try:
                updated = None
                for index, row_id in enumerate(row_ids):
                    raw = raws[0 if index == 0 else 2 if index == len(row_ids) - 1 else 1]
                    updated = self.sessions[document_index].execute(
                        SetNoteAt(row_id, lane, raw), coalesce_key=self.gesture_keys.get(widget)
                    )
                assert updated is not None
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Cannot create hold", str(exc))
                return
            self._apply_document(document_index, widget, updated)

        def _finish_note_gesture(
            self, document_index: int, widget: TimelineWidget
        ) -> None:
            self.sessions[document_index].finish_coalescing()
            self.gesture_keys.pop(widget, None)
            self._refresh_edit_actions()

        def _apply_document(
            self,
            document_index: int,
            widget: TimelineWidget,
            document,
            *,
            tree_selection: tuple[str, int, int | None, int | None] | None = None,
        ) -> None:
            entry = self.workspace.documents[document_index].with_document(document)
            self.workspace = self.workspace.replace_document(entry)
            old_snapshot = widget.snapshot
            snapshot = create_authoring_snapshot(document)
            for split_id, block_id in old_snapshot.active_blocks:
                try:
                    snapshot = snapshot.with_active_block(split_id, block_id)
                except KeyError:
                    pass
            widget.set_snapshot(snapshot)
            if widget is self.tabs.currentWidget():
                self._set_metronome_snapshot(snapshot)
            title = entry.path.name + (" *" if entry.is_modified else "")
            self.tabs.setTabText(self.tabs.indexOf(widget), title)
            if tree_selection is not None:
                self._populate_tree(tree_selection)
            self._populate_diagnostics()
            self._populate_routes()
            self._refresh_edit_actions()

        def _undo(self) -> None:
            document_index = self._current_document_index()
            widget = self.tabs.currentWidget()
            if document_index is None or not isinstance(widget, TimelineWidget):
                return
            stack = self.sessions[document_index]
            if stack.can_undo:
                self._apply_document(
                    document_index,
                    widget,
                    stack.undo(),
                    tree_selection=("document", document_index, None, None),
                )

        def _redo(self) -> None:
            document_index = self._current_document_index()
            widget = self.tabs.currentWidget()
            if document_index is None or not isinstance(widget, TimelineWidget):
                return
            stack = self.sessions[document_index]
            if stack.can_redo:
                self._apply_document(
                    document_index,
                    widget,
                    stack.redo(),
                    tree_selection=("document", document_index, None, None),
                )

        def _refresh_edit_actions(self, *args) -> None:
            document_index = (
                self._current_document_index() if hasattr(self, "tabs") else None
            )
            stack = (
                self.sessions.get(document_index)
                if document_index is not None
                else None
            )
            if hasattr(self, "undo_action"):
                self.undo_action.setEnabled(bool(stack and stack.can_undo))
                self.redo_action.setEnabled(bool(stack and stack.can_redo))
            if hasattr(self, "insert_split_action"):
                self._refresh_structure_actions()
            if hasattr(self, "edit_metadata_action"):
                metadata_context = self._metadata_context()
                self.edit_metadata_action.setEnabled(metadata_context is not None)
                self.edit_brain_action.setEnabled(
                    metadata_context is not None
                    and metadata_context[1] is MetadataScope.DIVISION
                )
                document_index = self._current_document_index()
                has_trailer_string = bool(
                    document_index is not None
                    and project_trailer_strings(
                        self.sessions[document_index].current
                    ).strings
                )
                self.edit_trailer_action.setEnabled(has_trailer_string)
                self.batch_metadata_action.setEnabled(self.workspace is not None)
                self.batch_shift_action.setEnabled(self.workspace is not None)
            widget = self.tabs.currentWidget() if hasattr(self, "tabs") else None
            has_selection = bool(
                isinstance(widget, TimelineWidget) and widget.selection.targets
            )
            if hasattr(self, "apply_selection_action"):
                tool = NoteTool(self.tool_combo.currentData())
                self.apply_selection_action.setEnabled(
                    has_selection and tool is not NoteTool.SELECT
                )
                self.clear_selection_notes_action.setEnabled(has_selection)
                self.mirror_selection_action.setEnabled(has_selection)
                self.clear_selection_action.setEnabled(has_selection)
                self.copy_selection_action.setEnabled(has_selection)
                self.paste_selection_action.setEnabled(
                    has_selection and self.note_clipboard is not None
                )
                self.replace_selection_action.setEnabled(has_selection)
                self.apply_flags.setEnabled(has_selection)

        def _tool_changed(self, *args) -> None:
            select = NoteTool(self.tool_combo.currentData()) is NoteTool.SELECT
            for index in range(self.tabs.count()):
                widget = self.tabs.widget(index)
                if isinstance(widget, TimelineWidget):
                    widget.set_selection_mode(select)
            self._refresh_edit_actions()

        def _snap_changed(self, *args) -> None:
            beats = self._selected_snap()
            for index in range(self.tabs.count()):
                widget = self.tabs.widget(index)
                if isinstance(widget, TimelineWidget):
                    widget.set_snap_beats(beats)
            label = self.snap_actions[beats].text()
            message = (
                "Snap disabled: clicks use the exact chart row."
                if beats == 0.0
                else f"Snap grid: {label}. Clicks round to the nearest blue guide."
            )
            self.statusBar().showMessage(message, 5000)

        def _selected_function(self) -> NoteFunction:
            return NoteFunction(self.function_combo.currentData())

        def _selected_visibility(self) -> NoteVisibility:
            return NoteVisibility(int(self.visibility_combo.currentData()))

        def _selected_profile(self) -> str:
            for value, action in self.profile_actions.items():
                if action.isChecked():
                    return value
            return "nxa-native"

        def _selected_snap(self) -> float:
            for beats, action in self.snap_actions.items():
                if action.isChecked():
                    return beats
            return 0.0

        def _selected_metronome_mode(self) -> str:
            for mode, action in self.metronome_mode_actions.items():
                if action.isChecked():
                    return mode
            return "arrow"

        def _metronome_mode_changed(self, *args) -> None:
            self.last_metronome_beat = None

        def _set_metronome_snapshot(self, snapshot) -> None:
            self.metronome_clock = MetronomeClock(snapshot)
            self.note_metronome_clock = NoteMetronomeClock(snapshot)

        def _audio_position_changed(self, position: int) -> None:
            if not self.audio_position.isSliderDown():
                self.audio_position.setValue(position)
            chart_time = self.audio_alignment.audio_to_chart(float(position))
            active = self.tabs.currentWidget()
            for index in range(self.tabs.count()):
                widget = self.tabs.widget(index)
                if isinstance(widget, TimelineWidget):
                    widget.set_playback_time(
                        chart_time,
                        follow=(
                            widget is active
                            and self.audio_playing
                            and self.follow_audio_action.isChecked()
                        ),
                    )
                elif isinstance(widget, GameplayPreviewWidget):
                    widget.set_playback_time(chart_time)
            for preview in tuple(self.preview_snapshots):
                preview.set_playback_time(chart_time)
            if not self.metronome_enabled.isChecked() or self.metronome_clock is None:
                return
            if self._selected_metronome_mode() == "arrow":
                note = (
                    None
                    if self.note_metronome_clock is None
                    else self.note_metronome_clock.note_at(chart_time)
                )
                identity = (
                    None if note is None else ("arrow", note.block_id, note.row_index)
                )
            else:
                beat = self.metronome_clock.beat_at(chart_time)
                identity = (
                    None if beat is None else ("beat", beat.block_id, beat.beat_index)
                )
            if (
                identity is not None
                and identity != self.last_metronome_beat
                and not self.audio_transport.play_metronome()
            ):
                self.statusBar().showMessage(
                    "Metronome enabled, but no loaded BEAT.WAV is ready",
                    3000,
                )
            self.last_metronome_beat = identity

        def _audio_duration_changed(self, duration: int) -> None:
            self.audio_position.setRange(0, max(0, duration))
            self._audio_position_changed(self.audio_position.value())

        def _audio_playback_changed(self, playing: bool) -> None:
            self.audio_playing = playing
            self.audio_play.setText("Pause" if playing else "Play")
            for index in range(self.tabs.count()):
                widget = self.tabs.widget(index)
                if isinstance(widget, TimelineWidget):
                    widget.set_playback_active(playing)
                    widget.set_playback_time(
                        self.audio_alignment.audio_to_chart(
                            float(self.audio_position.value())
                        ),
                        follow=(
                            playing
                            and widget is self.tabs.currentWidget()
                            and self.follow_audio_action.isChecked()
                        ),
                    )
            if not playing:
                self.last_metronome_beat = None

        def _audio_offset_changed(self, value: float) -> None:
            self.audio_alignment = AudioAlignment(value)
            for index in range(self.tabs.count()):
                widget = self.tabs.widget(index)
                if isinstance(widget, TimelineWidget):
                    widget.set_waveform(self.waveform, self.audio_alignment)
            self._audio_position_changed(self.audio_position.value())

        def _refresh_chart_start_time(self, widget: TimelineWidget) -> None:
            blocks = [block for split in widget.snapshot.splits for block in split.blocks]
            value = blocks[0].start_time if blocks else 0.0
            self.chart_start_time.blockSignals(True)
            self.chart_start_time.setValue(value)
            self.chart_start_time.blockSignals(False)

        def _chart_start_time_changed(self, value: float) -> None:
            document_index = self._current_document_index()
            widget = self.tabs.currentWidget()
            if document_index is None or not isinstance(widget, TimelineWidget):
                return
            document = self.sessions[document_index].current
            block = next((block for split in document.splits for block in split.blocks), None)
            if block is None or abs(float(block.start_time.value) - value) < 0.0001:
                return
            try:
                command = replace(BlockTimingValues.from_block(block), start_time_ms=value).command(block.stable_id)
                updated = self.sessions[document_index].execute(command)
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Invalid Start Time", str(exc))
                self._refresh_chart_start_time(widget)
                return
            self._apply_document(document_index, widget, updated)

        def _active_tab_changed(self, *args) -> None:
            widget = self.tabs.currentWidget()
            if isinstance(widget, TimelineWidget):
                self._set_metronome_snapshot(widget.snapshot)
                self._refresh_chart_start_time(widget)
            elif isinstance(widget, GameplayPreviewWidget):
                snapshot = self.preview_snapshots.get(widget)
                if snapshot is not None:
                    self._set_metronome_snapshot(snapshot)
                else:
                    self.metronome_clock = None
                    self.note_metronome_clock = None
            else:
                self.metronome_clock = None
                self.note_metronome_clock = None
            if isinstance(widget, (TimelineWidget, GameplayPreviewWidget)):
                widget.set_playback_time(
                    self.audio_alignment.audio_to_chart(
                        float(self.audio_position.value())
                    )
                )
            self.last_metronome_beat = None

        def _selected_chart_time(self) -> float | None:
            widget = self.tabs.currentWidget()
            if (
                not isinstance(widget, TimelineWidget)
                or not widget.selection.targets
                or widget.selection.anchor is None
            ):
                return None
            row_id = widget.selection.anchor.row_id
            projection = TimingProjection(widget.snapshot)
            for split in widget.snapshot.splits:
                block = widget.snapshot.active_block(split.stable_id)
                for row_index, row in enumerate(block.rows):
                    if row.stable_id == row_id:
                        return projection.point(
                            split.stable_id, block.stable_id, row_index
                        ).time_ms
            return None

        def _toggle_audio_playback(self) -> None:
            if self.audio_playing:
                self.audio_transport.toggle()
                return
            chart_time = self._selected_chart_time()
            if chart_time is None:
                widget = self.tabs.currentWidget()
                if isinstance(widget, TimelineWidget):
                    chart_time = widget.chart_time_at_viewport_beat()
            if chart_time is not None:
                self.audio_transport.seek(
                    round(self.audio_alignment.chart_to_audio(chart_time))
                )
            self.audio_transport.toggle()

        def _execute_bulk(
            self, command, *, selection: CellSelection | None = None
        ) -> None:
            document_index = self._current_document_index()
            widget = self.tabs.currentWidget()
            if document_index is None or not isinstance(widget, TimelineWidget):
                return
            try:
                updated = self.sessions[document_index].execute(command)
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Cannot edit selection", str(exc))
                return
            self._apply_document(document_index, widget, updated)
            if selection is not None:
                widget.set_selection(selection)
            self.statusBar().showMessage(
                f"Updated {len(widget.selection.targets)} selected cell(s)", 5000
            )

        def _apply_tool_to_selection(self) -> None:
            widget = self.tabs.currentWidget()
            if not isinstance(widget, TimelineWidget) or not widget.selection.targets:
                return
            tool = NoteTool(self.tool_combo.currentData())
            if tool is NoteTool.SELECT:
                return
            try:
                raw = note_tool_raw(
                    tool,
                    self.tool_value.value(),
                    self._selected_function(),
                    self._selected_visibility(),
                )
                command = set_selection_raw(widget.selection, raw)
            except ValueError as exc:
                QMessageBox.critical(self, "Cannot edit selection", str(exc))
                return
            self._execute_bulk(command)

        def _apply_flags_to_selection(self) -> None:
            document_index = self._current_document_index()
            widget = self.tabs.currentWidget()
            if (
                document_index is None
                or not isinstance(widget, TimelineWidget)
                or not widget.selection.targets
            ):
                self.statusBar().showMessage("Select one or more notes first", 4000)
                return
            try:
                command = modify_selection_notes(
                    self.sessions[document_index].current,
                    widget.selection,
                    self._selected_function(),
                    self._selected_visibility(),
                )
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Cannot apply note flags", str(exc))
                return
            self._execute_bulk(command)

        def _erase_selected_notes(self) -> None:
            widget = self.tabs.currentWidget()
            if not isinstance(widget, TimelineWidget) or not widget.selection.targets:
                return
            self._execute_bulk(set_selection_raw(widget.selection, b"\x00\x00\x00\x00"))

        def _mirror_selected_notes(self) -> None:
            document_index = self._current_document_index()
            widget = self.tabs.currentWidget()
            if (
                document_index is None
                or not isinstance(widget, TimelineWidget)
                or not widget.selection.targets
            ):
                return
            document = self.sessions[document_index].current
            try:
                command, selection = mirror_selection(document, widget.selection)
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Cannot mirror selection", str(exc))
                return
            self._execute_bulk(command, selection=selection)

        def _clear_selection(self) -> None:
            widget = self.tabs.currentWidget()
            if isinstance(widget, TimelineWidget):
                widget.set_selection(CellSelection())

        def _copy_selected_notes(self) -> None:
            document_index = self._current_document_index()
            widget = self.tabs.currentWidget()
            if document_index is None or not isinstance(widget, TimelineWidget):
                return
            try:
                self.note_clipboard = copy_selection(
                    self.sessions[document_index].current, widget.selection
                )
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Cannot copy selection", str(exc))
                return
            self.statusBar().showMessage(
                f"Copied {len(self.note_clipboard.cells)} note cell(s)", 5000
            )
            self._refresh_edit_actions()

        def _paste_selected_notes(self) -> None:
            document_index = self._current_document_index()
            widget = self.tabs.currentWidget()
            if (
                document_index is None
                or not isinstance(widget, TimelineWidget)
                or self.note_clipboard is None
                or widget.selection.anchor is None
            ):
                return
            try:
                command, selection = paste_clipboard(
                    self.sessions[document_index].current,
                    self.note_clipboard,
                    widget.selection.anchor,
                )
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Cannot paste notes", str(exc))
                return
            self._execute_bulk(command, selection=selection)

        def _replace_selected_type(self) -> None:
            document_index = self._current_document_index()
            widget = self.tabs.currentWidget()
            if document_index is None or not isinstance(widget, TimelineWidget):
                return
            note_type, accepted = QInputDialog.getInt(
                self,
                "Replace selected note type",
                "Existing low-nibble note type (0–15):",
                3,
                0,
                15,
            )
            if not accepted:
                return
            tool = NoteTool(self.tool_combo.currentData())
            if tool is NoteTool.SELECT:
                QMessageBox.information(
                    self,
                    "Choose a replacement",
                    "Select a placement or erase tool first.",
                )
                return
            try:
                replacement = note_tool_raw(
                    tool,
                    self.tool_value.value(),
                    self._selected_function(),
                    self._selected_visibility(),
                )
                command = replace_selection_type(
                    self.sessions[document_index].current,
                    widget.selection,
                    note_type,
                    replacement,
                )
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Cannot replace selection", str(exc))
                return
            self._execute_bulk(command)

        def _structure_selection(
            self,
        ) -> tuple[str, int, StructureTarget] | None:
            item = self.tree.currentItem()
            if item is None:
                return None
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if not payload:
                return None
            kind, document_index, split_id, block_id = payload
            if kind not in ("split", "block") or document_index < 0 or split_id is None:
                return None
            return kind, document_index, StructureTarget(split_id, block_id)

        def _refresh_structure_actions(self, *args) -> None:
            if not hasattr(self, "insert_split_action"):
                return
            selection = self._structure_selection()
            split_enabled = selection is not None
            block_enabled = bool(selection and selection[0] == "block")
            can_remove_split = False
            can_move_split_up = False
            can_move_split_down = False
            can_remove_block = False
            can_move_block_up = False
            can_move_block_down = False
            if selection is not None and self.workspace is not None:
                _, document_index, target = selection
                document = self.workspace.documents[document_index].document
                split_index = next(
                    (
                        index
                        for index, split in enumerate(document.splits)
                        if split.stable_id == target.split_id
                    ),
                    -1,
                )
                if split_index >= 0:
                    split = document.splits[split_index]
                    can_remove_split = len(document.splits) > 1
                    can_move_split_up = split_index > 0
                    can_move_split_down = split_index + 1 < len(document.splits)
                    if target.block_id is not None:
                        block_index = next(
                            (
                                index
                                for index, block in enumerate(split.blocks)
                                if block.stable_id == target.block_id
                            ),
                            -1,
                        )
                        can_remove_block = block_index >= 0 and len(split.blocks) > 1
                        can_move_block_up = block_index > 0
                        can_move_block_down = (
                            block_index >= 0 and block_index + 1 < len(split.blocks)
                        )
            self.insert_split_action.setEnabled(split_enabled)
            self.remove_split_action.setEnabled(can_remove_split)
            self.move_split_up_action.setEnabled(can_move_split_up)
            self.move_split_down_action.setEnabled(can_move_split_down)
            self.insert_block_action.setEnabled(block_enabled)
            self.remove_block_action.setEnabled(can_remove_block)
            self.move_block_up_action.setEnabled(can_move_block_up)
            self.move_block_down_action.setEnabled(can_move_block_down)
            self.edit_timing_action.setEnabled(block_enabled)
            self.shift_start_times_action.setEnabled(
                self._current_document_index() is not None
            )

        def _execute_structure(
            self,
            document_index: int,
            command,
            selection_after: tuple[str, int, int | None, int | None],
            message: str,
        ) -> None:
            self._open_document(document_index)
            widget = self.tabs.currentWidget()
            if not isinstance(widget, TimelineWidget):
                return
            try:
                updated = self.sessions[document_index].execute(command)
            except (StructureEditError, ModelInvariantError, ValueError) as exc:
                QMessageBox.critical(self, "Cannot edit structure", str(exc))
                return
            self._apply_document(
                document_index,
                widget,
                updated,
                tree_selection=selection_after,
            )
            self.statusBar().showMessage(message, 5000)

        def _insert_split(self) -> None:
            selection = self._structure_selection()
            if selection is None or self.workspace is None:
                return
            _, document_index, target = selection
            document = self.workspace.documents[document_index].document
            try:
                command = insert_empty_split_after(document, target)
                updated = command.apply(document)
            except (StructureEditError, ModelInvariantError, ValueError) as exc:
                QMessageBox.critical(self, "Cannot insert Split", str(exc))
                return
            old_ids = {split.stable_id for split in document.splits}
            new_split = next(
                split for split in updated.splits if split.stable_id not in old_ids
            )
            self._execute_structure(
                document_index,
                command,
                ("split", document_index, new_split.stable_id, None),
                "Inserted empty Split",
            )

        def _insert_block(self) -> None:
            selection = self._structure_selection()
            if selection is None or selection[0] != "block" or self.workspace is None:
                return
            _, document_index, target = selection
            document = self.workspace.documents[document_index].document
            try:
                command = insert_empty_block_after(document, target)
                updated = command.apply(document)
            except (StructureEditError, ModelInvariantError, ValueError) as exc:
                QMessageBox.critical(self, "Cannot insert Block", str(exc))
                return
            old_ids = {
                block.stable_id
                for split in document.splits
                if split.stable_id == target.split_id
                for block in split.blocks
            }
            split = next(
                split for split in updated.splits if split.stable_id == target.split_id
            )
            new_block = next(
                block for block in split.blocks if block.stable_id not in old_ids
            )
            self._execute_structure(
                document_index,
                command,
                ("block", document_index, target.split_id, new_block.stable_id),
                "Inserted empty Block",
            )

        def _remove_split(self) -> None:
            selection = self._structure_selection()
            if selection is None or self.workspace is None:
                return
            _, document_index, target = selection
            answer = QMessageBox.question(
                self,
                "Remove Split",
                "Remove the selected Split and every Block and note it contains?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            document = self.workspace.documents[document_index].document
            try:
                command = remove_split(document, target)
            except StructureEditError as exc:
                QMessageBox.critical(self, "Cannot remove Split", str(exc))
                return
            remaining = next(
                split for split in document.splits if split.stable_id != target.split_id
            )
            self._execute_structure(
                document_index,
                command,
                ("split", document_index, remaining.stable_id, None),
                "Removed Split",
            )

        def _remove_block(self) -> None:
            selection = self._structure_selection()
            if selection is None or selection[0] != "block" or self.workspace is None:
                return
            _, document_index, target = selection
            answer = QMessageBox.question(
                self,
                "Remove Block",
                "Remove the selected Block and every note it contains?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            document = self.workspace.documents[document_index].document
            try:
                command = remove_block(document, target)
            except StructureEditError as exc:
                QMessageBox.critical(self, "Cannot remove Block", str(exc))
                return
            split = next(
                split for split in document.splits if split.stable_id == target.split_id
            )
            remaining = next(
                block for block in split.blocks if block.stable_id != target.block_id
            )
            self._execute_structure(
                document_index,
                command,
                ("block", document_index, target.split_id, remaining.stable_id),
                "Removed Block",
            )

        def _move_split(self, delta: int) -> None:
            selection = self._structure_selection()
            if selection is None or self.workspace is None:
                return
            _, document_index, target = selection
            document = self.workspace.documents[document_index].document
            command = move_split(document, target, delta)
            if command is not None:
                self._execute_structure(
                    document_index,
                    command,
                    ("split", document_index, target.split_id, None),
                    "Moved Split",
                )

        def _move_block(self, delta: int) -> None:
            selection = self._structure_selection()
            if selection is None or selection[0] != "block" or self.workspace is None:
                return
            _, document_index, target = selection
            document = self.workspace.documents[document_index].document
            command = move_block(document, target, delta)
            if command is not None:
                self._execute_structure(
                    document_index,
                    command,
                    ("block", document_index, target.split_id, target.block_id),
                    "Moved Block",
                )

        def _edit_block_timing(self) -> None:
            selection = self._structure_selection()
            if selection is None or selection[0] != "block" or self.workspace is None:
                return
            _, document_index, target = selection
            document = self.workspace.documents[document_index].document
            split = next(
                item for item in document.splits if item.stable_id == target.split_id
            )
            block = next(
                item for item in split.blocks if item.stable_id == target.block_id
            )
            flattened = [item for candidate in document.splits for item in candidate.blocks]
            block_index = flattened.index(block)
            previous_end = None
            if block_index:
                previous = flattened[block_index - 1]
                previous_end = float(previous.start_time.value)
                if float(previous.bpm.value) > 0 and int(previous.beat_split.value) > 0:
                    previous_end += len(previous.rows) * 60_000.0 / (
                        float(previous.bpm.value) * int(previous.beat_split.value)
                    )
            dialog = BlockTimingDialog(
                BlockTimingValues.from_block(block), self,
                previous_end_ms=previous_end,
                advanced=self.advanced_split_timing_action.isChecked(),
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                command = dialog.values().command(block.stable_id)
            except ValueError as exc:
                QMessageBox.critical(self, "Invalid Block timing", str(exc))
                return
            self._execute_structure(
                document_index,
                command,
                ("block", document_index, target.split_id, target.block_id),
                "Updated Block timing",
            )

        def _shift_start_times(self) -> None:
            document_index = self._current_document_index()
            if document_index is None:
                return
            delta, accepted = QInputDialog.getDouble(
                self,
                "Shift all Start Times",
                "Milliseconds to add to every Block Start Time:",
                0.0,
                -1_000_000_000.0,
                1_000_000_000.0,
                4,
            )
            if not accepted or delta == 0.0:
                return
            widget = self.tabs.currentWidget()
            if not isinstance(widget, TimelineWidget):
                return
            try:
                updated = self.sessions[document_index].execute(
                    ShiftBlockStartTimes(delta)
                )
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Cannot shift Start Times", str(exc))
                return
            self._apply_document(document_index, widget, updated)
            self.statusBar().showMessage(
                f"Shifted all Start Times by {delta:g} ms", 5000
            )

        def _metadata_context(self):
            if self.workspace is None:
                return None
            item = self.tree.currentItem()
            if item is None:
                return None
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if not payload:
                return None
            kind, document_index, split_id, block_id = payload
            if document_index < 0:
                return None
            document = self.sessions[document_index].current
            if kind in ("document", "header"):
                return document_index, MetadataScope.HEADER, document.stable_id, payload
            if kind == "split":
                return document_index, MetadataScope.SPLIT, split_id, payload
            if kind == "block":
                return document_index, MetadataScope.DIVISION, block_id, payload
            return None

        def _edit_metadata(self, *, brain_only: bool = False) -> None:
            context = self._metadata_context()
            if context is None:
                return
            document_index, scope, owner_id, tree_selection = context
            if brain_only and scope is not MetadataScope.DIVISION:
                QMessageBox.information(
                    self,
                    "Choose a Block",
                    "Brain Shower fields are Division metadata owned by a Block.",
                )
                return
            document = self.sessions[document_index].current
            dialog = MetadataCollectionDialog(
                metadata_drafts(metadata_owner(document, owner_id)),
                document.profile,
                scope,
                self,
                brain_only=brain_only,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            command = ReplaceMetadataCollection(owner_id, dialog.drafts())
            self._open_document(document_index)
            widget = self.tabs.currentWidget()
            if not isinstance(widget, TimelineWidget):
                return
            try:
                updated = self.sessions[document_index].execute(command)
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Cannot edit metadata", str(exc))
                return
            self._apply_document(
                document_index,
                widget,
                updated,
                tree_selection=tree_selection,
            )
            self._inspect(*tree_selection)
            self.statusBar().showMessage("Updated metadata as one undo step", 5000)

        @staticmethod
        def _parse_u32(text: str) -> int:
            value = int(text.strip(), 0)
            if not 0 <= value <= 0xFFFFFFFF:
                raise ValueError("value must fit unsigned 32-bit storage")
            return value

        def _edit_trailer_string(self) -> None:
            document_index = self._current_document_index()
            if document_index is None:
                return
            document = self.sessions[document_index].current
            projection = project_trailer_strings(document)
            strings = tuple(item for item in projection.strings if item.authorable)
            if not strings:
                QMessageBox.information(
                    self,
                    "No safe trailer strings",
                    "No known trailer offset currently resolves to an editable UTF-8 string.",
                )
                return
            labels = [
                f"0x{item.metadata_id:08X} / variant {item.variant_index} / +{item.offset}: {item.text}"
                for item in strings
            ]
            selected, accepted = QInputDialog.getItem(
                self, "Edit trailer string", "Referenced field:", labels, 0, False
            )
            if not accepted:
                return
            target = strings[labels.index(selected)]
            text, accepted = QInputDialog.getText(
                self,
                "Same-size trailer edit",
                f"UTF-8 text ({len(target.raw)} bytes exactly; relocation is disabled):",
                text=target.text,
            )
            if not accepted:
                return
            widget = self.tabs.currentWidget()
            if not isinstance(widget, TimelineWidget):
                return
            try:
                updated = self.sessions[document_index].execute(
                    SetTrailerStringSameSize(target.metadata_stable_id, text)
                )
            except (UnicodeEncodeError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Cannot edit trailer string", str(exc))
                return
            self._apply_document(document_index, widget, updated)
            self.statusBar().showMessage("Updated same-size trailer string", 5000)

        def _confirm_batch(self, plan) -> bool:
            if not plan.commands:
                QMessageBox.information(
                    self, "Nothing to change", "No chart matches this batch operation."
                )
                return False
            lines = [f"{item.path.name}: {item.summary}" for item in plan.commands[:30]]
            if len(plan.commands) > 30:
                lines.append(f"…and {len(plan.commands) - 30} more")
            if plan.skipped:
                lines.append(
                    f"Skipped {len(plan.skipped)} document(s) without a matching field."
                )
            answer = QMessageBox.question(
                self,
                "Confirm folder batch",
                plan.label + "\n\n" + "\n".join(lines),
                QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            return answer == QMessageBox.StandardButton.Apply

        def _execute_batch(self, plan) -> None:
            if not self._confirm_batch(plan):
                return
            updated_indices = set()
            try:
                # Prove every command against the current snapshots before any
                # command stack advances, so rejection cannot leave a
                # misleading half-applied folder batch in memory.
                for item in plan.commands:
                    item.command.apply(self.sessions[item.document_index].current)
                for item in plan.commands:
                    updated = self.sessions[item.document_index].execute(item.command)
                    entry = self.workspace.documents[item.document_index].with_document(
                        updated
                    )
                    self.workspace = self.workspace.replace_document(entry)
                    updated_indices.add(item.document_index)
            except (ValueError, ModelInvariantError) as exc:
                QMessageBox.critical(self, "Batch failed", str(exc))
                return
            for widget, document_index in tuple(self.widget_documents.items()):
                if document_index not in updated_indices:
                    continue
                old_snapshot = widget.snapshot
                snapshot = create_authoring_snapshot(
                    self.sessions[document_index].current
                )
                for split_id, block_id in old_snapshot.active_blocks:
                    try:
                        snapshot = snapshot.with_active_block(split_id, block_id)
                    except KeyError:
                        pass
                widget.set_snapshot(snapshot)
                entry = self.workspace.documents[document_index]
                self.tabs.setTabText(self.tabs.indexOf(widget), entry.path.name + " *")
            self._populate_tree()
            self._populate_diagnostics()
            self._populate_routes()
            active = self.tabs.currentWidget()
            if isinstance(active, TimelineWidget):
                self._set_metronome_snapshot(active.snapshot)
            self._refresh_edit_actions()
            self.statusBar().showMessage(
                f"Applied batch to {len(updated_indices)} document(s); Save All is still required",
                7000,
            )

        def _batch_header_metadata(self) -> None:
            if self.workspace is None:
                return
            id_text, accepted = QInputDialog.getText(
                self,
                "Batch header metadata",
                "Metadata ID (decimal or 0x hexadecimal):",
            )
            if not accepted:
                return
            value_text, accepted = QInputDialog.getText(
                self, "Batch header metadata", "Value (decimal or 0x hexadecimal):"
            )
            if not accepted:
                return
            labels = (
                "Upsert last — replace last duplicate or append",
                "Replace all existing — never append",
                "Append — always create another entry",
            )
            selected, accepted = QInputDialog.getItem(
                self, "Duplicate policy", "Operation:", labels, 0, False
            )
            if not accepted:
                return
            modes = (
                MetadataBatchMode.UPSERT_LAST,
                MetadataBatchMode.REPLACE_ALL,
                MetadataBatchMode.APPEND,
            )
            try:
                plan = plan_batch_header_metadata(
                    self.workspace,
                    self._parse_u32(id_text),
                    self._parse_u32(value_text),
                    mode=modes[labels.index(selected)],
                )
            except ValueError as exc:
                QMessageBox.critical(self, "Invalid metadata", str(exc))
                return
            self._execute_batch(plan)

        def _batch_shift_start_times(self) -> None:
            if self.workspace is None:
                return
            delta, accepted = QInputDialog.getDouble(
                self,
                "Batch Start Time shift",
                "Milliseconds to add to every Block in every non-Lightmap chart:",
                0.0,
                -1_000_000_000.0,
                1_000_000_000.0,
                4,
            )
            if accepted and delta != 0.0:
                self._execute_batch(plan_batch_shift_start_times(self.workspace, delta))

        def _export_nfo_mirror(self) -> None:
            document_index = self._current_document_index()
            if document_index is None or self.workspace is None:
                return
            entry = self.workspace.documents[document_index]
            default = self.workspace.root / (entry.path.stem + ".NFO")
            selected, _ = QFileDialog.getSaveFileName(
                self,
                "Compare / export NFO mirror",
                str(default),
                "NX20 mission mirror (*.NFO);;NX20 chart (*.NX)",
            )
            if not selected:
                return
            target = Path(selected)
            document = self.sessions[document_index].current
            details = [f"Source: {entry.path.name}", f"Target: {target}"]
            if target.exists():
                try:
                    comparison = compare_mirror(document, target)
                except (OSError, WorkspaceError, ValueError) as exc:
                    QMessageBox.critical(self, "Cannot compare mirror", str(exc))
                    return
                details.append(
                    "Binary identical"
                    if comparison.binary_identical
                    else "Mirror differs"
                )
                details.extend(
                    f"• {change.path}" for change in comparison.structural_changes[:20]
                )
                if len(comparison.structural_changes) > 20:
                    details.append(
                        f"• …and {len(comparison.structural_changes) - 20} more"
                    )
            else:
                details.append("Target does not exist; it will be created.")
            answer = QMessageBox.question(
                self,
                "Confirm explicit mirror export",
                "\n".join(details),
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Save:
                return
            plan = plan_mirror_export(document, target)
            if not plan.is_ready:
                QMessageBox.critical(
                    self,
                    "Mirror export blocked",
                    "\n".join(f"{item.code}: {item.message}" for item in plan.issues),
                )
                return
            try:
                execute_save_plan(plan)
            except (OSError, WorkspaceError) as exc:
                QMessageBox.critical(self, "Mirror export failed", str(exc))
                return
            self.statusBar().showMessage(
                f"Exported explicit mirror: {target.name}", 6000
            )

        def _inspect_ids(
            self, document_index: int, split_id: int, block_id: int
        ) -> None:
            self._inspect("block", document_index, split_id, block_id)

        def _inspect(
            self,
            kind: str,
            document_index: int,
            split_id: int | None,
            block_id: int | None,
        ) -> None:
            document = self.workspace.documents[document_index].document
            rows: list[tuple[str, str, str, str]] = []

            def metadata_rows(entries, scope: MetadataScope, label: str):
                for entry in entries:
                    meta_id = int(entry.meta_id.value)
                    definition = metadata_definition(document.profile, scope, meta_id)
                    name = definition.label if definition else "Unknown"
                    value = (
                        definition.display_value(int(entry.value.value))
                        if definition
                        else str(entry.value.value)
                    )
                    yield (f"{label} — {name}", str(meta_id), value, entry.value.hex)

            if kind in ("document", "header"):
                rows.extend(
                    metadata_rows(
                        document.header_metadata,
                        MetadataScope.HEADER,
                        "Header metadata",
                    )
                )
                for item in project_trailer_strings(document).strings:
                    value = (
                        item.text if item.text is not None else item.raw.hex().upper()
                    )
                    rows.append(
                        (
                            f"Trailer string — base {item.base_field_id}, variant {item.variant_index}",
                            f"0x{item.metadata_id:08X}",
                            value,
                            f"offset +{item.offset}",
                        )
                    )
            if kind == "split":
                split = next(
                    split for split in document.splits if split.stable_id == split_id
                )
                rows.extend(
                    metadata_rows(split.metadata, MetadataScope.SPLIT, "Split metadata")
                )
                rows.extend(
                    [
                        (
                            "Raw select",
                            "—",
                            str(split.raw_select.value),
                            split.raw_select.hex,
                        ),
                        (
                            "Raw brain",
                            "—",
                            str(split.raw_brain.value),
                            split.raw_brain.hex,
                        ),
                    ]
                )
            if kind == "block":
                split = next(
                    split for split in document.splits if split.stable_id == split_id
                )
                block = next(
                    block for block in split.blocks if block.stable_id == block_id
                )
                rows.extend(
                    [
                        ("BPM", "—", f"{block.bpm.value:g}", block.bpm.hex),
                        (
                            "Start Time (ms)",
                            "—",
                            f"{block.start_time.value:g}",
                            block.start_time.hex,
                        ),
                        ("Scroll", "—", f"{block.scroll.value:g}", block.scroll.hex),
                        (
                            "Offset / Delay",
                            "—",
                            f"{block.offset_or_delay.value:g}",
                            block.offset_or_delay.hex,
                        ),
                        (
                            "Speed / Freeze",
                            "—",
                            f"{block.speed_or_freeze.value:g}",
                            block.speed_or_freeze.hex,
                        ),
                        (
                            "Beat split",
                            "—",
                            str(block.beat_split.value),
                            block.beat_split.hex,
                        ),
                        (
                            "Beat measure",
                            "—",
                            str(block.beat_measure.value),
                            block.beat_measure.hex,
                        ),
                        (
                            "Smooth Speed",
                            "—",
                            str(block.smooth_speed.value),
                            block.smooth_speed.hex,
                        ),
                        (
                            "Raw Flag",
                            "—",
                            str(block.raw_flag.value),
                            block.raw_flag.hex,
                        ),
                    ]
                )
                rows.extend(
                    metadata_rows(
                        block.divisions, MetadataScope.DIVISION, "Division metadata"
                    )
                )
                brain = next(
                    (
                        item
                        for item in project_brain_shower(document)
                        if item.block_id == block.stable_id
                    ),
                    None,
                )
                if brain is not None:
                    for label, value in (
                        ("Brain opcode", brain.opcode),
                        ("Brain instruction sprite", brain.instruction_sprite),
                        ("Brain question count", brain.question_count),
                        ("Brain answer count", brain.answer_count),
                        ("Brain variant", brain.variant),
                        ("Brain preset", brain.preset),
                        ("Brain correct range", brain.correct_range),
                        ("Brain wrong range", brain.wrong_range),
                    ):
                        if value is not None:
                            rows.append((label, "—", str(value), "derived"))
            self.inspector.setRowCount(len(rows))
            for row_index, values in enumerate(rows):
                for column_index, value in enumerate(values):
                    self.inspector.setItem(
                        row_index, column_index, QTableWidgetItem(value)
                    )
            self.inspector.resizeColumnsToContents()
            self.side_tabs.setCurrentWidget(self.inspector)

    application = QApplication(sys.argv)
    application.setApplicationName("StepNX Studio")
    window = MainWindow()
    window.show()
    if folder is not None:
        window.load_folder(folder)
    return application.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the StepNX Studio NX20 editor")
    parser.add_argument("folder", nargs="?", type=Path, help="chart folder to open")
    parser.add_argument(
        "--profile",
        choices=("nxa-native", "fiesta2", "prime2", "nxa-step5-patched"),
        default="nxa-native",
        help="engine semantics used for typed authoring and validation",
    )
    args = parser.parse_args(argv)
    return _run(args.folder, args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
