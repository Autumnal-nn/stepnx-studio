from __future__ import annotations

import struct

import pytest

from stepnx.codecs.nx20 import parse_bytes
from stepnx.exporters import SscExportError, compile_ssc_export, export_chart
from tests.fixture_factory import f32, metadata, u32


EMPTY = bytes((0x00, 0x00, 0x00, 0x00))


def _document(first_cell: bytes, *, header=()) -> bytes:
    row = first_cell + EMPTY * 4
    block = bytearray()
    block += f32(0.0) + f32(120.0) + f32(0.125) + f32(0.0) + f32(1.0)
    block += bytes((8, 4, 0, 0))
    block += metadata()
    block += u32(1)
    block += row

    data = bytearray(b"NX20")
    data += u32(0) + u32(5) + u32(0)
    data += metadata(*header)
    data += u32(1)
    data += bytes((0, 0)) + struct.pack("<H", 0)
    data += metadata()
    data += u32(1)
    data += block
    return bytes(data)


def test_lossless_compatibility_property_remains_available() -> None:
    document = parse_bytes(_document(bytes((0x43, 3, 0, 0))))
    report = export_chart(document, description="S1.NX")
    assert report.lossless


def test_header_noteskin_context_keeps_unknown_note_error_policy() -> None:
    document = parse_bytes(
        _document(bytes((0x53, 3, 1, 0)), header=((901, 16),))
    )
    with pytest.raises(SscExportError, match="0x53"):
        compile_ssc_export(document, description="S1.NX")


def test_runtime_compiler_owns_known_header_noteskin_semantics() -> None:
    document = parse_bytes(
        _document(bytes((0x43, 3, 1, 0)), header=((901, 16),))
    )
    report = compile_ssc_export(document, description="S1.NX")
    assert "perfor1" in report.charts[0].chart.noteskin_banks
    assert "ssc.metadata-not-carried" not in {item.code for item in report.diagnostics}
