from __future__ import annotations

import struct
import unittest

try:
    from stepnx.gui.audio_transport import (
        _accept_transport_position,
        _metronome_voice_count,
        _mix_metronome_chunk,
        _uses_linux_metronome_sink,
    )
except ImportError as exc:
    _accept_transport_position = None
    _metronome_voice_count = None
    _mix_metronome_chunk = None
    _uses_linux_metronome_sink = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


@unittest.skipIf(
    _accept_transport_position is None,
    f"Qt runtime unavailable: {QT_UNAVAILABLE}",
)
class AudioTransportJitterTests(unittest.TestCase):
    def test_live_backend_regression_is_rejected(self) -> None:
        self.assertFalse(
            _accept_transport_position(1008, 995, playing=True)
        )

    def test_live_forward_progress_is_accepted(self) -> None:
        self.assertTrue(
            _accept_transport_position(1008, 1012, playing=True)
        )

    def test_explicit_backward_seek_is_accepted(self) -> None:
        self.assertTrue(
            _accept_transport_position(1008, 500, playing=True, explicit=True)
        )

    def test_paused_transport_may_move_backwards(self) -> None:
        self.assertTrue(
            _accept_transport_position(1008, 995, playing=False)
        )

    def test_poll_backend_poll_sequence_never_rewinds_visible_time(self) -> None:
        previous = -1
        accepted = []
        for candidate in (1008, 995, 1012):
            if _accept_transport_position(previous, candidate, playing=True):
                previous = candidate
                accepted.append(candidate)
        self.assertEqual(accepted, [1008, 1012])

    def test_linux_uses_single_software_metronome_sink(self) -> None:
        self.assertTrue(_uses_linux_metronome_sink("linux"))
        self.assertTrue(_uses_linux_metronome_sink("linux2"))
        self.assertEqual(_metronome_voice_count("linux"), 0)

    def test_windows_keeps_existing_qsoundeffect_voice_pool(self) -> None:
        self.assertFalse(_uses_linux_metronome_sink("win32"))
        self.assertEqual(_metronome_voice_count("win32"), 8)

    def test_software_metronome_mixes_overlap_and_clips_int16(self) -> None:
        # Two stereo frames at +20000 on every channel. Starting two click
        # instances together must software-mix to +32767 rather than spawning
        # two independent backend streams or overflowing signed Int16.
        sample = (20000, 20000, 20000, 20000)
        payload, remaining = _mix_metronome_chunk(
            sample,
            (0, 0),
            channels=2,
            frames=1,
        )
        self.assertEqual(struct.unpack("<2h", payload), (32767, 32767))
        self.assertEqual(remaining, (1, 1))

    def test_software_metronome_outputs_silence_without_active_clicks(self) -> None:
        payload, remaining = _mix_metronome_chunk(
            (1000, 1000),
            (),
            channels=2,
            frames=3,
        )
        self.assertEqual(payload, b"\x00" * 12)
        self.assertEqual(remaining, ())


if __name__ == "__main__":
    unittest.main()
