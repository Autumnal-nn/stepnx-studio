from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QStyleFactory

from stepnx.authoring.glyphs import VisualPackError, load_visual_pack


_VISUAL_PACK_KEY = "assets/visual_pack"
_NOTESKIN_KEY = "assets/noteskin"
_DARK_MODE_KEY = "appearance/dark_mode"


def _settings() -> QSettings:
    # Keep editor preferences outside chart folders. The folder remains the
    # complete project/runtime unit and never receives a StepNX sidecar merely
    # because the user chose private rendering assets.
    return QSettings("Autumnal-nn", "StepNX Studio")


def _dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(127, 127, 127),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(127, 127, 127),
    )
    return palette


def _apply_dark_mode(window, enabled: bool) -> None:
    application = QApplication.instance()
    if application is None:
        return

    if enabled:
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            application.setStyle(fusion)
        application.setPalette(_dark_palette())
    else:
        style_name = getattr(window, "_phase11_system_style_name", "")
        style = QStyleFactory.create(style_name) if style_name else None
        if style is not None:
            application.setStyle(style)
        palette = getattr(window, "_phase11_system_palette", None)
        if palette is not None:
            application.setPalette(palette)


def _dark_mode_changed(window, checked: bool) -> None:
    _apply_dark_mode(window, bool(checked))
    settings = _settings()
    settings.setValue(_DARK_MODE_KEY, bool(checked))
    settings.sync()


def _install_dark_mode_toggle(window) -> None:
    application = QApplication.instance()
    if application is None:
        return

    window._phase11_system_style_name = application.style().objectName()
    window._phase11_system_palette = QPalette(application.palette())

    action = window.settings_menu.addAction("Dark Mode")
    action.setCheckable(True)
    enabled = _settings().value(_DARK_MODE_KEY, False, type=bool)
    action.setChecked(enabled)
    action.toggled.connect(lambda checked: _dark_mode_changed(window, checked))
    window.phase11_dark_mode_action = action
    _apply_dark_mode(window, enabled)


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

    _install_dark_mode_toggle(window)
    _restore_preferences(window)
    _replace_action(window, "Load local visual pack…", _choose_visual_pack)
    _replace_action(window, "Load local noteskin atlases…", _choose_noteskin)
