from __future__ import annotations

import math
from pathlib import Path

from stepnx.authoring.mp3_gapless import (
    Mp3GaplessAnalysis,
    analyze_ffmpeg_lame_gapless,
)
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
    gapless: Mp3GaplessAnalysis | None = None,
    *,
    nxa_profile: bool,
    canonical_pcm=None,
) -> float:
    manual = float(manual_offset_ms)
    if not math.isfinite(manual):
        raise ValueError("audio offset must be finite")
    if not nxa_profile:
        return manual
    if canonical_pcm is not None:
        # The pinned decoder retains every source frame and all priming. The
        # NXA output-rate sample ledger is authoritative; FFmpeg trims do not
        # participate in this path.
        return manual + canonical_pcm.startup_offset_ms

    startup = analysis.offset_ms if analysis is not None else 0.0
    # Qt/FFmpeg presents LAME-tagged MP3s after removing the encoder/decoder
    # priming samples. NXA's byte-stream timing model is anchored to the
    # original MPEG timeline, so restore that lost time virtually rather than
    # modifying the MP3 or synthesizing discarded samples.
    presentation = -(gapless.ffmpeg_start_skip_ms if gapless is not None else 0.0)
    return manual + startup + presentation


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


def _analyze_playback_source(
    window,
) -> tuple[NxaStartupAnalysis | None, Mp3GaplessAnalysis | None, str | None]:
    if not _profile_uses_nxa_startup(window):
        return None, None, None
    pcm = getattr(window.audio_transport, "canonical_pcm", None)
    if pcm is not None:
        return pcm.startup, None, None
    source = getattr(window.audio_transport, "playback_source", None)
    if source is None:
        return None, None, None
    path = Path(source)
    if path.suffix.casefold() not in _MP3_SUFFIXES:
        return None, None, None
    try:
        payload = path.read_bytes()
        startup = analyze_nxa_mp3_startup(payload)
        gapless = analyze_ffmpeg_lame_gapless(
            payload,
            first_frame_offset=startup.source_start_offset,
        )
        return startup, gapless, None
    except (OSError, NxaStartupError, ValueError) as exc:
        return None, None, str(exc)


def _apply_window_alignment(window, *, announce: bool = False) -> None:
    from stepnx.authoring.audio import AudioAlignment
    from stepnx.gui.timeline_widget import TimelineWidget

    analysis = getattr(window, "_nxa_startup_analysis", None)
    gapless = getattr(window, "_nxa_gapless_analysis", None)
    effective = effective_nxa_audio_offset_ms(
        window.audio_offset.value(),
        analysis,
        gapless,
        nxa_profile=_profile_uses_nxa_startup(window),
        canonical_pcm=getattr(window.audio_transport, "canonical_pcm", None),
    )
    window.audio_alignment = AudioAlignment(effective)
    _refresh_pcm_metronome(window)

    for index in range(window.tabs.count()):
        widget = window.tabs.widget(index)
        if isinstance(widget, TimelineWidget):
            widget.set_waveform(window.waveform, window.audio_alignment)

    window._audio_position_changed(window.audio_position.value())
    if not announce:
        return

    error = getattr(window, "_nxa_startup_analysis_error", None)
    if analysis is not None and _profile_uses_nxa_startup(window):
        pcm = getattr(window.audio_transport, "canonical_pcm", None)
        startup_ms = pcm.startup_offset_ms if pcm is not None else analysis.offset_ms
        parts = [
            "NXA timing: ",
            f"startup {analysis.net_source_lead_samples:+d} samples / "
            f"{startup_ms:+.3f} ms",
        ]
        if gapless is not None:
            parts.extend(
                [
                    "; FFmpeg LAME trim ",
                    f"{gapless.ffmpeg_start_skip_samples:d} samples / "
                    f"{gapless.ffmpeg_start_skip_ms:.3f} ms",
                    f"; compensation {-gapless.ffmpeg_start_skip_ms:+.3f} ms",
                ]
            )
        parts.append(f"; effective audio offset {effective:+.3f} ms")
        if getattr(window.audio_transport, "canonical_pcm", None) is not None:
            parts.append("; shared PCM / sample clock")
        window.statusBar().showMessage("".join(parts), 10000)
    elif error and _profile_uses_nxa_startup(window):
        window.statusBar().showMessage(
            "NXA timing unavailable; using manual audio offset only: "
            f"{error}",
            8000,
        )


def _refresh_analysis(window, *, announce: bool) -> None:
    analysis, gapless, error = _analyze_playback_source(window)
    window._nxa_startup_analysis = analysis
    window._nxa_gapless_analysis = gapless
    window._nxa_startup_analysis_error = error
    _apply_window_alignment(window, announce=announce)


def _refresh_pcm_metronome(window) -> None:
    transport = window.audio_transport
    playback = getattr(transport, "_pcm_playback", None)
    if playback is None:
        return
    click = transport._pcm_metronome_sample
    enabled = window.metronome_enabled.isChecked()
    clock = (window.note_metronome_clock if window._selected_metronome_mode() == "arrow"
             else window.metronome_clock)
    if not enabled or clock is None or not click:
        playback.set_clicks((), ())
        return
    pcm = transport.canonical_pcm
    offset = window.audio_alignment.offset_ms
    try:
        times = clock.times_between(-offset - len(click) / 96, pcm.duration_ms - offset)
        frames = tuple(sorted({round((time + offset) * 48) for time in times}))
        playback.set_clicks(click, frames)
    except (ValueError, OverflowError) as exc:
        playback.set_clicks((), ())
        transport.errorOccurred.emit(f"PCM metronome unavailable: {exc}")


def install_nxa_audio_alignment(window) -> None:
    """Select canonical PCM for NXA and apply its sample-ledger alignment.

    Profile changes reload the original source, preventing a waveform/player
    from retaining another profile's PCM or gapless assumptions. The ordinary
    Audio Offset spin box remains a session-only additive override.
    """

    if getattr(window, "_nxa_audio_alignment_installed", False):
        return
    window._nxa_audio_alignment_installed = True
    window._nxa_startup_analysis = None
    window._nxa_gapless_analysis = None
    window._nxa_startup_analysis_error = None
    window.audio_transport.pcm_prepare_playback = lambda: _refresh_pcm_metronome(window)

    original_load_audio = window._load_audio

    def load_audio_with_nxa_alignment(path: Path) -> None:
        window.audio_transport.nxa_timing_enabled = _profile_uses_nxa_startup(window)
        original_load_audio(path)
        if window.audio_transport.playback_source is None:
            window.waveform = None
        _refresh_analysis(window, announce=True)

    window._load_audio = load_audio_with_nxa_alignment

    # MainWindow's original handler runs first and restores the manual value;
    # this second connection composes the automatic NXA terms afterwards.
    window.audio_offset.valueChanged.connect(
        lambda _value: _apply_window_alignment(window, announce=False)
    )

    def profile_changed(_checked=False) -> None:
        enabled = _profile_uses_nxa_startup(window)
        transport = window.audio_transport
        if enabled != transport.nxa_timing_enabled:
            source = transport.original_source
            transport.nxa_timing_enabled = enabled
            if source is not None:
                window._load_audio(source)
                return
        _refresh_analysis(window, announce=False)

    for action in getattr(window, "profile_actions", {}).values():
        action.triggered.connect(profile_changed)

    window.metronome_enabled.toggled.connect(lambda _checked: _refresh_pcm_metronome(window))
    for action in window.metronome_mode_actions.values():
        action.triggered.connect(lambda _checked: _refresh_pcm_metronome(window))

    original_snapshot = window._set_metronome_snapshot

    def set_snapshot(snapshot):
        original_snapshot(snapshot)
        _refresh_pcm_metronome(window)

    window._set_metronome_snapshot = set_snapshot
    original_metronome = window._load_metronome

    def load_metronome(path):
        original_metronome(path)
        _refresh_pcm_metronome(window)

    window._load_metronome = load_metronome

    # A folder passed on the command line may have loaded audio before show(),
    # so consume an already-staged playback source during installation too.
    profile_changed()
