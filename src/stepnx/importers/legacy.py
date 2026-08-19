from __future__ import annotations

import math
import re
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.errors import ParseError, UnsupportedFormatError


@dataclass(frozen=True, slots=True)
class LegacyDiagnostic:
    code: str
    message: str
    offset: int | None = None


@dataclass(frozen=True, slots=True)
class LegacyRow:
    cells: tuple[int, ...]
    raw: bytes = b""


@dataclass(frozen=True, slots=True)
class LegacyBlock:
    bpm: float
    beat_measure: int
    beat_split: int
    delay_ms: float
    rows: tuple[LegacyRow, ...]
    scroll: float = 1.0
    raw_header: bytes = b""
    trailer: bytes = b""


@dataclass(frozen=True, slots=True)
class LegacyChart:
    source_format: str
    columns: int
    blocks: tuple[LegacyBlock, ...]
    source_name: str | None = None
    raw: bytes = b""
    diagnostics: tuple[LegacyDiagnostic, ...] = ()
    controls: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class LegacyContainer:
    source_format: str
    charts: tuple[LegacyChart, ...]
    raw: bytes
    diagnostics: tuple[LegacyDiagnostic, ...] = ()


_NOTE = {0: 0, 1: 3, 2: 7, 3: 11, 4: 15}


def _nx20_cell(code: int) -> bytes:
    note_type = _NOTE.get(code)
    if note_type is None:
        # Unknown legacy values remain visible as a typed item instead of
        # silently becoming empty.  The original value is retained as its ID.
        return struct.pack("<I", 0xC0000001 | ((code & 0xFF) << 16))
    if not note_type:
        return b"\0\0\0\0"
    return struct.pack("<I", 0x00000340 | note_type)


def project_nx20(chart: LegacyChart, *, start_column: int = 0):
    """Materialize one legacy chart as conservative, native NX20.

    Timing that has no absolute legacy anchor is chained from the preceding
    block.  This is explicitly a projection; ``chart.raw`` remains available
    for lossless inspection of the source format.
    """
    if not 1 <= chart.columns <= 10:
        raise ValueError("legacy chart width must be between 1 and 10")
    out = bytearray(b"NX20")
    out += struct.pack("<III", start_column, chart.columns, 0)
    out += struct.pack("<I", 0)  # document metadata
    out += struct.pack("<I", max(1, len(chart.blocks)))
    blocks = chart.blocks or (LegacyBlock(120.0, 4, 4, 0.0, ()),)
    start = 0.0
    for index, block in enumerate(blocks):
        bpm = block.bpm if math.isfinite(block.bpm) and block.bpm > 0 else 120.0
        split = max(1, min(255, int(block.beat_split)))
        measure = max(1, min(255, int(block.beat_measure)))
        if index:
            previous = blocks[index - 1]
            previous_bpm = previous.bpm if previous.bpm > 0 else 120.0
            previous_split = max(1, previous.beat_split)
            start += len(previous.rows) * 60_000.0 / (previous_bpm * previous_split)
        start += block.delay_ms
        out += b"\0\0\0\0"  # split flags
        out += struct.pack("<I", 0)  # split metadata
        out += struct.pack("<I", 1)  # one block in this split
        out += struct.pack("<fffff", start, bpm, block.scroll / split, 0.0, 1.0)
        out += bytes((split, measure, 0, 0))
        out += struct.pack("<I", 0)  # block metadata
        out += struct.pack("<I", len(block.rows))
        for row in block.rows:
            cells = tuple(row.cells[: chart.columns]) + (0,) * max(
                0, chart.columns - len(row.cells)
            )
            if not any(cells):
                out += b"\x80\0\0\0"
            else:
                out += b"".join(_nx20_cell(value) for value in cells)
    return parse_bytes(bytes(out), source=f"{chart.source_name or 'legacy'} [NX20 projection]")


def parse_stf(data: bytes, *, source: str | None = None) -> LegacyChart:
    if len(data) < 280 or (len(data) - 280) % 14:
        raise ParseError(0, "STF", "expected 280-byte header and 14-byte rows", source)
    row_count = (len(data) - 280) // 14
    if row_count not in (1024, 2048):
        raise ParseError(280, "STF", f"unsupported row count {row_count}", source)
    rows = []
    for index in range(row_count):
        raw = data[280 + index * 14 : 294 + index * 14]
        if any(value not in (0, 1, 0x30, 0x31) for value in raw):
            raise ParseError(280 + index * 14, "STF row", "non-binary channel", source)
        values = tuple(1 if value in (1, 0x31) else 0 for value in raw[:10])
        rows.append(LegacyRow(values, raw))
    bpm = struct.unpack_from("<f", data, 256)[0]
    if not math.isfinite(bpm) or bpm <= 0:
        bpm = 120.0
    return LegacyChart(
        "stf", 10, (LegacyBlock(bpm, 4, 4, 0.0, tuple(rows)),), source, data
    )


def _xor_not(payload: bytes) -> bytes:
    key = 0xD2
    decoded = bytearray()
    for value in payload:
        decoded.append(value ^ key)
        key = (key + 0x95) & 0xFF
    return bytes(decoded)


def parse_not(data: bytes, *, source: str | None = None) -> LegacyChart:
    if data.startswith(b"pump 5.0"):
        return parse_not5(data, source=source)
    if len(data) < 0x88 or (len(data) - 0x88) % 4:
        raise ParseError(0, "NOT", "invalid 0x88 + count*4 size", source)
    decoded = _xor_not(data[0x88:])
    by_line: dict[int, list[int]] = {}
    for offset in range(0, len(decoded), 4):
        line, mask = struct.unpack_from("<HH", decoded, offset)
        cells = by_line.setdefault(line, [0] * 10)
        for lane in range(10):
            if mask & (1 << lane):
                cells[lane] = 1
    count = max(by_line, default=-1) + 1
    rows = tuple(LegacyRow(tuple(by_line.get(i, [0] * 10))) for i in range(count))
    return LegacyChart("not", 10, (LegacyBlock(120.0, 4, 4, 0.0, rows),), source, data)


def parse_not5(data: bytes, *, source: str | None = None) -> LegacyChart:
    if len(data) < 0xD8 or not data.startswith(b"pump 5.0") or (len(data) - 0xD8) % 6:
        raise ParseError(0, "NOT5", "invalid pump 5.0 container", source)
    count = (len(data) - 0xD8) // 6
    lane_masks = struct.unpack_from(f"<{count}H", data, 0xD8)
    types = data[0xD8 + count * 2 : 0xD8 + count * 4]
    rows = []
    for index, mask in enumerate(lane_masks):
        cells = [0] * 10
        kind = types[index * 2] if index * 2 < len(types) else 1
        code = kind if kind in (1, 2, 3, 4) else 1
        for lane in range(10):
            if mask & (1 << (9 - lane)):
                cells[lane] = code
        rows.append(LegacyRow(tuple(cells)))
    bpm = struct.unpack_from("<f", data, 0x20)[0]
    if not math.isfinite(bpm) or bpm <= 0:
        bpm = 120.0
    return LegacyChart("not5", 10, (LegacyBlock(bpm, 4, 4, 0.0, tuple(rows)),), source, data)


def _decode_stx_block(raw: bytes, *, source: str | None, offset: int) -> LegacyBlock:
    try:
        payload = zlib.decompress(raw)
    except zlib.error as exc:
        raise ParseError(offset, "STX block", f"zlib error: {exc}", source) from exc
    if len(payload) < 128 or (len(payload) - 128) % 13:
        raise ParseError(offset, "STX block", "invalid 128 + rows*13 payload", source)
    bpm, measure, split, delay = struct.unpack_from("<fIIi", payload)
    rows = tuple(
        LegacyRow(tuple(payload[pos : pos + 10]), payload[pos : pos + 13])
        for pos in range(128, len(payload), 13)
    )
    return LegacyBlock(bpm, measure, split, float(delay), rows, raw_header=payload[:128])


def parse_stx(data: bytes, *, source: str | None = None) -> LegacyContainer:
    if not data.startswith(b"STF4"):
        raise ParseError(0, "STX", "missing STF4 signature", source)
    # StepEdit stores compressed blocks behind a flat offset/size table.  Read
    # every table pair that points to an actual zlib stream; untouched slots
    # are zero-filled and deliberately ignored.
    blocks: list[LegacyBlock] = []
    seen: set[tuple[int, int]] = set()
    table_end = min(len(data), 4 + 9 * 50 * 8)
    for position in range(4, table_end - 7, 8):
        offset, size = struct.unpack_from("<II", data, position)
        if not offset or not size or (offset, size) in seen:
            continue
        if offset > len(data) or size > len(data) - offset:
            continue
        if data[offset : offset + 2] not in (b"x\x01", b"x\x9c", b"x\xda"):
            continue
        seen.add((offset, size))
        blocks.append(_decode_stx_block(data[offset : offset + size], source=source, offset=offset))
    if not blocks:
        raise ParseError(4, "STX", "no valid compressed blocks found", source)
    chart = LegacyChart("stx", 10, tuple(blocks), source, data)
    return LegacyContainer("stx", (chart,), data)


_HEADER = re.compile(r"^#([A-Za-z0-9_]+)\s*:\s*(.*)$")
_CONTROL = re.compile(r"^([BTDE])\s*:\s*(.*)$", re.I)


def parse_ksf(data: bytes, *, source: str | None = None) -> LegacyChart:
    text = None
    for encoding in ("cp949", "utf-8-sig", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    assert text is not None
    headers: dict[str, str] = {}
    controls: list[tuple[str, str]] = []
    row_lines: list[str] = []
    in_step = False
    diagnostics: list[LegacyDiagnostic] = []
    for line_number, physical in enumerate(text.splitlines(), 1):
        line = physical.strip()
        if not in_step:
            match = _HEADER.match(line)
            if match:
                key, value = match.groups()
                headers[key.upper()] = value
                in_step = key.upper() == "STEP"
            continue
        control = _CONTROL.match(line)
        if control:
            controls.append((control.group(1).upper(), control.group(2)))
            continue
        if line.startswith("#") and line.upper() in {"#END", "#ENDSTEP"}:
            break
        if not line or line.startswith("//"):
            continue
        if len(line) not in (10, 13):
            diagnostics.append(LegacyDiagnostic("ksf.row.width", f"line {line_number} has {len(line)} channels"))
        row_lines.append(line.ljust(13, "0")[:13])
    if not row_lines:
        raise ParseError(0, "KSF", "missing #STEP rows", source)
    bpm = float(headers.get("BPM", "120") or 120)
    tick = int(float(headers.get("TICKCOUNT", "4") or 4))
    raw_rows = [[int(char, 16) if char in "0123456789abcdefABCDEF" else 0 for char in line[:10]] for line in row_lines]
    # KSF uses runs of 4 for holds. A solitary 4 is a tap.
    for lane in range(10):
        index = 0
        while index < len(raw_rows):
            if raw_rows[index][lane] != 4:
                index += 1
                continue
            end = index
            while end + 1 < len(raw_rows) and raw_rows[end + 1][lane] == 4:
                end += 1
            if end == index:
                raw_rows[index][lane] = 1
            else:
                raw_rows[index][lane] = 2
                for body in range(index + 1, end):
                    raw_rows[body][lane] = 3
                raw_rows[end][lane] = 4
            index = end + 1
    rows = tuple(LegacyRow(tuple(row), row_lines[i].encode("ascii")) for i, row in enumerate(raw_rows))
    return LegacyChart("ksf-direct-move" if controls else "ksf-kiu", 10, (LegacyBlock(bpm, 4, tick, 0.0, rows),), source, data, tuple(diagnostics), tuple(controls))


def load_legacy(path: str | Path) -> LegacyChart | LegacyContainer:
    source = Path(path)
    data = source.read_bytes()
    suffix = source.suffix.casefold()
    if suffix == ".stf":
        return parse_stf(data, source=str(source))
    if suffix in {".not", ".not5"}:
        return parse_not(data, source=str(source))
    if suffix == ".stx":
        return parse_stx(data, source=str(source))
    if suffix == ".ksf":
        return parse_ksf(data, source=str(source))
    if suffix == ".see":
        raise UnsupportedFormatError("SEE requires a verified StepEdit Blowfish key profile")
    raise UnsupportedFormatError(f"unsupported legacy suffix: {source.suffix}")


def row_similarity(left: LegacyChart, right: LegacyChart) -> float:
    a = [row.cells for block in left.blocks for row in block.rows]
    b = [row.cells for block in right.blocks for row in block.rows]
    total = max(len(a), len(b))
    if not total:
        return 1.0
    matched = 0.0
    for first, second in zip(a, b):
        width = max(len(first), len(second), 1)
        matched += sum(x == y for x, y in zip(first, second)) / width
    return matched / total
