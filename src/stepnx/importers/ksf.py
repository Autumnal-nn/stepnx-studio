from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from stepnx.core.errors import ParseError
from stepnx.importers.andamiro import (
    AndamiroChartResult,
    AndamiroImportResult,
    _PlainBlock,
    _build_nx20,
)

_HEADER = re.compile(r"^#([A-Za-z0-9_]+)\s*:\s*(.*?)\s*;?$")
_PIPE_CONTROL = re.compile(
    r"^\|([A-Za-z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\|$"
)
_COLON_CONTROL = re.compile(
    r"^([A-Za-z])\s*:\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*;?$"
)
_END_ROW = re.compile(r"^2{10,13};?$")
_SUPPORTED_ROW_CHARS = frozenset("014")


@dataclass(frozen=True, slots=True)
class _Control:
    row_index: int
    code: str
    value: float
    line_number: int


@dataclass(frozen=True, slots=True)
class _Segment:
    start_row: int
    end_row: int
    bpm: float
    tick: int
    delay_ms: float


def _decode(data: bytes) -> str:
    for encoding in ("cp949", "utf-8-sig", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AssertionError("latin-1 decode unexpectedly failed")


def _number(headers: dict[str, str], key: str, default: float, *, source: str) -> float:
    raw = headers.get(key, str(default)).strip().removesuffix(";").strip()
    try:
        return float(raw)
    except ValueError as exc:
        raise ParseError(0, f"KSF {key}", f"invalid numeric value {raw!r}", source) from exc


def _expand_holds(rows: list[list[int]]) -> None:
    for lane in range(10):
        index = 0
        while index < len(rows):
            if rows[index][lane] != 4:
                index += 1
                continue
            end = index
            while end + 1 < len(rows) and rows[end + 1][lane] == 4:
                end += 1
            if end == index:
                rows[index][lane] = 1
            else:
                rows[index][lane] = 2
                for body in range(index + 1, end):
                    rows[body][lane] = 3
                rows[end][lane] = 4
            index = end + 1


def _parse_control(line: str, *, row_index: int, line_number: int) -> _Control | None:
    match = _PIPE_CONTROL.fullmatch(line) or _COLON_CONTROL.fullmatch(line)
    if match is None:
        return None
    code, raw_value = match.groups()
    try:
        value = float(raw_value)
    except ValueError:
        return None
    return _Control(row_index, code.upper(), value, line_number)


def _timing_segments(
    row_count: int,
    controls: tuple[_Control, ...],
    *,
    initial_bpm: float,
    initial_tick: int,
    initial_delay_ms: float,
    source: str,
) -> tuple[tuple[_Segment, ...], tuple[str, ...]]:
    """Project Direct Move inline timing controls to homogeneous row segments.

    Direct Move control lines do not consume a step row. B/T change the
    timing state at the current row boundary. E/D add a delay at that
    boundary. Other Direct Move extensions are preserved as diagnostics
    rather than being mistaken for KSF note cells.
    """

    bpm = initial_bpm
    tick = initial_tick
    pending_delay = initial_delay_ms
    start_row = 0
    segments: list[_Segment] = []
    diagnostics: list[str] = []
    projected_counts = {"B": 0, "T": 0, "E": 0, "D": 0}
    unsupported: list[_Control] = []

    def flush(end_row: int) -> None:
        nonlocal start_row, pending_delay
        if end_row <= start_row:
            return
        segments.append(_Segment(start_row, end_row, bpm, tick, pending_delay))
        start_row = end_row
        pending_delay = 0.0

    for control in controls:
        code = control.code
        value = control.value
        if code not in {"B", "T", "E", "D"}:
            unsupported.append(control)
            continue

        boundary = max(0, min(row_count, control.row_index))
        if boundary > start_row:
            flush(boundary)

        if code == "B":
            if not math.isfinite(value) or value <= 0:
                raise ParseError(
                    control.line_number,
                    "KSF Direct Move BPM",
                    f"|B...| must be positive, found {value!r}",
                    source,
                )
            bpm = value
            projected_counts["B"] += 1
        elif code == "T":
            if not math.isfinite(value) or value <= 0 or not value.is_integer():
                raise ParseError(
                    control.line_number,
                    "KSF Direct Move TICKCOUNT",
                    f"|T...| must be a positive integer, found {value!r}",
                    source,
                )
            tick = int(value)
            projected_counts["T"] += 1
        elif code == "E":
            if not math.isfinite(value):
                raise ParseError(
                    control.line_number,
                    "KSF Direct Move beat delay",
                    f"|E...| must be finite, found {value!r}",
                    source,
                )
            # Direct Move semantics as preserved by the StepMania KSF loader:
            # delay_seconds = 60 / current_BPM * value / current_TICKCOUNT.
            pending_delay += 60_000.0 / bpm * value / tick
            projected_counts["E"] += 1
        elif code == "D":
            if not math.isfinite(value):
                raise ParseError(
                    control.line_number,
                    "KSF Direct Move millisecond delay",
                    f"|D...| must be finite, found {value!r}",
                    source,
                )
            pending_delay += value
            projected_counts["D"] += 1

    if start_row < row_count:
        flush(row_count)

    if not segments and row_count:
        segments.append(_Segment(0, row_count, bpm, tick, pending_delay))

    if any(projected_counts.values()):
        summary = ", ".join(
            f"{code}={count}" for code, count in projected_counts.items() if count
        )
        diagnostics.append(
            "ksf.direct-move-timing: projected inline Direct Move controls "
            f"as NX block boundaries ({summary})"
        )
    if unsupported:
        codes = ", ".join(sorted({control.code for control in unsupported}))
        diagnostics.append(
            "ksf.direct-move-controls-not-projected: inline controls "
            f"{codes} remain source-only and do not create note/item cells"
        )

    return tuple(segments), tuple(diagnostics)


def import_bytes(
    data: bytes,
    *,
    source: str | None = None,
    profile: str = "nxa-native",
) -> AndamiroImportResult:
    source_name = source or "legacy.KSF"
    text = _decode(data)
    headers: dict[str, str] = {}
    controls: list[_Control] = []
    physical_rows: list[str] = []
    in_steps = False

    for line_number, physical in enumerate(text.splitlines(), 1):
        line = physical.strip()
        if not line or line.startswith("//"):
            continue
        if not in_steps:
            match = _HEADER.match(line)
            if match is None:
                continue
            key, value = match.groups()
            key = key.upper()
            headers[key] = value.strip().removesuffix(";").strip()
            if key in {"STEP", "STEPS"}:
                in_steps = True
            continue

        if _END_ROW.fullmatch(line):
            break
        if line.upper().removesuffix(";") in {"#END", "#ENDSTEP", "#ENDSTEPS"}:
            break

        control = _parse_control(
            line,
            row_index=len(physical_rows),
            line_number=line_number,
        )
        if control is not None:
            controls.append(control)
            continue

        # Pipe-delimited input is Direct Move control syntax, never a note
        # row. Reject malformed payloads rather than turning characters inside
        # them into bogus NX item IDs.
        if line.startswith("|") and line.endswith("|"):
            raise ParseError(
                line_number,
                "KSF Direct Move control",
                f"unsupported or malformed control {line!r}",
                source_name,
            )

        row = line.removesuffix(";").strip()
        if len(row) not in (10, 13):
            raise ParseError(
                line_number,
                "KSF row",
                f"expected 10 or 13 channels, found {len(row)}",
                source_name,
            )
        invalid = sorted(set(row) - _SUPPORTED_ROW_CHARS)
        if invalid:
            raise ParseError(
                line_number,
                "KSF row",
                "unsupported KSF note cell(s) "
                + ", ".join(repr(character) for character in invalid)
                + "; Direct Move timing belongs in |...| control lines",
                source_name,
            )
        physical_rows.append(row)

    if not physical_rows:
        raise ParseError(0, "KSF", "missing step rows", source_name)

    bpm = _number(headers, "BPM", 120.0, source=source_name)
    if not math.isfinite(bpm) or bpm <= 0:
        raise ParseError(0, "KSF BPM", f"BPM must be positive, found {bpm!r}", source_name)
    tick_value = _number(headers, "TICKCOUNT", 4.0, source=source_name)
    if not tick_value.is_integer() or tick_value <= 0:
        raise ParseError(0, "KSF TICKCOUNT", "TICKCOUNT must be a positive integer", source_name)
    tick = int(tick_value)
    start_time_cs = _number(headers, "STARTTIME", 0.0, source=source_name)
    start_time_ms = start_time_cs * 10.0

    width = max(len(row) for row in physical_rows)
    normalized = [row.ljust(13, "0") for row in physical_rows]
    playable = [[int(character) for character in row[:10]] for row in normalized]
    _expand_holds(playable)
    playable_rows = tuple(tuple(row) for row in playable)
    p2_active = any(any(row[5:10]) for row in playable_rows)
    stem = Path(source_name).stem

    segments, direct_move_diagnostics = _timing_segments(
        len(playable_rows),
        tuple(controls),
        initial_bpm=bpm,
        initial_tick=tick,
        initial_delay_ms=start_time_ms,
        source=source_name,
    )

    diagnostics = [
        "ksf.starttime-centiseconds: #STARTTIME is multiplied by 10 to project milliseconds",
        f"ksf.row-width: source uses {width} channels",
        *direct_move_diagnostics,
    ]
    if any(
        key.startswith(("BPM", "BUNKI", "STARTTIME"))
        and key not in {"BPM", "STARTTIME"}
        for key in headers
    ):
        diagnostics.append(
            "ksf.extended-timing-not-projected: numbered BPM/BUNKI/STARTTIME "
            "fields remain source-only pending verified KIU/StepEdit block semantics"
        )

    def blocks_for_rows(rows):
        rows = tuple(rows)
        return tuple(
            _PlainBlock(
                segment.bpm,
                4,
                segment.tick,
                segment.delay_ms,
                rows[segment.start_row : segment.end_row],
            )
            for segment in segments
            if segment.end_row > segment.start_row
        )

    results: list[AndamiroChartResult] = []

    if p2_active:
        p1_rows = tuple(tuple(row[:5]) for row in playable_rows)
        p2_rows = tuple(tuple(row[5:10]) for row in playable_rows)
        results.append(
            AndamiroChartResult(
                "p1",
                "KSF — Player 1",
                "ksf",
                _build_nx20(
                    blocks_for_rows(p1_rows),
                    columns=5,
                    lightmap=False,
                    source=f"{source_name} [KSF P1 projection]",
                    profile=profile,
                ),
                f"{stem}_P1.NX",
                tuple(diagnostics),
            )
        )
        results.append(
            AndamiroChartResult(
                "p2",
                "KSF — Player 2",
                "ksf",
                _build_nx20(
                    blocks_for_rows(p2_rows),
                    columns=5,
                    lightmap=False,
                    source=f"{source_name} [KSF P2 projection]",
                    profile=profile,
                ),
                f"{stem}_P2.NX",
                tuple(diagnostics),
            )
        )
    else:
        p1_rows = tuple(tuple(row[:5]) for row in playable_rows)
        results.append(
            AndamiroChartResult(
                "chart",
                "KSF — chart",
                "ksf",
                _build_nx20(
                    blocks_for_rows(p1_rows),
                    columns=5,
                    lightmap=False,
                    source=f"{source_name} [KSF projection]",
                    profile=profile,
                ),
                f"{stem}.NX",
                tuple(diagnostics),
            )
        )

    if width == 13:
        lightmap_rows = tuple(
            tuple(1 if int(character) else 0 for character in row[10:13])
            for row in normalized
        )
        lm_note = "embedded KSF channels 10..12"
    else:
        lightmap_rows = tuple((0, 0, 0) for _ in normalized)
        lm_note = "10-channel KSF has no embedded Lightmap; generated empty LM"
    lm_document = _build_nx20(
        blocks_for_rows(lightmap_rows),
        columns=3,
        lightmap=True,
        source=f"{source_name} [KSF Lightmap projection]",
        profile=profile,
    )
    results.append(
        AndamiroChartResult(
            "LM",
            "LM — KSF Lightmap",
            "ksf",
            lm_document,
            "LM.NX",
            tuple(diagnostics + [f"ksf.lightmap: {lm_note}"]),
        )
    )
    return AndamiroImportResult(tuple(results), data, source_name)


def load(path: str | Path, *, profile: str = "nxa-native") -> AndamiroImportResult:
    source = Path(path)
    return import_bytes(source.read_bytes(), source=str(source), profile=profile)
