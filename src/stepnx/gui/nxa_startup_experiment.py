from __future__ import annotations

import math


# These are the candidate timeline corrections inferred from the NXA/libmad
# startup corpus. They are deliberately presets, not a production classifier.
# The experiment exists to validate the timing model before we spend effort on
# reproducing libmad recovery from arbitrary MPEG bytes.
NXA_STARTUP_CORRECTION_PRESETS_MS = (
    0.0,
    24.0,
    32.0,
    40.0,
    48.0,
    -144.0,
)


def effective_audio_offset_ms(
    manual_offset_ms: float,
    startup_correction_ms: float,
    *,
    enabled: bool,
) -> float:
    """Compose the existing session offset with the experimental correction."""

    manual = float(manual_offset_ms)
    correction = float(startup_correction_ms)
    if not math.isfinite(manual) or not math.isfinite(correction):
        raise ValueError("audio offsets must be finite")
    return manual + correction if enabled else manual


def _apply_window_alignment(window, *, announce: bool = False) -> None:
    """Apply the experiment through the Studio's existing AudioAlignment path.

    This intentionally changes no chart data and rewrites no audio. Timeline,
    waveform, preview and metronome already consume window.audio_alignment, so
    one composed session mapping is enough for an A/B experiment.
    """

    from stepnx.authoring.audio import AudioAlignment
    from stepnx.gui.timeline_widget import TimelineWidget

    enabled = bool(getattr(window, "_nxa_startup_experiment_enabled", False))
    correction = float(getattr(window, "_nxa_startup_correction_ms", 0.0))
    manual = float(window.audio_offset.value())
    effective = effective_audio_offset_ms(
        manual,
        correction,
        enabled=enabled,
    )
    window.audio_alignment = AudioAlignment(effective)

    for index in range(window.tabs.count()):
        widget = window.tabs.widget(index)
        if isinstance(widget, TimelineWidget):
            widget.set_waveform(window.waveform, window.audio_alignment)

    window._audio_position_changed(window.audio_position.value())
    if announce:
        state = "enabled" if enabled else "disabled"
        applied = correction if enabled else 0.0
        window.statusBar().showMessage(
            "NXA startup timing experiment "
            f"{state}: manual {manual:+.3f} ms, startup {applied:+.3f} ms, "
            f"total {effective:+.3f} ms",
            8000,
        )


def _audio_menu(window):
    for action in window.menuBar().actions():
        if action.text().replace("&", "").strip().casefold() == "audio":
            return action.menu()
    return None


def install_nxa_startup_experiment(window) -> None:
    """Install a disposable manual A/B harness for NXA startup timing.

    The production question is whether libmad's startup recovery explains the
    audible/chart alignment in NXA. This branch does *not* pretend that question
    is already answered. The user chooses one measured correction class (or a
    custom value), while the Studio composes it with the normal manual session
    offset. Disabled is the exact pre-experiment behavior.
    """

    if getattr(window, "_nxa_startup_experiment_installed", False):
        return
    window._nxa_startup_experiment_installed = True
    window._nxa_startup_experiment_enabled = False
    window._nxa_startup_correction_ms = 0.0

    menu = _audio_menu(window)
    if menu is None:
        return

    from PySide6.QtGui import QActionGroup
    from PySide6.QtWidgets import QInputDialog

    menu.addSeparator()
    experiment_menu = menu.addMenu("NXA startup timing (experimental)")
    experiment_menu.setToolTipsVisible(True)
    experiment_menu.setToolTip(
        "Session-only A/B harness. It never edits NX data or rewrites the AUD/MP3."
    )

    group = QActionGroup(window)
    group.setExclusive(True)
    window._nxa_startup_experiment_group = group
    window._nxa_startup_experiment_menu = experiment_menu
    window._nxa_startup_experiment_actions = {}

    disabled = experiment_menu.addAction("Disabled")
    disabled.setCheckable(True)
    disabled.setChecked(True)
    disabled.setData(None)
    group.addAction(disabled)

    preset_labels = {
        0.0: "0 ms (clean startup class)",
        24.0: "+24 ms",
        32.0: "+32 ms",
        40.0: "+40 ms",
        48.0: "+48 ms",
        -144.0: "-144 ms (F08 class)",
    }
    for correction in NXA_STARTUP_CORRECTION_PRESETS_MS:
        action = experiment_menu.addAction(preset_labels[correction])
        action.setCheckable(True)
        action.setData(correction)
        group.addAction(action)
        window._nxa_startup_experiment_actions[correction] = action

    def choose_preset(action) -> None:
        correction = action.data()
        if correction is None:
            window._nxa_startup_experiment_enabled = False
            window._nxa_startup_correction_ms = 0.0
        else:
            window._nxa_startup_experiment_enabled = True
            window._nxa_startup_correction_ms = float(correction)
        _apply_window_alignment(window, announce=True)

    group.triggered.connect(choose_preset)

    experiment_menu.addSeparator()
    custom_action = experiment_menu.addAction("Custom correction...")

    def choose_custom() -> None:
        current = float(getattr(window, "_nxa_startup_correction_ms", 0.0))
        value, accepted = QInputDialog.getDouble(
            window,
            "NXA startup timing experiment",
            "Additional startup correction (ms):",
            current,
            -1000.0,
            1000.0,
            3,
        )
        if not accepted:
            return
        group.setExclusive(False)
        for action in group.actions():
            action.setChecked(False)
        group.setExclusive(True)
        window._nxa_startup_experiment_enabled = True
        window._nxa_startup_correction_ms = float(value)
        _apply_window_alignment(window, announce=True)

    custom_action.triggered.connect(choose_custom)
    window._nxa_startup_custom_action = custom_action

    # MainWindow's original slot remains authoritative for the user-facing
    # manual offset. This second connection runs afterwards and composes the
    # experimental term, keeping the existing spin box semantics unchanged.
    window.audio_offset.valueChanged.connect(
        lambda value: _apply_window_alignment(window, announce=False)
    )
