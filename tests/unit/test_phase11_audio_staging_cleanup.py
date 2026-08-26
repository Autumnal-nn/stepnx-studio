from __future__ import annotations

import unittest
from pathlib import Path

try:
    from stepnx.gui.phase11_audio_staging_cleanup import (
        _cleanup_aud_staging_retryable,
        _release_waveform_source,
    )
except ImportError as exc:
    _cleanup_aud_staging_retryable = None
    _release_waveform_source = None
    QT_UNAVAILABLE = str(exc)
else:
    QT_UNAVAILABLE = ""


class _FakeDirectory:
    def __init__(self, outcomes: list[bool]) -> None:
        self.outcomes = list(outcomes)
        self.remove_calls = 0

    def remove(self) -> bool:
        self.remove_calls += 1
        return self.outcomes.pop(0)


class _FakePlayer:
    def __init__(self) -> None:
        self.stop_calls = 0
        self.sources = []

    def stop(self) -> None:
        self.stop_calls += 1

    def setSource(self, source) -> None:
        self.sources.append(source)


class _FakeTimer:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1


class _FakeClock:
    def __init__(self) -> None:
        self.invalidate_calls = 0

    def invalidate(self) -> None:
        self.invalidate_calls += 1


class _FakeBackendDecoder:
    def __init__(self) -> None:
        self.stop_calls = 0
        self.sources = []

    def stop(self) -> None:
        self.stop_calls += 1

    def setSource(self, source) -> None:
        self.sources.append(source)


@unittest.skipIf(
    _cleanup_aud_staging_retryable is None,
    f"Qt runtime unavailable: {QT_UNAVAILABLE}",
)
class Phase11AudioStagingCleanupTests(unittest.TestCase):
    def test_failed_windows_style_remove_keeps_directory_for_retry(self) -> None:
        directory = _FakeDirectory([False, True])
        transport = type("FakeTransport", (), {})()
        transport._aud_directory = directory
        transport._playback_source = Path("decoded-1.mp3")
        transport.player = _FakePlayer()
        transport._position_timer = _FakeTimer()
        transport._position_clock = _FakeClock()

        self.assertFalse(_cleanup_aud_staging_retryable(transport))
        self.assertIs(transport._aud_directory, directory)
        self.assertIsNone(transport._playback_source)
        self.assertTrue(transport.player.sources[-1].isEmpty())

        self.assertTrue(_cleanup_aud_staging_retryable(transport))
        self.assertIsNone(transport._aud_directory)
        self.assertEqual(directory.remove_calls, 2)

    def test_waveform_release_drops_staged_mp3_source(self) -> None:
        backend = _FakeBackendDecoder()
        decoder = type("FakeWaveformDecoder", (), {})()
        decoder.decoder = backend
        decoder._source = Path("decoded-2.mp3")

        _release_waveform_source(decoder)

        self.assertEqual(backend.stop_calls, 1)
        self.assertTrue(backend.sources[-1].isEmpty())
        self.assertIsNone(decoder._source)


if __name__ == "__main__":
    unittest.main()
