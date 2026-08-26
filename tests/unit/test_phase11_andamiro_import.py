from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from stepnx.importers.andamiro import load_andamiro
from stepnx.importers.authoring_import import load_authoring_import_candidates


def _write_stf(path: Path, *, double_name: bool = False) -> None:
    data = bytearray(280 + 1024 * 14)
    struct.pack_into("<HH", data, 0xFC, 2, 2)
    struct.pack_into("<f", data, 0x100, 120.0)
    struct.pack_into("<I", data, 0x104, 4)
    struct.pack_into("<I", data, 0x108, 2)
    struct.pack_into("<I", data, 0x114, 25)
    empty = b"0" * 13 + b"\0"
    for index in range(1024):
        data[280 + index * 14 : 294 + index * 14] = empty
    row = bytearray(empty)
    row[0] = ord("1")
    row[5] = ord("1")
    row[10] = ord("1")
    data[280:294] = row
    path.write_bytes(data)


def _not4_encrypt(payload: bytes) -> bytes:
    return bytes(value ^ ((0xD2 + 0x95 * index) & 0xFF) for index, value in enumerate(payload))


def _write_not4(path: Path) -> None:
    records = (
        struct.pack("<HH", 0, (1 << 15) | (1 << 10) | (1 << 5))
        + struct.pack("<HH", 2, (1 << 14) | (1 << 9) | (1 << 4))
    )
    data = bytearray(0x88)
    struct.pack_into("<I", data, 0, 2)
    struct.pack_into("<3f", data, 8, 125.0, 120.0, 120.0)
    struct.pack_into("<3I", data, 24, 100, 0, 0)
    struct.pack_into("<2I", data, 40, 0, 0)
    struct.pack_into("<I", data, 56, 2)
    struct.pack_into("<I", data, 60, 4)
    struct.pack_into("<HH", data, 0x84, 3, 3)
    data += _not4_encrypt(records)
    path.write_bytes(data)


def _signed_not5(word: int) -> int:
    word &= 0x03FF
    return word | (0xFC00 if word & 0x0200 else 0)


def _write_not5(path: Path) -> None:
    line_count = 2
    data = bytearray(0xD8 + line_count * 6)
    data[:8] = b"pump 5.0"
    struct.pack_into("<I", data, 10, line_count)
    struct.pack_into("<10f", data, 16, 140.0, *([120.0] * 9))
    struct.pack_into("<10I", data, 56, 50, *([0] * 9))
    struct.pack_into("<10I", data, 96, *([0] * 10))
    struct.pack_into("<I", data, 136, 2)
    struct.pack_into("<I", data, 140, 0)
    steps = (_signed_not5((1 << 9) | (1 << 4)), 0)
    struct.pack_into("<2H", data, 0xD8, *steps)
    struct.pack_into("<2H", data, 0xD8 + 4, 0, 0)
    struct.pack_into("<2H", data, 0xD8 + 8, 0, 0)
    path.write_bytes(data)


def _stx_block(*, lane: int) -> bytes:
    decoded = bytearray(0x84 + 13)
    struct.pack_into("<fIIi", decoded, 0, 136.0, 4, 2, 1)
    struct.pack_into("<i", decoded, 0x60, 1000)
    struct.pack_into("<I", decoded, 0x80, 1)
    decoded[0x84 + lane] = 1
    return zlib.compress(decoded)


def _write_stx(path: Path) -> None:
    header = bytearray(0x120)
    header[:4] = b"STF4"
    sections = []
    for mode in range(9):
        lane = 10 if mode == 8 else (2 if mode == 6 else 0)
        compressed = _stx_block(lane=lane)
        section = bytearray(204)
        struct.pack_into("<I", section, 0, mode)
        struct.pack_into("<I", section, 4, 1)
        section += struct.pack("<I", len(compressed)) + compressed
        sections.append(bytes(section))
    position = len(header)
    addresses = []
    for section in sections:
        addresses.append(position)
        position += len(section)
    struct.pack_into("<9I", header, 0xFC, *addresses)
    path.write_bytes(bytes(header) + b"".join(sections))


class AndamiroLegacyImportTests(unittest.TestCase):
    def test_stf_versus_exposes_p1_p2_and_lightmap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Ignit_2.STF"
            _write_stf(path)
            result = load_andamiro(path)
        self.assertEqual([chart.key for chart in result.charts], ["p1", "p2", "LM"])
        self.assertEqual([chart.document.columns.value for chart in result.charts], [5, 5, 3])
        self.assertEqual(result.charts[0].document.splits[0].blocks[0].beat_split.value, 2)
        self.assertAlmostEqual(result.charts[0].document.splits[0].blocks[0].start_time.value, 250.0)
        self.assertTrue(result.charts[2].document.effective_lightmap)

    def test_stf_db_remains_real_double(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Ignit_db.STF"
            _write_stf(path)
            result = load_andamiro(path)
        self.assertEqual([chart.key for chart in result.charts], ["double", "LM"])
        self.assertEqual(result.charts[0].document.columns.value, 10)

    def test_not4_maps_playable_banks_and_lightmap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "104_E2.NOT"
            _write_not4(path)
            result = load_andamiro(path)
        self.assertEqual([chart.key for chart in result.charts], ["p1", "p2", "LM"])
        self.assertEqual([chart.document.columns.value for chart in result.charts], [5, 5, 3])
        self.assertEqual(result.charts[0].document.splits[0].blocks[0].beat_split.value, 2)
        self.assertTrue(result.charts[2].document.effective_lightmap)

    def test_not5_versus_uses_two_single_banks_not_double(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "08_H2.NOT"
            _write_not5(path)
            result = load_andamiro(path)
        self.assertEqual([chart.key for chart in result.charts], ["p1", "p2"])
        self.assertEqual([chart.document.columns.value for chart in result.charts], [5, 5])
        self.assertEqual(result.charts[0].document.splits[0].blocks[0].beat_measure.value, 16)

    def test_stx_exposes_native_nine_mode_choices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "705.STX"
            _write_stx(path)
            result = load_andamiro(path)
        self.assertEqual([chart.key for chart in result.charts], ["PR", "NO", "HD", "NM", "CR", "FR", "HF", "DV", "LM"])
        hf = result.charts[6].document
        self.assertEqual((hf.start_column.value, hf.columns.value), (2, 6))
        self.assertTrue(result.charts[8].document.effective_lightmap)

    def test_authoring_gui_candidates_keep_p1_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Jmb_hd_2.STF"
            _write_stf(path)
            candidates = load_authoring_import_candidates(path)
        self.assertEqual([candidate.key for candidate in candidates], ["p1", "p2", "LM"])
        self.assertEqual(candidates[0].label, "STF — Player 1")
        self.assertEqual(candidates[1].label, "STF — Player 2")


if __name__ == "__main__":
    unittest.main()
