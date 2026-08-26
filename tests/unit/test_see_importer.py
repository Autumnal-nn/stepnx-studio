from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from stepnx.core.errors import ParseError
from stepnx.importers.dispatch import load_importable
from stepnx.importers.see import (
    SEE_HEADER_SIZE,
    SEE_SECTION_TABLE_OFFSET,
    SEEImportResult,
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


def _make_see(
    *,
    section_index: int = 0,
    rows: tuple[bytes, ...] = (bytes((1,) + (0,) * 12), bytes((20,) + (0,) * 12)),
    malformed_crypto: bool = False,
) -> bytes:
    if not 0 <= section_index < 9:
        raise ValueError("SEE section index must be 0..8")
    if any(len(row) != 13 for row in rows):
        raise ValueError("synthetic SEE rows must contain 13 lanes")

    block = bytearray(0x84 + len(rows) * 13)
    struct.pack_into("<fIIi", block, 0, 120.0, 4, 4, 125)
    struct.pack_into("<II", block, 0x10, 3, 7)
    struct.pack_into("<i", block, 0x60, 1000)
    struct.pack_into("<I", block, 0x80, len(rows))
    for index, row in enumerate(rows):
        block[0x84 + index * 13 : 0x84 + (index + 1) * 13] = row

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
    struct.pack_into(
        "<I", data, SEE_SECTION_TABLE_OFFSET + section_index * 4, section_offset
    )
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

    def test_half_double_preserves_native_six_lane_projection(self) -> None:
        row = bytearray(13)
        row[2] = 1
        row[7] = 10
        result = import_bytes(
            _make_see(section_index=6, rows=(bytes(row),)), source="half.SEE"
        )
        chart = result.charts[0]
        self.assertEqual(chart.mode.key, "HF")
        self.assertEqual(chart.document.start_column.value, 2)
        self.assertEqual(chart.document.columns.value, 6)
        self.assertEqual(len(chart.document.splits[0].blocks[0].rows), 1)

    def test_lightmap_uses_see_lanes_10_through_12(self) -> None:
        row = bytearray(13)
        row[10] = 1
        row[12] = 20
        result = import_bytes(
            _make_see(section_index=8, rows=(bytes(row),)), source="lightmap.SEE"
        )
        chart = result.charts[0]
        self.assertEqual(chart.mode.key, "LM")
        self.assertTrue(chart.document.effective_lightmap)
        self.assertEqual(chart.document.columns.value, 3)
        self.assertEqual(
            chart.document.splits[0].blocks[0].rows[0].raw_channels,
            b"\x01\x00\x01\x00",
        )

    def test_dispatcher_routes_see_to_verified_importer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.SEE"
            path.write_bytes(_make_see())
            imported = load_importable(path)
        self.assertIsInstance(imported, SEEImportResult)
        self.assertEqual(imported.charts[0].mode.key, "PR")

    def test_unverified_or_damaged_crypto_profile_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(ParseError, "verified StepEdit 5.63 SEE profile"):
            import_bytes(_make_see(malformed_crypto=True), source="broken.SEE")


if __name__ == "__main__":
    unittest.main()
