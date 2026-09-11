"""Runtime-facing rendering for semantic XSanity SSC exports.

The semantic compiler in :mod:`stepnx.exporters.ssc_random` owns helper-window
planning, two-visual-beat Wrap lead, and sparse helper note payloads. This module
applies the standalone XSanity metadata envelope and can combine several NX
charts from one song folder into one SSC.

Current evidence-driven rules:

* random helper pools require song-level ``#SPECIAL:LEVEL,RANDOM;``;
* generated ``LABELTYPE:DIVISION`` Steps receive a non-empty unique
  ``#CHARTNAME``;
* ``#TICKCOUNTS`` follows the writer's virtual row grid. The current projection
  maps one NX row to one SSC row and defines one SSC beat as
  ``LINE_BEAT_SPLIT`` rows, so the same tick count preserves one hold tick per
  source NX row after BPM rescaling;
* XSanity Wrap selects from the DIVISION pool of the same StepsType. Until a
  narrower runtime filter is proven, one combined SSC may therefore contain at
  most one random source chart for each StepsType. Non-random charts of that
  StepsType are safe because they remain LABELTYPE:NORMAL;
* changing Steps while a long note is already active severs that sustain in
  runtime. If the semantic compiler's visually-safe T row lands inside a hold
  or roll, the runtime layer moves T backward to the latest hold-safe row and
  restores the newly exposed common prefix in every sparse helper.
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
_HOLD_HEAD_KINDS = frozenset({"2", "4"})
_HOLD_TAIL_KIND = "3"


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


def _cell_kind(cell: str) -> str:
    if not cell:
        return ""
    if cell.startswith("{"):
        return cell[1:2]
    return cell[0]


def _hold_unsafe_rows(rows: list[str], columns: int) -> tuple[bool, ...]:
    """Mark every row that starts, ends, or lies inside an SSC hold/roll.

    T/O are Step switches rather than ordinary judged notes. Runtime testing
    shows that a switch while a sustain is already active drops that sustain,
    so seam rows must not bisect a long note. Head and tail rows are also kept
    unsafe because their processing order relative to a StepSwap is not proven.
    """

    active: list[bool] = [False] * columns
    unsafe: list[bool] = []
    for line in rows:
        cells = _split_cells(line, columns)
        row_unsafe = any(active)
        for lane, cell in enumerate(cells):
            kind = _cell_kind(cell)
            if kind in _HOLD_HEAD_KINDS:
                row_unsafe = True
                active[lane] = True
            elif kind == _HOLD_TAIL_KIND:
                row_unsafe = True
                active[lane] = False
        if any(active):
            row_unsafe = True
        unsafe.append(row_unsafe)
    return tuple(unsafe)


def _control_cells(rows: list[str], columns: int, token: str) -> tuple[tuple[int, int], ...]:
    result: list[tuple[int, int]] = []
    for row_index, line in enumerate(rows):
        for lane, cell in enumerate(_split_cells(line, columns)):
            if cell == token:
                result.append((row_index, lane))
    return tuple(result)


def _without_control(line: str, columns: int, token: str) -> str:
    cells = _split_cells(line, columns)
    changed = False
    for lane, cell in enumerate(cells):
        if cell == token:
            cells[lane] = "0"
            changed = True
    return "".join(cells) if changed else line


def _retime_wraps_around_active_holds(
    report: SscRandomExportReport,
) -> tuple[SscLabeledChart, ...]:
    """Move T before any sustain it would otherwise cut in XSanity runtime.

    The semantic layer deliberately places T as late as possible while keeping
    two visual beats before the first divergent row. That can still land in the
    middle of a deterministic long note immediately before the random window.
    XSanity drops that already-active sustain when it swaps Steps.

    Moving T backward is semantically safe because it only increases random
    lookahead. Sparse helpers need one matching repair: rows newly exposed by
    the earlier swap are copied from the NORMAL chart, where they are still in
    the common pre-random prefix.
    """

    charts = list(report.charts)
    if report.helper_count <= 0 or len(charts) <= 1:
        return tuple(charts)

    columns = report.program.base_snapshot.columns
    base_rows = _dense_rows(charts[0].chart.notes, columns)
    wraps = _control_cells(base_rows, columns, _WRAP)
    if not wraps:
        return tuple(charts)

    helper_rows = [_dense_rows(item.chart.notes, columns) for item in charts[1:]]
    helper_returns = [
        _control_cells(rows, columns, _RETURN) for rows in helper_rows
    ]
    for controls in helper_returns:
        if len(controls) != len(wraps):
            raise SscExportError(
                "compiled helper contains a different number of Wrap0 controls than the base Wrap count"
            )

    plain_base = [_without_control(line, columns, _WRAP) for line in base_rows]
    unsafe = _hold_unsafe_rows(plain_base, columns)
    moved: list[tuple[int, int]] = []

    for ordinal, (old_row, old_lane) in enumerate(wraps):
        if old_row >= len(unsafe) or not unsafe[old_row]:
            continue

        earliest = 0
        if ordinal:
            earliest = max(controls[ordinal - 1][0] for controls in helper_returns) + 1

        new_row = None
        new_lane = None
        for candidate in range(old_row - 1, earliest - 1, -1):
            if candidate < len(unsafe) and unsafe[candidate]:
                continue
            cells = _split_cells(plain_base[candidate], columns)
            lane = next((index for index, cell in enumerate(cells) if cell == "0"), None)
            if lane is None:
                continue
            new_row = candidate
            new_lane = lane
            break

        if new_row is None or new_lane is None:
            raise SscExportError(
                f"Wrap {ordinal + 1} falls inside an active long note and cannot be moved "
                "to a hold-safe row without crossing the previous random window"
            )

        old_cells = _split_cells(base_rows[old_row], columns)
        old_cells[old_lane] = "0"
        base_rows[old_row] = "".join(old_cells)
        new_cells = _split_cells(base_rows[new_row], columns)
        if new_cells[new_lane] != "0":
            raise SscExportError("internal Wrap retiming selected a non-empty lane")
        new_cells[new_lane] = _WRAP
        base_rows[new_row] = "".join(new_cells)

        for rows in helper_rows:
            blank = "0" * columns
            if old_row >= len(rows):
                rows.extend([blank] * (old_row + 1 - len(rows)))
            for row_index in range(new_row, old_row + 1):
                rows[row_index] = plain_base[row_index]
        moved.append((old_row, new_row))

    if not moved:
        return tuple(charts)

    charts[0] = replace(
        charts[0],
        chart=replace(charts[0].chart, notes=_measure_rows(base_rows, columns)),
    )
    for index, rows in enumerate(helper_rows, 1):
        charts[index] = replace(
            charts[index],
            chart=replace(charts[index].chart, notes=_measure_rows(rows, columns)),
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
    """Render a standalone runtime-oriented XSanity SSC from one compiled report."""

    charts = _retime_wraps_around_active_holds(report)
    if not charts:
        raise SscExportError("a compiled simfile needs at least one chart")
    text = render_simfile([item.chart for item in charts], song)
    return _decorate_runtime_metadata(text, charts, random_mode=report.helper_count > 0)


def render_compiled_reports(
    reports: tuple[SscRandomExportReport, ...] | list[SscRandomExportReport],
    song: SscSongInfo,
) -> str:
    """Render several source charts from one song folder into one XSanity SSC.

    Random reports are intentionally limited to one per StepsType because T is
    known to select from the global DIVISION pool of that StepsType. This guard
    can be relaxed only after runtime evidence proves a narrower filter.
    """

    frozen = tuple(reports)
    if not frozen:
        raise SscExportError("a combined simfile needs at least one source chart")
    _validate_combined_random_pools(frozen)

    runtime_groups = tuple(_retime_wraps_around_active_holds(report) for report in frozen)
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
