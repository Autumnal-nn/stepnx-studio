"""Runtime-facing rendering for semantic XSanity SSC exports.

The random compiler in :mod:`stepnx.exporters.ssc_random` builds chart state and
control cells. This module owns the standalone XSanity envelope and the small
runtime-specific adaptations that make those generated Steps behave like the
working Sanity corpus.

The current rules are evidence-driven:

* random helper pools require the song-level ``#SPECIAL:LEVEL,RANDOM;`` gate.
  A 20-way runtime probe stayed on the base/first route without it; adding only
  that tag immediately produced different helper outcomes;
* generated ``LABELTYPE:DIVISION`` Steps receive a non-empty, unique
  ``#CHARTNAME`` to match the corpus shape. The chart-name requirement has not
  been isolated independently from the song-level random gate;
* ``#TICKCOUNTS`` follows the writer's virtual row grid. The current mechanical
  projection maps one NX row to one SSC row and defines one SSC beat as
  ``LINE_BEAT_SPLIT`` rows, so using the same value as the tick count preserves
  one hold tick per source NX row even when BPM is rescaled;
* Wrap is scheduled with at least two *visual* beats of lookahead. Runtime
  testing showed that one musical beat can still switch a branch after its
  arrows are already visible. Visual distance is accumulated from the source
  NX scroll magnitude, so a zero-scroll section contributes no lookahead and
  forces T farther back, while faster scrolling needs fewer source rows.

This does not make ``LINE_BEAT_SPLIT == 8`` a property of SSC. It is merely the
coordinate system of the current writer. A later rational/adaptive timeline
compiler can replace the grid, tick-count projection, and runtime lookahead
rules together.
"""

from __future__ import annotations

from dataclasses import replace
from math import ceil

from stepnx.exporters.ssc import (
    LINES_PER_MEASURE,
    LINE_BEAT_SPLIT,
    SscChart,
    SscExportError,
    SscSongInfo,
    render_simfile,
)
from stepnx.exporters.ssc_random import SscLabeledChart, SscRandomExportReport

_CORPUS_VERSION_LINE = "#VERSION:0.83;"
_PR_VERSION_LINE = "#VERSION:0.83 xSanity;"
_RANDOM_SPECIAL_LINE = "#SPECIAL:LEVEL,RANDOM;"
_WRAP = "T"
_MIN_VISUAL_LOOKAHEAD_BEATS = 2.0


def _chart_name(item: SscLabeledChart) -> str:
    if item.helper_index is None:
        return "STEPNX_BASE"
    return f"STEPNX_RANDOM_{item.helper_index + 1:03d}"


def _split_bounds(report: SscRandomExportReport) -> dict[int, tuple[int, int]]:
    snapshot = report.program.base_snapshot
    row = 0
    bounds: dict[int, tuple[int, int]] = {}
    for split_index, split in enumerate(snapshot.splits):
        if not split.blocks:
            continue
        block = snapshot.active_block(split.stable_id)
        start = row
        row += block.row_count
        bounds[split_index] = (start, row)
    return bounds


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
    if len(rows) % LINES_PER_MEASURE:
        rows = list(rows) + [blank] * (LINES_PER_MEASURE - len(rows) % LINES_PER_MEASURE)

    parts: list[str] = []
    for start in range(0, len(rows), LINES_PER_MEASURE):
        measure = rows[start : start + LINES_PER_MEASURE]
        if all(row == blank for row in measure):
            parts.append(blank + "\n")
        else:
            parts.append("\n".join(measure) + "\n")
    return ",\n".join(parts)


def _wrap_cells(rows: list[str], columns: int) -> list[tuple[int, int]]:
    controls: list[tuple[int, int]] = []
    for row_index, line in enumerate(rows):
        for lane, cell in enumerate(_split_cells(line, columns)):
            if cell == _WRAP:
                controls.append((row_index, lane))
    return controls


def _random_return_splits(report: SscRandomExportReport) -> tuple[int, ...]:
    analysis = report.program.analysis
    episodes = {episode.store_split_index: episode for episode in analysis.bank_episodes}
    result: list[int] = []
    for split_index in analysis.random_split_indices:
        selector = analysis.selectors[split_index]
        if selector.stores_bank:
            result.append(episodes[split_index].last_use_split_index)
        else:
            result.append(split_index)
    return tuple(result)


def _visual_lookahead_row(
    report: SscRandomExportReport,
    random_split_index: int,
    *,
    minimum_visual_beats: float = _MIN_VISUAL_LOOKAHEAD_BEATS,
) -> int:
    """Return the latest row that leaves enough visual travel before a random split.

    The writer maps one NX row to 1/8 SSC beat and projects
    ``SSC_SCROLL = NX_SCROLL * 8``. Therefore one source row contributes
    ``abs(NX_SCROLL)`` normal-scroll beats of visual distance. Zero scroll
    contributes no distance and is crossed completely while walking backward.
    """

    if minimum_visual_beats <= 0.0:
        raise ValueError("minimum visual lookahead must be greater than zero")

    snapshot = report.program.base_snapshot
    bounds = _split_bounds(report)
    target_row = bounds[random_split_index][0]
    remaining = float(minimum_visual_beats)
    cursor = target_row

    for split_index in reversed(tuple(bounds)):
        start, end = bounds[split_index]
        segment_end = min(end, cursor)
        if segment_end <= start:
            continue

        split = snapshot.splits[split_index]
        block = snapshot.active_block(split.stable_id)
        visual_per_row = abs(float(block.scroll))
        available_rows = segment_end - start

        if visual_per_row > 0.0:
            needed_rows = max(1, ceil((remaining - 1e-12) / visual_per_row))
            if needed_rows <= available_rows:
                return segment_end - needed_rows
            remaining -= available_rows * visual_per_row

        cursor = start

    raise SscExportError(
        f"random split {random_split_index} has less than "
        f"{minimum_visual_beats:g} visual beats available before it for a runtime-safe Wrap"
    )


def _inject_wrap(
    rows: list[str],
    columns: int,
    latest: int,
    earliest: int,
) -> int:
    for row_index in range(latest, earliest - 1, -1):
        if row_index < 0:
            continue
        cells = _split_cells(rows[row_index], columns)
        for lane, cell in enumerate(cells):
            if cell != "0":
                continue
            cells[lane] = _WRAP
            rows[row_index] = "".join(cells)
            return row_index
    raise SscExportError(
        "no empty lane is available for a runtime-safe Wrap with the required visual lookahead"
    )


def _retime_wraps_for_visual_lookahead(
    report: SscRandomExportReport,
    chart: SscChart,
) -> SscChart:
    """Move each T early enough to provide at least two visual beats of lead."""

    analysis = report.program.analysis
    random_splits = tuple(analysis.random_split_indices)
    if not random_splits:
        return chart

    snapshot = report.program.base_snapshot
    columns = snapshot.columns
    rows = _dense_rows(chart.notes, columns)
    controls = _wrap_cells(rows, columns)
    if len(controls) != len(random_splits):
        raise SscExportError(
            f"compiled base chart contains {len(controls)} Wrap controls for "
            f"{len(random_splits)} random decisions"
        )

    bounds = _split_bounds(report)
    return_splits = _random_return_splits(report)
    previous_return_end = 0
    changed = False

    for ordinal, (random_split_index, control) in enumerate(zip(random_splits, controls)):
        old_row, old_lane = control
        latest = _visual_lookahead_row(report, random_split_index)
        if latest < previous_return_end:
            raise SscExportError(
                f"random split {random_split_index} cannot keep "
                f"{_MIN_VISUAL_LOOKAHEAD_BEATS:g} visual beats of Wrap lookahead without "
                "overlapping the previous random region; dense random clusters require "
                "trajectory/joint-state compilation"
            )

        if old_row > latest:
            old_cells = _split_cells(rows[old_row], columns)
            old_cells[old_lane] = "0"
            rows[old_row] = "".join(old_cells)
            _inject_wrap(rows, columns, latest, previous_return_end)
            changed = True

        previous_return_end = bounds[return_splits[ordinal]][1]

    if not changed:
        return chart
    return replace(chart, notes=_measure_rows(rows, columns))


def _runtime_charts(report: SscRandomExportReport) -> tuple[SscLabeledChart, ...]:
    charts = list(report.charts)
    if report.helper_count and charts:
        base = charts[0]
        runtime_chart = _retime_wraps_for_visual_lookahead(report, base.chart)
        if runtime_chart is not base.chart:
            charts[0] = replace(base, chart=runtime_chart)
    return tuple(charts)


def _decorate_runtime_metadata(
    text: str,
    charts: tuple[SscLabeledChart, ...],
    *,
    random_mode: bool,
) -> str:
    """Add the chart identity, random gate, labels, and tick tags used by XSanity."""

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
            output.append(f"#CHARTNAME:{_chart_name(charts[chart_index])};")
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
    """Render a standalone, runtime-oriented XSanity SSC from a compiled report."""

    charts = _runtime_charts(report)
    if not charts:
        raise SscExportError("a compiled simfile needs at least one chart")
    text = render_simfile([item.chart for item in charts], song)
    return _decorate_runtime_metadata(text, charts, random_mode=report.helper_count > 0)


__all__ = ["render_compiled_simfile"]
