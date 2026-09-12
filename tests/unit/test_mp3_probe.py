from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stepnx.authoring.mp3_probe import (
    detect_mp3_sample_rate,
    detect_mp3_sample_rate_bytes,
)


def _frame(header: bytes, size: int) -> bytes:
    return header + bytes(size - len(header))


def _chain(header: bytes, size: int) -> bytes:
    return _frame(header, size) * 3


class Mp3SampleRateProbeTests(unittest.TestCase):
    def test_detects_48khz_mpeg1_layer3(self) -> None:
        payload = _chain(bytes.fromhex("fffbb404"), 576)
        self.assertEqual(detect_mp3_sample_rate_bytes(payload), 48_000)

    def test_detects_44100hz_mpeg1_layer3(self) -> None:
        payload = _chain(bytes.fromhex("fffbb004"), 626)
        self.assertEqual(detect_mp3_sample_rate_bytes(payload), 44_100)

    def test_file_probe_skips_id3v2_payload(self) -> None:
        mp3 = _chain(bytes.fromhex("fffbb004"), 626)
        id3 = b"ID3\x04\x00\x00\x00\x00\x00\x10" + b"X" * 16
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "legacy.mp3"
            source.write_bytes(id3 + mp3)
            self.assertEqual(detect_mp3_sample_rate(source), 44_100)

    def test_rejects_isolated_false_sync(self) -> None:
        payload = bytes.fromhex("fffbb004") + b"not an MPEG frame chain"
        self.assertIsNone(detect_mp3_sample_rate_bytes(payload))


if __name__ == "__main__":
    unittest.main()
