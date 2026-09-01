from __future__ import annotations

import argparse
from pathlib import Path


def main(argv=None) -> int:
    from stepnx.gui.phase11_profile_gate import available_profiles, default_profile

    parser = argparse.ArgumentParser(description="Launch the StepNX Studio NX20 editor")
    parser.add_argument("folder", nargs="?", type=Path, help="chart folder to open")
    parser.add_argument(
        "--profile",
        choices=available_profiles(),
        default=default_profile(),
        help="engine semantics used for typed authoring and validation",
    )
    args = parser.parse_args(argv)

    # app._run imports these classes lazily. Install the extended authoring
    # adapters before delegating to the base application runtime.
    try:
        from PySide6.QtWidgets import QMainWindow
    except ImportError:
        from stepnx.gui.app import _run as base_run
        return base_run(args.folder, args.profile)

    import stepnx.gui.timeline_widget as timeline_module
    import stepnx.gui.timing_dialog as timing_module
    import stepnx.gui.preview_widget as preview_module
    from stepnx.gui.phase10_install import install_phase10
    from stepnx.gui.phase10_timeline import Phase10TimelineWidget
    from stepnx.gui.phase10_timing import Phase10BlockTimingDialog
    from stepnx.gui.phase10_preview import Phase10GameplayPreviewWidget
    from stepnx.gui.phase11_audio_picker import install_phase11_audio_picker
    from stepnx.gui.phase11_audio_staging_cleanup import (
        install_phase11_audio_staging_cleanup,
        install_phase11_audio_staging_transport,
    )
    from stepnx.gui.phase11_authoring_polish import install_phase11_authoring_polish
    from stepnx.gui.phase11_fast_notes import install_phase11_fast_note_index
    from stepnx.gui.phase11_feedback import install_phase11_feedback
    from stepnx.gui.phase11_import import install_phase11_import
    from stepnx.gui.phase11_linux_metronome import install_phase11_linux_metronome
    from stepnx.gui.phase11_nx10_materialization import install_phase11_nx10_materialization
    from stepnx.gui.phase11_preferences import install_phase11_preferences
    from stepnx.gui.phase11_profile_gate import install_phase11_profile_gate
    from stepnx.gui.phase11_render_performance import install_phase11_render_performance
    from stepnx.gui.phase11_split_cascade import install_phase11_split_cascade
    from stepnx.gui.phase11_state_guard import install_phase11_state_guard
    from stepnx.gui.phase11_trailer_edit import install_phase11_trailer_edit
    from stepnx.gui.phase11_ui_polish import install_phase11_ui_polish
    from stepnx.gui.phase11_waveform import install_phase11_waveform
    from stepnx.gui.phase11_waveform_precision import install_phase11_waveform_precision
    from stepnx.gui.phase11_workspace import install_phase11_workspace_tools
    from stepnx.gui.phase12_editor_note_visuals import install_phase12_editor_note_visuals
    from stepnx.gui.phase12_split_header import install_phase12_split_header

    timeline_module.TimelineWidget = Phase10TimelineWidget
    timing_module.BlockTimingDialog = Phase10BlockTimingDialog
    preview_module.GameplayPreviewWidget = Phase10GameplayPreviewWidget

    # AudioTransport connects its cleanup slot while MainWindow is constructed,
    # so install the retryable Windows-safe implementation before base_run()
    # creates the window.
    install_phase11_audio_staging_transport()

    original_show = QMainWindow.show

    def show_with_phase10(self, *args, **kwargs):
        if self.windowTitle() == "StepNX Studio":
            install_phase10(self)
            install_phase11_linux_metronome(self)
            install_phase11_profile_gate(self)
            install_phase11_import(self)
            install_phase11_workspace_tools(self)
            install_phase12_split_header(self)
            install_phase11_state_guard(self)
            install_phase11_waveform(self)
            install_phase11_audio_staging_cleanup(self)
            install_phase11_audio_picker(self)
            install_phase11_waveform_precision(self)
            install_phase11_authoring_polish(self)
            install_phase12_editor_note_visuals(self)
            install_phase11_trailer_edit(self)
            install_phase11_nx10_materialization(self)
            install_phase11_preferences(self)
            install_phase11_feedback(self)
            install_phase11_split_cascade(self)
            install_phase11_fast_note_index(self)
            install_phase11_render_performance(self)
            install_phase11_ui_polish(self)
        return original_show(self, *args, **kwargs)

    QMainWindow.show = show_with_phase10
    try:
        from stepnx.gui.app import _run as base_run
        return base_run(args.folder, args.profile)
    finally:
        QMainWindow.show = original_show
