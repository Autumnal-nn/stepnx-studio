from __future__ import annotations

import math
import re
import struct
import zlib
from dataclasses import dataclass, replace
from pathlib import Path

from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.errors import ParseError
from stepnx.core.model import DeploymentRole, NX20Document
from stepnx.importers.nx10 import import_bytes as import_nx10_bytes


@dataclass(frozen=True, slots=True)
class AndamiroChartResult:
    key: str
    label: str
    source_format: str
    document: NX20Document
    default_filename: str
    diagnostics: tuple[str, ...] = ()
    semantically_lossless: bool = False


@dataclass(frozen=True, slots=True)
class AndamiroImportResult:
    charts: tuple[AndamiroChartResult, ...]
    source_bytes: bytes
    source_name: str | None = None


@dataclass(frozen=True, slots=True)
class _PlainBlock:
    bpm: float
    beat_measure: int
    beat_split: int
    delay_ms: float
    rows: tuple[tuple[int, ...], ...]
    scroll: float = 1.0


_DOUBLE_SUFFIX = re.compile(r"(?:^|_)(?:DB|XD)$", re.I)


def _source_stem(source: str | Path | None) -> str:
    return Path(source).stem if source is not None else "legacy"


def _is_explicit_double(source: str | Path | None) -> bool:
    stem = _source_stem(source).upper()
    return bool(_DOUBLE_SUFFIX.search(stem)) or stem.startswith("BATTLE")


def _has_activity(rows, start: int, end: int) -> bool:
    return any(any(row[start:end]) for row in rows)


def _note_raw(code: int) -> bytes:
    note_type = {0: 0, 1: 3, 2: 7, 3: 11, 4: 15}.get(code)
    if note_type is None:
        return struct.pack("<I", 0xC0000001 | ((code & 0xFF) << 16))
    if note_type == 0:
        return b"\x00\x00\x00\x00"
    return struct.pack("<I", 0x00000340 | note_type)


def _build_nx20(
    blocks: tuple[_PlainBlock, ...],
    *,
    columns: int,
    lightmap: bool,
    source: str,
    profile: str,
) -> NX20Document:
    if not blocks:
        raise ValueError("legacy projection requires at least one timing block")
    output = bytearray(b"NX20")
    output += struct.pack("<III", 0, columns, 1 if lightmap else 0)
    output += struct.pack("<I", 0)
    output += struct.pack("<I", len(blocks))
    base_time = 0.0
    for block in blocks:
        bpm = float(block.bpm)
        if not math.isfinite(bpm) or bpm <= 0.0:
            raise ValueError(f"invalid legacy BPM {bpm!r}")
        split = max(1, min(255, int(block.beat_split)))
        measure = max(1, min(255, int(block.beat_measure)))
        start_time = base_time + float(block.delay_ms)
        output += b"\x00\x00\x00\x00"
        output += struct.pack("<I", 0)
        output += struct.pack("<I", 1)
        output += struct.pack(
            "<fffff",
            start_time,
            bpm,
            float(block.scroll) / split,
            float(block.delay_ms),
            1.0,
        )
        output += bytes((split, measure, 0, 0))
        output += struct.pack("<I", 0)
        output += struct.pack("<I", len(block.rows))
        if lightmap:
            for row in block.rows:
                channels = tuple(1 if value else 0 for value in row[:3])
                channels += (0,) * (3 - len(channels))
                output += bytes((*channels, 0))
        else:
            for row in block.rows:
                cells = tuple(row[:columns]) + (0,) * max(0, columns - len(row))
                if not any(cells):
                    output += b"\x80\x00\x00\x00"
                else:
                    output += b"".join(_note_raw(value) for value in cells)
        base_time = start_time + len(block.rows) * 60000.0 / (bpm * split)
    document = parse_bytes(bytes(output), source=source, profile=profile)
    if lightmap:
        document = replace(document, role=DeploymentRole.LIGHTMAP)
    return document


def _candidate_documents(
    rows,
    blocks_for_rows,
    *,
    source: str,
    source_format: str,
    profile: str,
    lightmap_rows=None,
    lightmap_blocks=None,
    diagnostics: tuple[str, ...] = (),
) -> tuple[AndamiroChartResult, ...]:
    stem = _source_stem(source)
    explicit_double = _is_explicit_double(source)
    p2_active = _has_activity(rows, 5, 10)
    results: list[AndamiroChartResult] = []
    if explicit_double:
        playable = tuple(tuple(row[:10]) for row in rows)
        document = _build_nx20(
            blocks_for_rows(playable),
            columns=10,
            lightmap=False,
            source=f"{source} [{source_format.upper()} Double projection]",
            profile=profile,
        )
        results.append(
            AndamiroChartResult(
                "double",
                f"{source_format.upper()} — Double (10 lanes)",
                source_format,
                document,
                f"{stem}.NX",
                diagnostics + ("legacy.bank-layout: explicit Double keeps playable lanes 0..9",),
            )
        )
    else:
        p1_rows = tuple(tuple(row[:5]) for row in rows)
        p1 = _build_nx20(
            blocks_for_rows(p1_rows),
            columns=5,
            lightmap=False,
            source=f"{source} [{source_format.upper()} P1 projection]",
            profile=profile,
        )
        results.append(
            AndamiroChartResult(
                "p1",
                f"{source_format.upper()} — Player 1",
                source_format,
                p1,
                f"{stem}_P1.NX" if p2_active else f"{stem}.NX",
                diagnostics + ("legacy.versus-bank: lanes 0..4 projected as Player 1",),
            )
        )
        if p2_active:
            p2_rows = tuple(tuple(row[5:10]) for row in rows)
            p2 = _build_nx20(
                blocks_for_rows(p2_rows),
                columns=5,
                lightmap=False,
                source=f"{source} [{source_format.upper()} P2 projection]",
                profile=profile,
            )
            results.append(
                AndamiroChartResult(
                    "p2",
                    f"{source_format.upper()} — Player 2",
                    source_format,
                    p2,
                    f"{stem}_P2.NX",
                    diagnostics + (
                        "legacy.versus-bank: source carries a simultaneous Single in lanes 5..9; projected as Player 2",
                    ),
                )
            )
    if lightmap_rows is not None and lightmap_blocks is not None:
        lm = _build_nx20(
            lightmap_blocks(lightmap_rows),
            columns=3,
            lightmap=True,
            source=f"{source} [{source_format.upper()} Lightmap projection]",
            profile=profile,
        )
        results.append(
            AndamiroChartResult(
                "LM",
                f"LM — embedded {source_format.upper()} Lightmap",
                source_format,
                lm,
                "LM.NX",
                diagnostics + ("legacy.lightmap: source channels 10..12 projected as NX20 Lightmap",),
            )
        )
    return tuple(results)


def _load_stf(data: bytes, *, source: str, profile: str) -> AndamiroImportResult:
    if len(data) < 280 or (len(data) - 280) % 14:
        raise ParseError(0, "STF", "expected 280-byte header and 14-byte rows", source)
    physical_rows = (len(data) - 280) // 14
    if physical_rows not in (1024, 2048):
        raise ParseError(280, "STF", f"unsupported physical row count {physical_rows}", source)
    last_p1, last_p2 = struct.unpack_from("<HH", data, 0xFC)
    bpm = struct.unpack_from("<f", data, 0x100)[0]
    beat_measure = struct.unpack_from("<I", data, 0x104)[0] or 4
    beat_split = struct.unpack_from("<I", data, 0x108)[0]
    start_time_cs = struct.unpack_from("<I", data, 0x114)[0]
    if not math.isfinite(bpm) or bpm <= 0.0:
        raise ParseError(0x100, "STF BPM", f"invalid BPM {bpm!r}", source)
    if beat_split <= 0:
        raise ParseError(0x108, "STF Beat Split", "Beat Split must be positive", source)
    rows13: list[tuple[int, ...]] = []
    for index in range(physical_rows):
        raw = data[280 + index * 14 : 294 + index * 14]
        if raw[13] != 0 or any(value not in (0x30, 0x31) for value in raw[:13]):
            raise ParseError(280 + index * 14, "STF row", "expected 13 ASCII binary channels plus NUL", source)
        rows13.append(tuple(1 if value == 0x31 else 0 for value in raw[:13]))
    last_lm = max((index for index, row in enumerate(rows13) if any(row[10:13])), default=-1)
    final_index = max(last_p1, last_p2, last_lm)
    if final_index >= physical_rows:
        raise ParseError(0xFC, "STF final row", f"row index {final_index} exceeds backing grid", source)
    rows = tuple(rows13[: final_index + 1])
    lm_rows = tuple(tuple(row[10:13]) for row in rows)

    def timed(projected_rows):
        return (
            _PlainBlock(
                bpm,
                beat_measure,
                beat_split,
                start_time_cs * 10.0,
                tuple(projected_rows),
            ),
        )

    diagnostics = (
        "stf.header-timing: BPM/BeatMeasure/BeatSplit/start-time projected from the STF header",
        "stf.13-lane-layout: lanes 0..9 are playable and lanes 10..12 are Lightmap",
    )
    return AndamiroImportResult(
        _candidate_documents(
            rows,
            timed,
            source=source,
            source_format="stf",
            profile=profile,
            lightmap_rows=lm_rows,
            lightmap_blocks=timed,
            diagnostics=diagnostics,
        ),
        data,
        source,
    )


def _xor_not4(payload: bytes) -> bytes:
    return bytes(value ^ ((0xD2 + 0x95 * index) & 0xFF) for index, value in enumerate(payload))


def _expand_not4_rows(data: bytes, *, source: str) -> tuple[tuple[int, ...], ...]:
    decoded = _xor_not4(data[0x88:])
    rows: list[tuple[int, ...]] = []
    previous = -1
    for offset in range(0, len(decoded), 4):
        step_index, mask = struct.unpack_from("<HH", decoded, offset)
        if step_index <= previous:
            raise ParseError(0x88 + offset, "NOT4 row index", "sparse indexes are not strictly increasing", source)
        if mask & 0x0007:
            raise ParseError(0x88 + offset + 2, "NOT4 lane mask", "reserved low three bits are nonzero", source)
        previous = step_index
        padding = step_index - len(rows) - 1
        if padding > 0:
            rows.extend(((0,) * 13 for _ in range(padding)))
        rows.append(tuple(1 if mask & (1 << (15 - lane)) else 0 for lane in range(13)))
    p1_count, p2_count = struct.unpack_from("<HH", data, 0x84)
    line_count = max(p1_count, p2_count)
    if line_count > len(rows):
        rows.extend(((0,) * 13 for _ in range(line_count - len(rows))))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class _BunkiLineInfo:
    enter_lines: int = -1
    enter_offset_cs: float = -1.0
    exit_lines: int = -1
    exit_offset_cs: float = -1.0


def _filter_timing(bpms, starts, bunkis):
    valid_bpms = [bpms[0]]
    valid_starts = [starts[0]]
    valid_bunkis = []
    previous = -1
    for index, bunki in enumerate(bunkis):
        if bunki == 0:
            break
        if bunki == previous:
            continue
        if index + 1 >= len(bpms) or index + 1 >= len(starts):
            break
        valid_bpms.append(bpms[index + 1])
        valid_starts.append(starts[index + 1])
        valid_bunkis.append(bunki)
        previous = bunki
    return tuple(valid_bpms), tuple(valid_starts), tuple(valid_bunkis)


def _bunki_line_info(starts, bpms, bunkis, beat_split: int):
    if not bunkis:
        return ()
    result = []
    rows_per_cs = (bpms[0] / 6000.0) * beat_split
    raw = (bunkis[0] - starts[0]) * rows_per_cs
    first_exit = math.floor(raw)
    result.append(_BunkiLineInfo(exit_lines=first_exit, exit_offset_cs=(raw - first_exit) / rows_per_cs))
    for index, bunki in enumerate(bunkis):
        rows_per_cs = (bpms[index + 1] / 6000.0) * beat_split
        raw = (bunki - starts[index + 1]) * rows_per_cs
        enter = math.ceil(raw)
        enter_offset = (enter - raw) / rows_per_cs
        exit_lines = -1
        exit_offset = -1.0
        if index < len(bunkis) - 1:
            raw_exit = (bunkis[index + 1] - starts[index + 1]) * rows_per_cs
            exit_lines = math.floor(raw_exit)
            exit_offset = (raw_exit - exit_lines) / rows_per_cs
        result.append(_BunkiLineInfo(enter, enter_offset, exit_lines, exit_offset))
    return tuple(result)


def _not_blocks_for_rows(
    rows,
    *,
    bpms,
    starts,
    bunkis,
    beat_split: int,
    beat_measure: int,
    is_not5: bool,
):
    valid_bpms, valid_starts, valid_bunkis = _filter_timing(bpms, starts, bunkis)
    infos = _bunki_line_info(valid_starts, valid_bpms, valid_bunkis, beat_split)
    width = len(rows[0]) if rows else 1
    if not infos:
        selected = tuple(rows)
        if not is_not5:
            selected = ((0,) * width,) + selected
        return (_PlainBlock(valid_bpms[0], beat_measure, beat_split, valid_starts[0] * 10.0, selected),)
    blocks = []
    for index, info in enumerate(infos):
        begin = 0
        end = len(rows) - 1
        if info.enter_lines != -1:
            begin = info.enter_lines - (1 if is_not5 else 2)
        if info.exit_lines != -1:
            end = info.exit_lines - (1 if is_not5 else 2)
        begin = max(0, min(len(rows), begin))
        end = max(begin - 1, min(len(rows) - 1, end))
        selected = tuple(rows[begin : end + 1]) if end >= begin else ()
        if not is_not5 and index == 0:
            selected = ((0,) * width,) + selected
        if index == 0:
            delay_ms = valid_starts[0] * 10.0
        else:
            adjustment = 14.0 if is_not5 else 16.0
            delay_cs = max(math.floor(infos[index - 1].exit_offset_cs + info.enter_offset_cs - adjustment), 0)
            delay_ms = delay_cs * 10.0
        blocks.append(_PlainBlock(valid_bpms[index], beat_measure, beat_split, delay_ms, selected))
    return tuple(blocks)


def _load_not4(data: bytes, *, source: str, profile: str) -> AndamiroImportResult:
    if len(data) < 0x88 or (len(data) - 0x88) % 4:
        raise ParseError(0, "NOT4", "invalid 0x88 + record_count*4 size", source)
    record_count = struct.unpack_from("<I", data, 0)[0]
    actual_count = (len(data) - 0x88) // 4
    if record_count != actual_count:
        raise ParseError(0, "NOT4 record count", f"header says {record_count}, file stores {actual_count}", source)
    bpms = struct.unpack_from("<3f", data, 8)
    starts = struct.unpack_from("<3I", data, 24)
    bunkis = struct.unpack_from("<2I", data, 40)
    beat_split = struct.unpack_from("<I", data, 56)[0]
    beat_measure = struct.unpack_from("<I", data, 60)[0] or 4
    if beat_split <= 0:
        raise ParseError(56, "NOT4 Beat Split", "Beat Split must be positive", source)
    rows = _expand_not4_rows(data, source=source)
    lm_rows = tuple(tuple(row[10:13]) for row in rows)

    def timed(projected_rows):
        return _not_blocks_for_rows(
            tuple(projected_rows),
            bpms=bpms,
            starts=starts,
            bunkis=bunkis,
            beat_split=beat_split,
            beat_measure=beat_measure,
            is_not5=False,
        )

    diagnostics = (
        "not4.13-lane-mask: bits 15..6 are playable, bits 5..3 are Lightmap, bits 2..0 are padding",
        "not4.timing: BPM/StartTime/Bunki/BeatSplit/BeatMeasure projected with the StepEdit-era sparse-line convention",
    )
    return AndamiroImportResult(
        _candidate_documents(
            rows,
            timed,
            source=source,
            source_format="not",
            profile=profile,
            lightmap_rows=lm_rows,
            lightmap_blocks=timed,
            diagnostics=diagnostics,
        ),
        data,
        source,
    )


def _load_not5(data: bytes, *, source: str, profile: str) -> AndamiroImportResult:
    if len(data) < 0xD8 or not data.startswith(b"pump 5.0"):
        raise ParseError(0, "NOT5", "missing pump 5.0 header", source)
    line_count = struct.unpack_from("<I", data, 10)[0]
    expected = 0xD8 + line_count * 6
    if len(data) != expected:
        raise ParseError(10, "NOT5 line count", f"expected {expected} bytes from {line_count} rows, found {len(data)}", source)
    bpms = struct.unpack_from("<10f", data, 16)
    starts = struct.unpack_from("<10I", data, 56)
    bunkis = struct.unpack_from("<10I", data, 96)
    beat_split = struct.unpack_from("<I", data, 136)[0]
    beat_measure = struct.unpack_from("<I", data, 140)[0] or 16
    if beat_split <= 0:
        raise ParseError(136, "NOT5 Beat Split", "Beat Split must be positive", source)
    arrays = []
    position = 0xD8
    for label in ("steps", "hold heads", "hold tails"):
        raw = data[position : position + line_count * 2]
        words = struct.unpack(f"<{line_count}H", raw) if line_count else ()
        for index, word in enumerate(words):
            expected_high = 0xFC00 if word & 0x0200 else 0
            if (word & 0xFC00) != expected_high:
                raise ParseError(position + index * 2, f"NOT5 {label}", "invalid signed 10-bit mask extension", source)
        arrays.append(tuple(word & 0x03FF for word in words))
        position += line_count * 2
    holding = [False] * 10
    rows = []
    for row_index in range(line_count):
        step, head, tail = (array[row_index] for array in arrays)
        cells = [0] * 10
        for bit in range(10):
            mask = 1 << bit
            lane = 9 - bit
            if (head & mask) and (tail & mask):
                raise ParseError(0xD8 + row_index * 2, "NOT5 hold", "head and tail share one row/lane", source)
            if not (step & mask):
                continue
            if head & mask:
                if holding[lane]:
                    raise ParseError(0xD8 + row_index * 2, "NOT5 hold", "nested hold head", source)
                holding[lane] = True
                cells[lane] = 2
            elif tail & mask:
                if not holding[lane]:
                    raise ParseError(0xD8 + row_index * 2, "NOT5 hold", "tail without open hold", source)
                holding[lane] = False
                cells[lane] = 4
            elif holding[lane]:
                cells[lane] = 3
            else:
                cells[lane] = 1
        rows.append(tuple(cells))
    if any(holding):
        raise ParseError(len(data), "NOT5 hold", "file ends with an open hold", source)
    rows = tuple(rows)

    def timed(projected_rows):
        return _not_blocks_for_rows(
            tuple(projected_rows),
            bpms=bpms,
            starts=starts,
            bunkis=bunkis,
            beat_split=beat_split,
            beat_measure=beat_measure,
            is_not5=True,
        )

    diagnostics = (
        "not5.mask-width: step/head/tail arrays use signed 10-bit playable masks; upper bits are sign extension, not Lightmap",
        "not5.timing: BPM/StartTime/Bunki/BeatSplit/BeatMeasure projected from the pump 5.0 header",
    )
    return AndamiroImportResult(
        _candidate_documents(rows, timed, source=source, source_format="not5", profile=profile, diagnostics=diagnostics),
        data,
        source,
    )


def _load_stx(data: bytes, *, source: str, profile: str) -> AndamiroImportResult:
    from stepnx.importers.see import SEE_MODES, _SEEBlock, _build_nx10

    if len(data) < 0x120 or data[:4] != b"STF4":
        raise ParseError(0, "STX", "missing STF4 header", source)
    addresses = struct.unpack_from("<9I", data, 0xFC)
    if any(address < 0x120 or address >= len(data) for address in addresses):
        raise ParseError(0xFC, "STX chart address table", "chart address lies outside file", source)
    if any(right < left for left, right in zip(addresses, addresses[1:])):
        raise ParseError(0xFC, "STX chart address table", "chart addresses are not ordered", source)
    results = []
    for mode in SEE_MODES:
        start = addresses[mode.index]
        end = addresses[mode.index + 1] if mode.index + 1 < len(addresses) else len(data)
        if end - start < 204:
            raise ParseError(start, f"STX {mode.key}", "section shorter than difficulty + 50 split counts", source)
        difficulty = struct.unpack_from("<I", data, start)[0]
        counts = struct.unpack_from("<50I", data, start + 4)
        first_zero = next((index for index, count in enumerate(counts) if count == 0), 50)
        if any(counts[first_zero + 1 :]):
            raise ParseError(start + 4 + first_zero * 4, f"STX {mode.key}", "split counts are non-contiguous", source)
        position = start + 204
        splits = []
        for split_index, count in enumerate(counts[:first_zero]):
            blocks = []
            for block_index in range(count):
                if position + 4 > end:
                    raise ParseError(position, f"STX {mode.key}", "missing compressed block length", source)
                compressed_size = struct.unpack_from("<I", data, position)[0]
                size_offset = position
                position += 4
                if compressed_size <= 0 or position + compressed_size > end:
                    raise ParseError(size_offset, f"STX {mode.key}", f"invalid compressed size {compressed_size}", source)
                compressed_offset = position
                try:
                    decoded = zlib.decompress(data[position : position + compressed_size])
                except zlib.error as exc:
                    raise ParseError(position, f"STX {mode.key}", f"zlib error: {exc}", source) from exc
                position += compressed_size
                if len(decoded) < 0x84:
                    raise ParseError(compressed_offset, f"STX {mode.key}", "decoded block shorter than 0x84 bytes", source)
                bpm, _measure, beat_split, _delay = struct.unpack_from("<fIIi", decoded, 0)
                row_count = struct.unpack_from("<I", decoded, 0x80)[0]
                if not math.isfinite(bpm) or bpm <= 0 or beat_split <= 0:
                    raise ParseError(compressed_offset, f"STX {mode.key}", f"invalid timing BPM={bpm!r} Split={beat_split}", source)
                if len(decoded) != 0x84 + row_count * 13:
                    raise ParseError(compressed_offset, f"STX {mode.key}", f"row count {row_count} does not match decoded size", source)
                blocks.append(_SEEBlock(compressed_offset, decoded))
            splits.append(tuple(blocks))
        if not splits:
            raise ParseError(start + 4, f"STX {mode.key}", "section contains no splits", source)
        if position != end and any(data[position:end]):
            raise ParseError(position, f"STX {mode.key}", f"{end - position} unexpected trailing byte(s)", source)
        nx10 = _build_nx10(mode, tuple(splits))
        imported = import_nx10_bytes(nx10, source=f"{source}/{mode.key}.NX", profile=profile)
        diagnostics = tuple(
            f"{diagnostic.kind.value}: {diagnostic.code}: {diagnostic.message}"
            + (f" [{diagnostic.path}]" if diagnostic.path else "")
            for diagnostic in imported.report.diagnostics
        )
        results.append(
            AndamiroChartResult(
                mode.key,
                f"{mode.key} — {mode.label} (difficulty {difficulty})",
                "stx",
                imported.document,
                f"{mode.key}.NX",
                diagnostics,
                imported.report.is_semantically_lossless,
            )
        )
    return AndamiroImportResult(tuple(results), data, source)


def load_andamiro(path: str | Path, *, profile: str = "nxa-native") -> AndamiroImportResult:
    source_path = Path(path)
    data = source_path.read_bytes()
    suffix = source_path.suffix.casefold()
    source = str(source_path)
    if suffix in {".stf", ".st2"}:
        return _load_stf(data, source=source, profile=profile)
    if suffix in {".not", ".not5"}:
        if data.startswith(b"pump 5.0"):
            return _load_not5(data, source=source, profile=profile)
        return _load_not4(data, source=source, profile=profile)
    if suffix == ".stx":
        return _load_stx(data, source=source, profile=profile)
    raise ValueError(f"unsupported Andamiro legacy suffix: {source_path.suffix}")
