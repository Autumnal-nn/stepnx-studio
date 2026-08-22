from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from pathlib import Path

from stepnx.core.errors import ParseError
from stepnx.core.scalars import RawU32
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
_TIMING_CONTROL_CODES = frozenset("BTED")
_LEGACY_TIMING_KEYS = frozenset(
    {"BPM2", "BPM3", "BUNKI", "BUNKI2", "STARTTIME2", "STARTTIME3"}
)
_HALFDOUBLE_NAMES = ("halfdouble", "half-double", "h_double", "hdb")
_DOUBLE_TOKEN = re.compile(r"(?:^|[_-])(?:db|nm|fs)(?:$|[_-])", re.I)


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
        value = float(raw)
    except ValueError as exc:
        raise ParseError(0, f"KSF {key}", f"invalid numeric value {raw!r}", source) from exc
    if not math.isfinite(value):
        raise ParseError(0, f"KSF {key}", f"value must be finite, found {value!r}", source)
    return value


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


def _unsupported_control_diagnostics(controls: tuple[_Control, ...]) -> tuple[str, ...]:
    unsupported = sorted({control.code for control in controls if control.code not in _TIMING_CONTROL_CODES})
    if not unsupported:
        return ()
    return (
        "ksf.direct-move-controls-not-projected: inline controls "
        + ", ".join(unsupported)
        + " remain source-only and do not create note/item cells",
    )


def _timing_segments(
    row_count: int,
    controls: tuple[_Control, ...],
    *,
    initial_bpm: float,
    initial_tick: int,
    initial_delay_ms: float,
    source: str,
) -> tuple[tuple[_Segment, ...], tuple[str, ...]]:
    """Project Direct Move inline timing controls to homogeneous row segments."""

    bpm = initial_bpm
    tick = initial_tick
    pending_delay = initial_delay_ms
    start_row = 0
    segments: list[_Segment] = []
    diagnostics: list[str] = []
    projected_counts = {"B": 0, "T": 0, "E": 0, "D": 0}

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
        if code not in _TIMING_CONTROL_CODES:
            continue

        boundary = max(0, min(row_count, control.row_index))
        if boundary > start_row:
            flush(boundary)

        if code == "B":
            if value <= 0:
                raise ParseError(
                    control.line_number,
                    "KSF Direct Move BPM",
                    f"|B...| must be positive, found {value!r}",
                    source,
                )
            bpm = value
            projected_counts["B"] += 1
        elif code == "T":
            if value <= 0 or not value.is_integer():
                raise ParseError(
                    control.line_number,
                    "KSF Direct Move TICKCOUNT",
                    f"|T...| must be a positive integer, found {value!r}",
                    source,
                )
            tick = int(value)
            projected_counts["T"] += 1
        elif code == "E":
            pending_delay += 60_000.0 / bpm * value / tick
            projected_counts["E"] += 1
        elif code == "D":
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
    diagnostics.extend(_unsupported_control_diagnostics(controls))
    return tuple(segments), tuple(diagnostics)


def _ceil_legacy_row(value: float) -> int:
    # Suppress floating-point noise around exact historical row boundaries.
    return int(math.ceil(value - 1e-9))


def _legacy_header_segments(
    row_count: int,
    headers: dict[str, str],
    *,
    initial_bpm: float,
    initial_tick: int,
    source: str,
) -> tuple[tuple[_Segment, ...], tuple[str, ...]]:
    """Project Kick It Up BPM/STARTTIME/BUNKI timing to NX block anchors.

    The original KIU runtime stores three BPMs and three STARTTIMEs. At each
    non-zero BUNKI it swaps both the BPM and the timing anchor. This is the
    same timing model carried by NOT4, but KSF rows are already explicit and
    therefore do not need NOT4's sparse-record padding corrections.
    """

    initial_start = _number(headers, "STARTTIME", 0.0, source=source)
    transition_specs = (
        ("BUNKI", "BPM2", "STARTTIME2"),
        ("BUNKI2", "BPM3", "STARTTIME3"),
    )
    transitions: list[tuple[float, float, float, str]] = []
    for bunki_key, bpm_key, start_key in transition_specs:
        bunki = _number(headers, bunki_key, 0.0, source=source)
        if bunki <= 0:
            continue
        next_bpm = _number(headers, bpm_key, 0.0, source=source)
        if next_bpm <= 0:
            raise ParseError(
                0,
                "KSF Kick It Up timing",
                f"{bunki_key}={bunki:g} requires a positive {bpm_key}",
                source,
            )
        next_start = _number(headers, start_key, 0.0, source=source)
        transitions.append((bunki, next_bpm, next_start, bunki_key))

    for previous, current in zip(transitions, transitions[1:]):
        if current[0] <= previous[0]:
            raise ParseError(
                0,
                "KSF Kick It Up timing",
                "BUNKI transition times must be strictly increasing",
                source,
            )

    states: list[tuple[float, float]] = [(initial_bpm, initial_start)]
    states.extend((bpm, start) for _, bpm, start, _ in transitions)
    boundaries = [bunki for bunki, _, _, _ in transitions]

    segments: list[_Segment] = []
    previous_absolute_end = 0.0
    previous_source_end = 0
    remaps: list[str] = []

    for index, (bpm, start_cs) in enumerate(states):
        rows_per_cs = bpm / 6000.0 * initial_tick
        row_ms = 60_000.0 / (bpm * initial_tick)
        if index == 0:
            begin = 0
        else:
            begin = _ceil_legacy_row((boundaries[index - 1] - start_cs) * rows_per_cs)
        if index < len(boundaries):
            end = _ceil_legacy_row((boundaries[index] - start_cs) * rows_per_cs)
        else:
            end = row_count

        begin = max(0, min(row_count, begin))
        end = max(begin, min(row_count, end))

        if index and begin != previous_source_end:
            direction = "skips" if begin > previous_source_end else "replays"
            remaps.append(
                f"{boundaries[index - 1]:g}cs {direction} source rows "
                f"{previous_source_end}..{begin}"
            )

        if end > begin:
            absolute_start = start_cs * 10.0 + begin * row_ms
            delay_ms = absolute_start if not segments else absolute_start - previous_absolute_end
            segments.append(_Segment(begin, end, bpm, initial_tick, delay_ms))
            previous_absolute_end = absolute_start + (end - begin) * row_ms
        previous_source_end = end

    if not segments and row_count:
        segments.append(_Segment(0, row_count, initial_bpm, initial_tick, initial_start * 10.0))

    diagnostics = [
        "ksf.kiu-header-timing: projected BPM2/BPM3 + BUNKI/BUNKI2 + "
        "STARTTIME2/STARTTIME3 using the original Kick It Up segment-anchor model"
    ]
    if not transitions:
        diagnostics.append(
            "ksf.kiu-header-timing-unused: numbered timing fields are present but no "
            "non-zero BUNKI transition is active"
        )
    if remaps:
        diagnostics.append(
            "ksf.kiu-row-remap: STARTTIME segment anchors intentionally remap the source "
            "row cursor (" + "; ".join(remaps) + ")"
        )
    return tuple(segments), tuple(diagnostics)


def _ksf_mode(source_name: str, headers: dict[str, str], *, p2_active: bool) -> str:
    stem = Path(source_name).stem.casefold()
    player = headers.get("PLAYER", "").strip().casefold()

    if any(token in stem for token in _HALFDOUBLE_NAMES):
        return "halfdouble"
    if "double" in player:
        return "double"
    if "couple" in player:
        return "couple"
    if player == "single":
        return "single"

    if (
        "double" in stem
        or "nightmare" in stem
        or "freestyle" in stem
        or _DOUBLE_TOKEN.search(stem)
    ):
        return "double"
    if stem.endswith("_2"):
        return "couple"
    if stem.endswith("_1"):
        return "single"
    return "couple" if p2_active else "single"


def _has_activity(rows: tuple[tuple[int, ...], ...]) -> bool:
    return any(any(row) for row in rows)


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
    if bpm <= 0:
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

    extended_timing = any(key in headers for key in _LEGACY_TIMING_KEYS)
    inline_timing = any(control.code in _TIMING_CONTROL_CODES for control in controls)
    if extended_timing and inline_timing:
        raise ParseError(
            0,
            "KSF timing syntax",
            "file mixes Kick It Up BPM2/BUNKI/STARTTIME2 timing with Direct Move "
            "B/T/E/D controls; coexistence is not verified",
            source_name,
        )

    if extended_timing:
        segments, timing_diagnostics = _legacy_header_segments(
            len(playable_rows),
            headers,
            initial_bpm=bpm,
            initial_tick=tick,
            source=source_name,
        )
        timing_diagnostics += _unsupported_control_diagnostics(tuple(controls))
    else:
        segments, timing_diagnostics = _timing_segments(
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
        *timing_diagnostics,
    ]

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
    mode = _ksf_mode(source_name, headers, p2_active=p2_active)
    diagnostics.append(f"ksf.mode: classified source as {mode}")

    if mode == "double":
        rows10 = tuple(tuple(row[:10]) for row in playable_rows)
        results.append(
            AndamiroChartResult(
                "double",
                "KSF — Double",
                "ksf",
                _build_nx20(
                    blocks_for_rows(rows10),
                    columns=10,
                    lightmap=False,
                    source=f"{source_name} [KSF Double projection]",
                    profile=profile,
                ),
                f"{stem}.NX",
                tuple(diagnostics + ["ksf.bank-layout: playable lanes 0..9 kept as one Double chart"]),
            )
        )
    elif mode == "halfdouble":
        rows6 = tuple(tuple(row[2:8]) for row in playable_rows)
        document = _build_nx20(
            blocks_for_rows(rows6),
            columns=6,
            lightmap=False,
            source=f"{source_name} [KSF Half Double projection]",
            profile=profile,
        )
        document = replace(document, start_column=RawU32.from_value(2))
        results.append(
            AndamiroChartResult(
                "halfdouble",
                "KSF — Half Double",
                "ksf",
                document,
                f"{stem}.NX",
                tuple(diagnostics + ["ksf.bank-layout: lanes 2..7 projected as 6-lane Half Double at start_column=2"]),
            )
        )
    elif mode == "couple":
        p1_rows = tuple(tuple(row[:5]) for row in playable_rows)
        p2_rows = tuple(tuple(row[5:10]) for row in playable_rows)
        if _has_activity(p1_rows):
            results.append(
                AndamiroChartResult(
                    "p1",
                    "KSF — Player 1",
                    "ksf",
                    _build_nx20(
                        blocks_for_rows(p1_rows),
                        columns=5,
                        lightmap=False,
                        source=f"{source_name} [KSF Couple P1 projection]",
                        profile=profile,
                    ),
                    f"{stem}_P1.NX",
                    tuple(diagnostics + ["ksf.couple-bank: lanes 0..4 projected as Player 1"]),
                )
            )
        if _has_activity(p2_rows):
            results.append(
                AndamiroChartResult(
                    "p2",
                    "KSF — Player 2",
                    "ksf",
                    _build_nx20(
                        blocks_for_rows(p2_rows),
                        columns=5,
                        lightmap=False,
                        source=f"{source_name} [KSF Couple P2 projection]",
                        profile=profile,
                    ),
                    f"{stem}_P2.NX",
                    tuple(diagnostics + ["ksf.couple-bank: lanes 5..9 projected as Player 2"]),
                )
            )
    else:
        p1_rows = tuple(tuple(row[:5]) for row in playable_rows)
        results.append(
            AndamiroChartResult(
                "chart",
                "KSF — Single",
                "ksf",
                _build_nx20(
                    blocks_for_rows(p1_rows),
                    columns=5,
                    lightmap=False,
                    source=f"{source_name} [KSF Single projection]",
                    profile=profile,
                ),
                f"{stem}.NX",
                tuple(
                    diagnostics
                    + [
                        "ksf.bank-layout: Single uses lanes 0..4"
                        + ("; activity in lanes 5..9 is ignored by Single semantics" if p2_active else "")
                    ]
                ),
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
