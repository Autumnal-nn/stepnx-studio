from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from stepnx.authoring.audio import AudDecodeError, decode_enc2_aud


_BIT_REVERSE = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))
_PROFILES = (
    bytes.fromhex("000000001c1d1e1f3c3e383a585b5e59"),
    bytes.fromhex("ba81da7ea69ec09db6bfdab8a2d4f8df"),
    bytes.fromhex("9ea4448e82b95a8d9aa27c88beb79a8f"),
)


def _enc2_fixture(payload: bytes, base_profile: bytes) -> bytes:
    key = bytes(range(16))
    table = bytes((index * 37 + 11) & 0xFF for index in range(1024))
    start = 0x12345678
    stream = bytes(
        value ^ base_profile[index & 15] ^ key[index & 15]
        for index, value in enumerate(table)
    )
    encrypted = bytes(
        _BIT_REVERSE[value ^ stream[(start + index) & 1023]]
        for index, value in enumerate(payload)
    )
    skip = 5
    header = bytearray(156)
    header[:4] = b"ENC2"
    struct.pack_into("<II", header, 0x84, len(payload), skip)
    header[0x8C:0x9C] = key
    return bytes(header) + bytes(skip) + struct.pack("<I", start) + table + encrypted


class Enc2ProfileTests(unittest.TestCase):
    def test_all_recovered_profiles_decode_same_mp3_payload(self) -> None:
        payload = b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes(range(64))
        with tempfile.TemporaryDirectory() as temporary:
            for index, profile in enumerate(_PROFILES):
                with self.subTest(profile=index):
                    path = Path(temporary) / f"profile-{index}.AUD"
                    path.write_bytes(_enc2_fixture(payload, profile))
                    self.assertEqual(decode_enc2_aud(path), payload)

    def test_unknown_profile_remains_rejected(self) -> None:
        payload = b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes(range(64))
        unknown = bytes.fromhex("112233445566778899aabbccddeeff00")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "unknown.AUD"
            path.write_bytes(_enc2_fixture(payload, unknown))
            with self.assertRaisesRegex(AudDecodeError, "unsupported key profile"):
                decode_enc2_aud(path)


if __name__ == "__main__":
    unittest.main()
