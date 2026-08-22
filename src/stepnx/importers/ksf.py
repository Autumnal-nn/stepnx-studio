from __future__ import annotations

import math
import re
from pathlib import Path

from stepnx.core.errors import ParseError
from stepnx.importers.andamiro import (
    AndamiroChartResult,
    AndamiroImportResult,
    _PlainBlock,
    _build_nx20,
)

_HEADER = re.compile(r"^#([A-Za-z0-9_]+)\s*:\s*(.*?)\s*;?$")
_CONTROL = re.compile(r"^([BTDE])\s*:\s*(.*?)\s*;?$", re.I)
_END_ROW = re.compile(r"^2{10,13};?$")


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


def import_bytes(
    data: bytes,
    *,
    source: str | None = None,
    profile: str = "nxa-native",
) -> AndamiroImportResult:
    source_name = source or "legacy.KSF"
    text = _decode(data)
    headers: dict[str, str] = {}
    controls: list[tuple[str, str]] = []
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
        control = _CONTROL.match(line)
        if control:
            controls.append(
                (
                    control.group(1).upper(),
                    control.group(2).strip().removesuffix(";").strip(),
                )
            )
            continue
        row = line.removesuffix(";").strip()
        if len(row) not in (10, 13):
            raise ParseError(
                line_number,
                "KSF row",
                f"expected 10 or 13 channels, found {len(row)}",
                source_name,
            )
        if any(character not in "0123456789abcdefABCDEF" for character in row):
            raise ParseError(line_number, "KSF row", "non-hexadecimal channel", source_name)
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
    playable = [
        [int(character, 16) for character in row[:10]]
        for row in normalized
    ]
    _expand_holds(playable)
    playable_rows = tuple(tuple(row) for row in playable)
    p2_active = any(any(row[5:10]) for row in playable_rows)
    stem = Path(source_name).stem
    diagnostics = [
        "ksf.starttime-centiseconds: #STARTTIME is multiplied by 10 to project milliseconds",
        f"ksf.row-width: source uses {width} channels",
    ]
    if controls:
        diagnostics.append(
            "ksf.controls-not-projected: B/T/D/E Direct Move controls remain source-only"
        )
    if any(
        key.startswith(("BPM", "BUNKI", "STARTTIME"))
        and key not in {"BPM", "STARTTIME"}
        for key in headers
    ):
        diagnostics.append(
            "ksf.extended-timing-not-projected: numbered BPM/BUNKI/STARTTIME fields remain source-only"
        )

    results: list[AndamiroChartResult] = []

    def block(rows):
        return (
            _PlainBlock(
                bpm,
                4,
                tick,
                start_time_ms,
                tuple(rows),
            ),
        )

    if p2_active:
        p1_rows = tuple(tuple(row[:5]) for row in playable_rows)
        p2_rows = tuple(tuple(row[5:10]) for row in playable_rows)
        results.append(
            AndamiroChartResult(
                "p1",
                "KSF — Player 1",
                "ksf",
                _build_nx20(
                    block(p1_rows),
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
                    block(p2_rows),
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
                    block(p1_rows),
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
            tuple(1 if int(character, 16) else 0 for character in row[10:13])
            for row in normalized
        )
        lm_note = "embedded KSF channels 10..12"
    else:
        lightmap_rows = tuple((0, 0, 0) for _ in normalized)
        lm_note = "10-channel KSF has no embedded Lightmap; generated empty LM"
    lm_document = _build_nx20(
        block(lightmap_rows),
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
