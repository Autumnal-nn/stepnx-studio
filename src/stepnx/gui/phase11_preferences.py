from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMessageBox

from stepnx.authoring.glyphs import VisualPackError, load_visual_pack


_VISUAL_PACK_KEY = "assets/visual_pack"
_NOTESKIN_KEY = "assets/noteskin"


def _settings() -> QSettings:
    # Keep editor preferences outside chart folders. The folder remains the
    # complete project/runtime unit and never receives a StepNX sidecar merely
    # because the user chose private rendering assets.
    return QSettings("Autumnal-nn", "StepNX Studio")


def _apply_visual_pack(window, path: Path, *, report_error: bool) -> bool:
    try:
        pack = load_visual_pack(path)
    except VisualPackError as exc:
        if report_error:
            QMessageBox.critical(window, "Invalid visual pack", str(exc))
        return False
    window.pack = pack
    for index in range(window.tabs.count()):
        widget = window.tabs.widget(index)
        if hasattr(widget, "set_visual_pack"):
            widget.set_visual_pack(pack)
    window.statusBar().showMessage(f"Loaded local visual pack: {pack.name}", 5000)
    return True


def _restore_preferences(window) -> None:
    settings = _settings()

    visual = settings.value(_VISUAL_PACK_KEY, "", type=str)
    if visual:
        path = Path(visual)
        if not _apply_visual_pack(window, path, report_error=False):
            window.statusBar().showMessage(
                f"Saved visual pack is unavailable: {path}", 8000
            )

    noteskin = settings.value(_NOTESKIN_KEY, "", type=str)
    if noteskin:
        path = Path(noteskin)
        before = getattr(getattr(window, "noteskin", None), "root", None)
        window._load_noteskin(path, report_error=False)
        after = getattr(getattr(window, "noteskin", None), "root", None)
        try:
            restored = after is not None and Path(after).resolve() == path.resolve()
        except OSError:
            restored = False
        if not restored:
            # _load_noteskin deliberately preserves the previous valid pack on
            # failure, so distinguish that fallback from a successful restore.
            if before == after:
                window.statusBar().showMessage(
                    f"Saved noteskin is unavailable: {path}", 8000
                )


def _choose_visual_pack(window) -> None:
    current = getattr(getattr(window, "pack", None), "root", None)
    selected = QFileDialog.getExistingDirectory(
        window,
        "Select StepNX visual pack",
        "" if current is None else str(current),
    )
    if not selected:
        return
    path = Path(selected).resolve()
    if _apply_visual_pack(window, path, report_error=True):
        settings = _settings()
        settings.setValue(_VISUAL_PACK_KEY, str(path))
        settings.sync()


def _choose_noteskin(window) -> None:
    current = getattr(getattr(window, "noteskin", None), "root", None)
    selected = QFileDialog.getExistingDirectory(
        window,
        "Select local noteskin folder",
        "" if current is None else str(current),
    )
    if not selected:
        return
    path = Path(selected).resolve()
    window._load_noteskin(path, report_error=True)
    loaded = getattr(getattr(window, "noteskin", None), "root", None)
    try:
        success = loaded is not None and Path(loaded).resolve() == path
    except OSError:
        success = False
    if success:
        settings = _settings()
        settings.setValue(_NOTESKIN_KEY, str(path))
        settings.sync()


def _replace_action(window, label: str, callback) -> bool:
    action = next(
        (item for item in window.findChildren(QAction) if item.text() == label),
        None,
    )
    if action is None:
        return False
    try:
        action.triggered.disconnect()
    except (RuntimeError, TypeError):
        pass
    action.triggered.connect(lambda *_: callback(window))
    return True


def install_phase11_preferences(window) -> None:
    if getattr(window, "_phase11_preferences_installed", False):
        return
    window._phase11_preferences_installed = True

    _restore_preferences(window)
    _replace_action(window, "Load local visual pack…", _choose_visual_pack)
    _replace_action(window, "Load local noteskin atlases…", _choose_noteskin)
