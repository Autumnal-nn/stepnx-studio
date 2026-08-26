from __future__ import annotations

import sys
from types import MethodType

import stepnx.gui.audio_transport as transport_module


_LINUX_METRONOME_QUEUE_MS = 20.0
_LINUX_TRANSPORT_POLL_MS = 16.0
# The event detector advances in roughly 16 ms transport steps. Adding half a
# poll period centers the trigger error around the 20 ms QAudioSink queue instead
# of making the click systematically late by up to one poll interval.
_LINUX_METRONOME_LOOKAHEAD_MS = (
    _LINUX_METRONOME_QUEUE_MS + _LINUX_TRANSPORT_POLL_MS / 2.0
)
_LINUX_STABLE_PUMP_MS = 4


class _BeatClockLookahead:
    def __init__(self, clock, lookahead_ms: float) -> None:
        self._clock = clock
        self._lookahead_ms = float(lookahead_ms)

    def beat_at(self, chart_time_ms: float):
        return self._clock.beat_at(chart_time_ms + self._lookahead_ms)


class _NoteClockLookahead:
    def __init__(self, clock, lookahead_ms: float) -> None:
        self._clock = clock
        self._lookahead_ms = float(lookahead_ms)

    def note_at(self, chart_time_ms: float):
        return self._clock.note_at(chart_time_ms + self._lookahead_ms)


def _stable_linux_pump(self) -> None:
    """Keep the Linux sink full, reproducing the no-underrun implementation."""

    sink = self._sink
    writer = self._writer
    if sink is None or writer is None:
        return
    frame_bytes = self._channels * 2
    free_bytes = max(0, int(sink.bytesFree()))
    frames = free_bytes // frame_bytes
    if frames <= 0:
        return
    payload, self._voices = transport_module._mix_metronome_chunk(
        self._sample,
        self._voices,
        channels=self._channels,
        frames=frames,
    )
    if payload:
        writer.write(payload)


def _wrap_current_clocks(window) -> None:
    beat = getattr(window, "metronome_clock", None)
    if beat is not None and not isinstance(beat, _BeatClockLookahead):
        window.metronome_clock = _BeatClockLookahead(
            beat, _LINUX_METRONOME_LOOKAHEAD_MS
        )

    note = getattr(window, "note_metronome_clock", None)
    if note is not None and not isinstance(note, _NoteClockLookahead):
        window.note_metronome_clock = _NoteClockLookahead(
            note, _LINUX_METRONOME_LOOKAHEAD_MS
        )


def install_phase11_linux_metronome(window) -> None:
    """Use a stable sink queue while compensating its latency in event timing."""

    if not sys.platform.startswith("linux"):
        return
    if getattr(window, "_phase11_linux_metronome_installed", False):
        return
    window._phase11_linux_metronome_installed = True

    linux_sink = getattr(window.audio_transport, "_linux_metronome", None)
    if linux_sink is None:
        return

    # The low-queue experiment reduced latency but reintroduced audible
    # underruns. Restore the original full-buffer pump and its proven 4 ms
    # refill cadence. The queue latency is compensated at the chart-event layer
    # below instead of starving QAudioSink.
    timer = linux_sink._pump_timer
    try:
        timer.timeout.disconnect()
    except (RuntimeError, TypeError):
        pass
    linux_sink._pump = MethodType(_stable_linux_pump, linux_sink)
    timer.setInterval(_LINUX_STABLE_PUMP_MS)
    timer.timeout.connect(linux_sink._pump)
    linux_sink._pump()

    original_set_snapshot = window._set_metronome_snapshot

    def set_snapshot_with_lookahead(snapshot) -> None:
        original_set_snapshot(snapshot)
        _wrap_current_clocks(window)

    window._set_metronome_snapshot = set_snapshot_with_lookahead
    _wrap_current_clocks(window)
