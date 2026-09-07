from __future__ import annotations

import math
from pathlib import Path

from stepnx.authoring.nxa_startup import (
    NxaStartupAnalysis,
    NxaStartupError,
    analyze_nxa_mp3_startup,
)

_NXA_PROFILES = frozenset({"nxa-native", "nxa-step5-patched"})
_MP3_SUFFIXES = frozenset({".mp3"})


def effective_nxa_audio_offset_ms(
    manual_offset_ms: float,
    analysis: NxaStartupAnalysis | None,
    *,
    nxa_profile: bool,
) -> float:
    manual = float(manual_offset_ms)
    if not math.isfinite(manual):
        raise ValueError("audio offset must be finite")
    startup = analysis.offset_ms if nxa_profile and analysis is not None else 0.0
    return manual + startup


def _selected_profile(window) -> str:
    getter = getattr(window, "_selected_profile", None)
    if callable(getter):
        try:
            return str(getter())
        except (RuntimeError, TypeError, ValueError):
            pass
    for value, action in getattr(window, "profile_actions", {}).items():
        if action.isChecked():
            return str(value)
    return ""


def _profile_uses_nxa_startup(window) -> bool:
    return _selected_profile(window) in _NXA_PROFILES


def _analyze_playback_source(window) -> tuple[NxaStartupAnalysis | None, str | None]:
    if not _profile_uses_nxa_startup(window):
        return None, None
    source = getattr(window.audio_transport, "playback_source", None)
    if source is None:
        return None, None
    path = Path(source)
    if path.suffix.casefold() not in _MP3_SUFFIXES:
        return None, None
    try:
        payload = path.read_bytes()
        return analyze_nxa_mp3_startup(payload), None
    except (OSError, NxaStartupError, ValueError) as exc:
        return None, str(exc)


def _apply_window_alignment(window, *, announce: bool = False) -> None:
    from stepnx.authoring.audio import AudioAlignment
    from stepnx.gui.timeline_widget import TimelineWidget

    analysis = getattr(window, "_nxa_startup_analysis", None)
    effective = effective_nxa_audio_offset_ms(
        window.audio_offset.value(),
        analysis,
        nxa_profile=_profile_uses_nxa_startup(window),
    )
    window.audio_alignment = AudioAlignment(effective)

    for index in range(window.tabs.count()):
        widget = window.tabs.widget(index)
        if isinstance(widget, TimelineWidget):
            widget.set_waveform(window.waveform, window.audio_alignment)

    window._audio_position_changed(window.audio_position.value())
    if not announce:
        return

    error = getattr(window, "_nxa_startup_analysis_error", None)
    if analysis is not None and _profile_uses_nxa_startup(window):
        window.statusBar().showMessage(
            "NXA startup timing: "
            f"{analysis.net_source_lead_samples:+d} samples / "
            f"{analysis.offset_ms:+.3f} ms; "
            f"effective audio offset {effective:+.3f} ms",
            8000,
        )
    elif error and _profile_uses_nxa_startup(window):
        window.statusBar().showMessage(
            "NXA startup timing unavailable; using manual audio offset only: "
            f"{error}",
            8000,
        )


def _refresh_analysis(window, *, announce: bool) -> None:
    analysis, error = _analyze_playback_source(window)
    window._nxa_startup_analysis = analysis
    window._nxa_startup_analysis_error = error
    _apply_window_alignment(window, announce=announce)


def install_nxa_audio_alignment(window) -> None:
    """Apply NXA/libmad startup displacement automatically for loaded MP3/AUD.

    AUD playback is already staged by ``AudioTransport`` as the exact decoded
    MP3 bytes. Reading ``playback_source`` therefore analyzes the same payload
    handed to Qt/FFmpeg, without decoding the AUD a second time. The ordinary
    Audio Offset spin box remains a session-only additive override.
    """

    if getattr(window, "_nxa_audio_alignment_installed", False):
        return
    window._nxa_audio_alignment_installed = True
    window._nxa_startup_analysis = None
    window._nxa_startup_analysis_error = None

    original_load_audio = window._load_audio

    def load_audio_with_nxa_alignment(path: Path) -> None:
        original_load_audio(path)
        _refresh_analysis(window, announce=True)

    window._load_audio = load_audio_with_nxa_alignment

    # MainWindow's original handler runs first and restores the manual value;
    # this second connection composes the automatic NXA term afterwards.
    window.audio_offset.valueChanged.connect(
        lambda _value: _apply_window_alignment(window, announce=False)
    )

    for action in getattr(window, "profile_actions", {}).values():
        action.triggered.connect(
            lambda _checked=False: _refresh_analysis(window, announce=False)
        )

    # A folder passed on the command line may have loaded audio before show(),
    # so consume an already-staged playback source during installation too.
    _refresh_analysis(window, announce=False)
