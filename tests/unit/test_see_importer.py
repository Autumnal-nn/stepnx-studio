from __future__ import annotations

import struct
import unittest
import zlib

from stepnx.core.errors import ParseError
from stepnx.importers.see import (
    SEE_HEADER_SIZE,
    SEE_SECTION_TABLE_OFFSET,
    _BLOWFISH_P,
    _blowfish_f,
    import_bytes,
)


def _encrypt_stepedit_block(block: bytes) -> bytes:
    left, right = struct.unpack("<II", block)
    for index in range(16):
        left ^= _BLOWFISH_P[index]
        right ^= _blowfish_f(left)
        left, right = right, left
    left, right = right, left
    right ^= _BLOWFISH_P[16]
    left ^= _BLOWFISH_P[17]
    return struct.pack("<II", left & 0xFFFFFFFF, right & 0xFFFFFFFF)


def _encode_stepedit_payload(decoded: bytes) -> bytes:
    encoded = bytearray(decoded)
    for position in range(0, len(encoded) - 7, 24):
        encoded[position : position + 8] = _encrypt_stepedit_block(
            bytes(encoded[position : position + 8])
        )
    return zlib.compress(bytes(encoded))


def _make_see(*, malformed_crypto: bool = False) -> bytes:
    block = bytearray(0xA8)
    struct.pack_into("<fIIi", block, 0, 120.0, 4, 4, 125)
    struct.pack_into("<II", block, 0x10, 3, 7)
    struct.pack_into("<i", block, 0x60, 1000)
    struct.pack_into("<I", block, 0x80, 2)
    block[0x84 + 0] = 1
    block[0x84 + 13 + 0] = 20
    compressed = _encode_stepedit_payload(bytes(block))
    if malformed_crypto:
        payload = bytearray(zlib.decompress(compressed))
        payload[0:8] = b"\x00" * 8
        compressed = zlib.compress(bytes(payload))

    section_offset = SEE_HEADER_SIZE
    section = bytearray(804)
    struct.pack_into("<I", section, 4, 1)
    section += struct.pack("<I", len(compressed)) + compressed

    data = bytearray(SEE_HEADER_SIZE)
    data[:4] = b"STEE"
    struct.pack_into("<I", data, 4, 1)
    struct.pack_into("<I", data, SEE_SECTION_TABLE_OFFSET, section_offset)
    data += section
    return bytes(data)


class SEEImporterTests(unittest.TestCase):
    def test_stepedit_pipeline_decodes_to_nx20_through_nx10(self) -> None:
        result = import_bytes(_make_see(), source="synthetic.SEE")
        self.assertEqual(len(result.charts), 1)
        chart = result.charts[0]
        self.assertEqual(chart.mode.key, "PR")
        self.assertTrue(chart.nx10_bytes.startswith(b"NX10"))
        document = chart.document
        self.assertEqual(document.columns.value, 5)
        self.assertEqual(len(document.splits), 1)
        block = document.splits[0].blocks[0]
        self.assertAlmostEqual(block.bpm.value, 120.0)
        self.assertEqual(block.beat_measure.value, 4)
        self.assertEqual(block.beat_split.value, 4)
        self.assertEqual(len(block.rows), 2)
        self.assertEqual(len(block.divisions), 1)
        self.assertEqual(block.divisions[0].meta_id.value, 0)
        self.assertEqual(block.divisions[0].value.value, (7 << 16) | 3)

    def test_unverified_or_damaged_crypto_profile_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(ParseError, "verified StepEdit 5.63 SEE profile"):
            import_bytes(_make_see(malformed_crypto=True), source="broken.SEE")


if __name__ == "__main__":
    unittest.main()
