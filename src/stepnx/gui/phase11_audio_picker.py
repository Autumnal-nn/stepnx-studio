from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog


_AUDIO_DIALOG_FILTER = (
    "Audio ("
    "*.mp3 *.MP3 "
    "*.aud *.AUD "
    "*.a *.A "
    "*.wav *.WAV "
    "*.flac *.FLAC "
    "*.ogg *.OGG "
    "*.mp2 *.MP2"
    ");;AUD (*.aud *.AUD *.a *.A);;All files (*)"
)


def _audio_dialog_options(platform: str | None = None):
    """Use Qt's own file dialog on Linux so name globs stay deterministic."""

    selected = sys.platform if platform is None else platform
    if selected.startswith("linux"):
        return QFileDialog.Option.DontUseNativeDialog
    return QFileDialog.Option(0)


def _choose_audio(window) -> None:
    initial = str(window.workspace.root) if window.workspace is not None else ""
    selected, _ = QFileDialog.getOpenFileName(
        window,
        "Select chart audio",
        initial,
        _AUDIO_DIALOG_FILTER,
        options=_audio_dialog_options(),
    )
    if selected:
        window._load_audio(Path(selected))


def install_phase11_audio_picker(window) -> None:
    """Make the chart-audio picker portable across case-sensitive desktops."""

    action = next(
        (
            item
            for item in window.findChildren(QAction)
            if item.text() == "Select audio…"
        ),
        None,
    )
    if action is None:
        return
    try:
        action.triggered.disconnect()
    except (RuntimeError, TypeError):
        pass
    action.triggered.connect(lambda *_args: _choose_audio(window))
