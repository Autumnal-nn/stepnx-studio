from __future__ import annotations

import unittest

try:
    from stepnx.gui.audio_transport import _accept_transport_position
except ImportError as exc:
    _accept_transport_position = None
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


if __name__ == "__main__":
    unittest.main()
