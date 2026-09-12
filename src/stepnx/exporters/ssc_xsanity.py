"""Runtime-facing rendering for semantic XSanity SSC exports.

The semantic compiler materializes NX load-time random choices into XSanity
``LABELTYPE:DIVISION`` helpers. Runtime testing showed that changing Steps in
the middle of gameplay is not transparent: visible taps can disappear and an
active hold can be severed even when both charts contain equivalent nearby
notes. NX ``0x8_`` decisions are load-time decisions, so the XSanity runtime
projection now performs exactly one StepSwap before the first judged note and
keeps the selected helper active for the rest of the chart.

The compiler may still build sparse multi-window helpers internally because
that representation is compact and convenient for planning. This renderer
reconstructs each full helper by overlaying those sparse random windows onto
the NORMAL chart, removes every Wrap0 return, then places one T in the earliest
safe pre-note row. That avoids all mid-song StepSwap seams while retaining the
chosen helper pool and per-split ticket distribution.

Current evidence-driven rules:

* random helper pools require song-level ``#SPECIAL:LEVEL,RANDOM;``;
* generated ``LABELTYPE:DIVISION`` Steps receive a non-empty unique
  ``#CHARTNAME``;
* ``#TICKCOUNTS`` follows the writer's virtual row grid;
* XSanity Wrap selects from the DIVISION pool of the same StepsType, so a
  combined SSC may contain at most one random source chart per StepsType until
  a narrower runtime filter is proven;
* startup random requires at least one row before the first judged note. If the
  source begins immediately at row zero, export fails instead of gambling on
  same-row StepSwap ordering.
"""

from __future__ import annotations

from dataclasses import replace

from stepnx.exporters.ssc import (
    LINES_PER_MEASURE,
    LINE_BEAT_SPLIT,
    SscExportError,
    SscSongInfo,
    render_simfile,
)
from stepnx.exporters.ssc_random import SscLabeledChart, SscRandomExportReport

_CORPUS_VERSION_LINE = "#VERSION:0.83;"
_PR_VERSION_LINE = "#VERSION:0.83 xSanity;"
_RANDOM_SPECIAL_LINE = "#SPECIAL:LEVEL,RANDOM;"
_WRAP = "T"
_RETURN = "O"


def _single_chart_name(item: SscLabeledChart) -> str:
    if item.helper_index is None:
        return "STEPNX_BASE"
    return f"STEPNX_RANDOM_{item.helper_index + 1:03d}"


def _combined_chart_names(
    reports: tuple[SscRandomExportReport, ...],
) -> tuple[str, ...]:
    names: list[str] = []
    for report_index, report in enumerate(reports, 1):
        prefix = f"STEPNX_{report_index:02d}"
        for item in report.charts:
            if item.helper_index is None:
                names.append(prefix + "_BASE")
            else:
                names.append(prefix + f"_RANDOM_{item.helper_index + 1:04d}")
    return tuple(names)


def _validate_combined_random_pools(
    reports: tuple[SscRandomExportReport, ...],
) -> None:
    random_by_type: dict[str, int] = {}
    for report in reports:
        if report.helper_count <= 0 or not report.charts:
            continue
        steps_type = report.charts[0].chart.steps_type
        random_by_type[steps_type] = random_by_type.get(steps_type, 0) + 1
    conflicts = sorted(steps_type for steps_type, count in random_by_type.items() if count > 1)
    if conflicts:
        raise SscExportError(
            "combined SSC contains more than one random chart for StepsType(s): "
            + ", ".join(conflicts)
            + "; XSanity T would see both DIVISION pools"
        )


def _split_cells(line: str, columns: int) -> list[str]:
    cells: list[str] = []
    index = 0
    while index < len(line):
        if line[index] == "{":
            end = line.find("}", index + 1)
            if end < 0:
                raise SscExportError(
                    f"generated SSC row has an unterminated cell token: {line!r}"
                )
            cells.append(line[index : end + 1])
            index = end + 1
        else:
            cells.append(line[index])
            index += 1
    if len(cells) != columns:
        raise SscExportError(
            f"generated SSC row has {len(cells)} cells but chart declares {columns}: {line!r}"
        )
    return cells


def _dense_rows(notes: str, columns: int) -> list[str]:
    blank = "0" * columns
    stripped = notes.rstrip("\n")
    if not stripped:
        return []

    result: list[str] = []
    for measure in stripped.split(",\n"):
        rows = measure.splitlines()
        if rows == [blank]:
            result.extend([blank] * LINES_PER_MEASURE)
            continue
        if len(rows) != LINES_PER_MEASURE:
            raise SscExportError(
                "generated SSC measure has "
                f"{len(rows)} rows; expected {LINES_PER_MEASURE} or one collapsed blank row"
            )
        result.extend(rows)
    return result


def _measure_rows(rows: list[str], columns: int) -> str:
    blank = "0" * columns
    if not rows:
        return blank + "\n"
    padded = list(rows)
    if len(padded) % LINES_PER_MEASURE:
        padded.extend([blank] * (LINES_PER_MEASURE - len(padded) % LINES_PER_MEASURE))

    parts: list[str] = []
    for start in range(0, len(padded), LINES_PER_MEASURE):
        measure = padded[start : start + LINES_PER_MEASURE]
        if all(row == blank for row in measure):
            parts.append(blank + "\n")
        else:
            parts.append("\n".join(measure) + "\n")
    return ",\n".join(parts)


def _control_cells(rows: list[str], columns: int, token: str) -> tuple[tuple[int, int], ...]:
    result: list[tuple[int, int]] = []
    for row_index, line in enumerate(rows):
        for lane, cell in enumerate(_split_cells(line, columns)):
            if cell == token:
                result.append((row_index, lane))
    return tuple(result)


def _without_controls(line: str, columns: int) -> str:
    cells = _split_cells(line, columns)
    changed = False
    for lane, cell in enumerate(cells):
        if cell in {_WRAP, _RETURN}:
            cells[lane] = "0"
            changed = True
    return "".join(cells) if changed else line


def _first_judged_row(rows: list[str], columns: int) -> int | None:
    for row_index, line in enumerate(rows):
        if any(cell not in {"0", _WRAP, _RETURN} for cell in _split_cells(line, columns)):
            return row_index
    return None


def _startup_wrap_row(rows: list[str], columns: int) -> tuple[int, int]:
    """Choose a StepSwap row before any judged source note.

    Prefer the earliest row so XSanity has the maximum possible startup time to
    settle on the selected DIVISION chart. We intentionally do not place T on
    the first judged row because same-row processing order is not established.
    """

    first = _first_judged_row(rows, columns)
    limit = len(rows) if first is None else first
    for row_index in range(limit):
        cells = _split_cells(rows[row_index], columns)
        for lane, cell in enumerate(cells):
            if cell == "0":
                return row_index, lane
    raise SscExportError(
        "load-time random chart has no empty SSC row before its first judged note; "
        "a startup StepSwap cannot be placed safely without adding a timing pre-roll"
    )


def _materialize_startup_random(
    report: SscRandomExportReport,
) -> tuple[SscLabeledChart, ...]:
    """Rebuild sparse helper windows as full charts and swap exactly once.

    ``compile_ssc_export`` keeps helpers sparse and brackets each active region
    with base T / helper O controls. Those controls are useful planning markers,
    but runtime testing proved that switching Steps after play has begun can
    invalidate notes already on screen and can sever active holds. Because NX
    0x8_ choices are made at chart load, the runtime form uses the markers only
    to reconstruct each helper, then discards them in favour of one pre-note T.
    """

    charts = list(report.charts)
    if report.helper_count <= 0 or len(charts) <= 1:
        return tuple(charts)

    columns = report.program.base_snapshot.columns
    base_rows = _dense_rows(charts[0].chart.notes, columns)
    wraps = _control_cells(base_rows, columns, _WRAP)
    if not wraps:
        raise SscExportError("compiled random base chart contains no Wrap planning markers")

    plain_base = [_without_controls(line, columns) for line in base_rows]
    startup_row, startup_lane = _startup_wrap_row(plain_base, columns)

    rebuilt_helpers: list[list[str]] = []
    for item in charts[1:]:
        sparse = _dense_rows(item.chart.notes, columns)
        returns = _control_cells(sparse, columns, _RETURN)
        if len(returns) != len(wraps):
            raise SscExportError(
                "compiled helper contains a different number of Wrap0 planning markers than "
                "the base Wrap count"
            )

        full = list(plain_base)
        blank = "0" * columns
        if len(full) < len(sparse):
            full.extend([blank] * (len(sparse) - len(full)))
        for (wrap_row, _), (return_row, _) in zip(wraps, returns):
            if return_row < wrap_row:
                raise SscExportError(
                    f"compiled random window returns at row {return_row} before Wrap row {wrap_row}"
                )
            if return_row >= len(sparse):
                raise SscExportError("compiled sparse helper ends before its Wrap0 marker")
            for row_index in range(wrap_row, return_row + 1):
                full[row_index] = _without_controls(sparse[row_index], columns)
        rebuilt_helpers.append(full)

    startup_cells = _split_cells(plain_base[startup_row], columns)
    if startup_cells[startup_lane] != "0":
        raise SscExportError("internal startup Wrap placement selected a non-empty lane")
    startup_cells[startup_lane] = _WRAP
    base_rows = list(plain_base)
    base_rows[startup_row] = "".join(startup_cells)
    charts[0] = replace(
        charts[0],
        chart=replace(charts[0].chart, notes=_measure_rows(base_rows, columns)),
    )

    for chart_index, rows in enumerate(rebuilt_helpers, 1):
        charts[chart_index] = replace(
            charts[chart_index],
            chart=replace(charts[chart_index].chart, notes=_measure_rows(rows, columns)),
        )
    return tuple(charts)


def _decorate_runtime_metadata(
    text: str,
    charts: tuple[SscLabeledChart, ...],
    *,
    random_mode: bool,
    chart_names: tuple[str, ...] | None = None,
) -> str:
    """Add chart identity, random gate, labels, and hold tick tags used by XSanity."""

    if chart_names is None:
        chart_names = tuple(_single_chart_name(item) for item in charts)
    if len(chart_names) != len(charts):
        raise SscExportError("runtime chart-name count does not match chart count")

    output: list[str] = []
    chart_index = -1
    awaiting_description = False
    random_gate_present = _RANDOM_SPECIAL_LINE in text.splitlines()
    random_gate_inserted = random_gate_present

    for raw_line in text.splitlines():
        line = _CORPUS_VERSION_LINE if raw_line == _PR_VERSION_LINE else raw_line
        output.append(line)

        if random_mode and not random_gate_inserted and line.startswith("#TITLE:"):
            output.append(_RANDOM_SPECIAL_LINE)
            random_gate_inserted = True

        if line == "#NOTEDATA:;":
            chart_index += 1
            if chart_index >= len(charts):
                raise SscExportError(
                    "rendered simfile contains more chart sections than the compiled report"
                )
            output.append(f"#CHARTNAME:{chart_names[chart_index]};")
            awaiting_description = True
            continue

        if awaiting_description and line.startswith("#DESCRIPTION:"):
            item = charts[chart_index]
            output.append(f"#LABELTYPE:{item.label_type};")
            output.append(f"#TICKCOUNTS:0.000000={LINE_BEAT_SPLIT};")
            awaiting_description = False

    if random_mode and not random_gate_inserted:
        raise SscExportError(
            "rendered simfile is missing #TITLE, so the XSanity random gate cannot be inserted"
        )
    if chart_index + 1 != len(charts):
        raise SscExportError(
            f"rendered simfile contains {chart_index + 1} chart sections but "
            f"{len(charts)} were expected"
        )
    if awaiting_description:
        raise SscExportError("rendered simfile chart section is missing #DESCRIPTION")
    return "\n".join(output) + "\n"


def render_compiled_simfile(report: SscRandomExportReport, song: SscSongInfo) -> str:
    """Render one report with a single pre-note StepSwap for load-time random."""

    charts = _materialize_startup_random(report)
    if not charts:
        raise SscExportError("a compiled simfile needs at least one chart")
    text = render_simfile([item.chart for item in charts], song)
    return _decorate_runtime_metadata(text, charts, random_mode=report.helper_count > 0)


def render_compiled_reports(
    reports: tuple[SscRandomExportReport, ...] | list[SscRandomExportReport],
    song: SscSongInfo,
) -> str:
    """Render several source charts from one song folder into one XSanity SSC."""

    frozen = tuple(reports)
    if not frozen:
        raise SscExportError("a combined simfile needs at least one source chart")
    _validate_combined_random_pools(frozen)

    runtime_groups = tuple(_materialize_startup_random(report) for report in frozen)
    charts = tuple(item for group in runtime_groups for item in group)
    if not charts:
        raise SscExportError("a combined simfile needs at least one chart section")
    text = render_simfile([item.chart for item in charts], song)
    return _decorate_runtime_metadata(
        text,
        charts,
        random_mode=any(report.helper_count > 0 for report in frozen),
        chart_names=_combined_chart_names(frozen),
    )


__all__ = ["render_compiled_simfile", "render_compiled_reports"]
