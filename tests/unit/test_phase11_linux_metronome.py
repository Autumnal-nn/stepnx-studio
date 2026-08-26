from __future__ import annotations

import struct
import unittest

try:
    from stepnx.gui.phase11_linux_metronome import (
        _BeatClockLookahead,
        _LINUX_METRONOME_LOOKAHEAD_MS,
        _NoteClockLookahead,
        _stable_linux_pump,
    )
except ImportError as exc:
    _BeatClockLookahead = None
    _NoteClockLookahead = None
    _stable_linux_pump = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


class _RecordingBeatClock:
    def __init__(self) -> None:
        self.times: list[float] = []

    def beat_at(self, value: float):
        self.times.append(value)
        return value


class _RecordingNoteClock:
    def __init__(self) -> None:
        self.times: list[float] = []

    def note_at(self, value: float):
        self.times.append(value)
        return value


class _FakeSink:
    def __init__(self, free_bytes: int) -> None:
        self._free_bytes = free_bytes

    def bytesFree(self) -> int:
        return self._free_bytes


class _FakeWriter:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def write(self, payload: bytes) -> int:
        self.payloads.append(bytes(payload))
        return len(payload)


@unittest.skipIf(
    _BeatClockLookahead is None,
    f"Qt runtime unavailable: {QT_UNAVAILABLE}",
)
class Phase11LinuxMetronomeTests(unittest.TestCase):
    def test_linux_metronome_lookahead_is_queue_plus_half_poll(self) -> None:
        self.assertEqual(_LINUX_METRONOME_LOOKAHEAD_MS, 28.0)

    def test_beat_clock_only_advances_metronome_query(self) -> None:
        clock = _RecordingBeatClock()
        wrapped = _BeatClockLookahead(clock, 28.0)
        self.assertEqual(wrapped.beat_at(1000.0), 1028.0)
        self.assertEqual(clock.times, [1028.0])

    def test_note_clock_only_advances_metronome_query(self) -> None:
        clock = _RecordingNoteClock()
        wrapped = _NoteClockLookahead(clock, 28.0)
        self.assertEqual(wrapped.note_at(250.0), 278.0)
        self.assertEqual(clock.times, [278.0])

    def test_stable_pump_fills_all_sink_space(self) -> None:
        writer = _FakeWriter()
        fake = type("FakeLinuxSink", (), {})()
        fake._sink = _FakeSink(16)
        fake._writer = writer
        fake._channels = 2
        fake._sample = (1000, 1000, 2000, 2000)
        fake._voices = (0,)

        _stable_linux_pump(fake)

        self.assertEqual(len(writer.payloads), 1)
        # 16 free bytes / 4 bytes per stereo frame = 4 frames written.
        self.assertEqual(len(writer.payloads[0]), 16)
        samples = struct.unpack("<8h", writer.payloads[0])
        self.assertEqual(samples[:4], (1000, 1000, 2000, 2000))
        self.assertEqual(samples[4:], (0, 0, 0, 0))
        self.assertEqual(fake._voices, ())


if __name__ == "__main__":
    unittest.main()
