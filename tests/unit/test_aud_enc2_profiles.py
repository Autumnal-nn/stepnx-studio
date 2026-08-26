from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from stepnx.authoring.audio import (
    AudDecodeError,
    _ENC1_TABLE,
    decode_aud,
    decode_enc1_aud,
    decode_enc2_aud,
)


_BIT_REVERSE = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))
_ENCDECRYPT_PROFILE = bytes.fromhex("000000001c1d1e1f3c3e383a585b5e59")
_NXA_SIGNATURES = (
    b"\xff\xfb\xb4D" + b"\x00" * 32 + b"Info",
    b"\xff\xfb\xb4d" + b"\x00" * 32 + b"Info",
    bytes.fromhex(
        "4944330300000000086754495432000000010000005450453100000001000000"
        "54414c4200000001"
    ),
    bytes.fromhex(
        "4944330300000000077647454f4200000019000000000053664d61726b657273"
        "000c000000640000"
    ),
)
_ARBITRARY_PROFILES = (
    bytes.fromhex("112233445566778899aabbccddeeff00"),
    bytes.fromhex("b8861ec4a49b3cdbb4bc5efea0d97415"),
    bytes.fromhex("28d8503734c54e2624d6483130c34e20"),
    bytes.fromhex("e6fa6a35fae77024e2f06a37f6e5685e"),
)


def _enc1_fixture(payload: bytes, *, start: int = 0x12345678, skip: int = 9) -> bytes:
    encrypted = bytes(
        _BIT_REVERSE[value ^ _ENC1_TABLE[(start + index) & 1023]]
        for index, value in enumerate(payload)
    )
    header = bytearray(0x86 + skip + 4)
    header[:4] = b"ENC1"
    struct.pack_into("<I", header, 0x7E, len(payload) ^ 0xCCBB)
    struct.pack_into("<I", header, 0x82, skip)
    struct.pack_into("<I", header, 0x86 + skip, start)
    return bytes(header) + encrypted


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


class AudWrapperTests(unittest.TestCase):
    def test_enc1_official_table_decodes_mp3_payload(self) -> None:
        payload = b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes(range(64))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "enc1.AUD"
            path.write_bytes(_enc1_fixture(payload))
            self.assertEqual(decode_enc1_aud(path), payload)
            self.assertEqual(decode_aud(path), payload)
            # Existing GUI callers still use this historical entry point.
            self.assertEqual(decode_enc2_aud(path), payload)

    def test_encdecrypt_profile_still_decodes_generic_mp3_payload(self) -> None:
        payload = b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes(range(64))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "encdecrypt.AUD"
            path.write_bytes(_enc2_fixture(payload, _ENCDECRYPT_PROFILE))
            self.assertEqual(decode_enc2_aud(path), payload)

    def test_nxa_signatures_recover_arbitrary_per_file_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            for index, (signature, profile) in enumerate(
                zip(_NXA_SIGNATURES, _ARBITRARY_PROFILES)
            ):
                with self.subTest(signature=index):
                    payload = signature + bytes(range(64))
                    path = Path(temporary) / f"dynamic-{index}.AUD"
                    path.write_bytes(_enc2_fixture(payload, profile))
                    self.assertEqual(decode_enc2_aud(path), payload)

    def test_zero_run_recovers_unknown_enc2_mastering_signature(self) -> None:
        payload = (
            b"ID3\x04\x00\x00\x00\x00\x00\x10"
            b"TXXX\x00\x00\x00\x06\x00\x00other"
            + bytes(range(48))
            + b"\x00" * 32
            + bytes(range(48, 96))
        )
        unknown = bytes.fromhex("fedcba98765432100123456789abcdef")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "zero-run.AUD"
            path.write_bytes(_enc2_fixture(payload, unknown))
            self.assertEqual(decode_enc2_aud(path), payload)

    def test_unknown_profile_without_recovery_evidence_remains_rejected(self) -> None:
        payload = (
            b"ID3\x04\x00\x00\x00\x00\x00\x10"
            b"TXXX\x00\x00\x00\x06\x00\x00other"
            + bytes(range(1, 97))
        )
        unknown = bytes.fromhex("102132435465768798a9bacbdcedfe0f")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "unknown.AUD"
            path.write_bytes(_enc2_fixture(payload, unknown))
            with self.assertRaisesRegex(AudDecodeError, "unsupported key profile"):
                decode_enc2_aud(path)


if __name__ == "__main__":
    unittest.main()
