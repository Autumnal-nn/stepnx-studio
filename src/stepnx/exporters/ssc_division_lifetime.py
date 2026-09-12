"""Lifetime-aware XSanity Division allocation.

Random helper identity is only valuable while a generated ``T``/``O`` window is
live. Once the final random window has returned to the initial NORMAL chart, a
later native ``#DIVISION`` decision is independent of the random helper state.
The exporter should therefore avoid a global Cartesian product.

The important EF662-style shape is::

    NORMAL --T--> random helper ... --O0--> NORMAL ... #DIVISION

For a pool of N random helpers and a four-way terminal Division, the runtime
keeps exactly N random helpers. Every helper ends shortly after the final O0,
while the three alternate Division routes are small NORMAL route charts built
from the base suffix. Because generated T only samples ``LABELTYPE:DIVISION``,
those NORMAL routes do not contaminate the random pool. This mirrors the corpus
cases where T and native ``#DIVISION`` coexist while the named route Steps are
NORMAL charts addressed by ``#CHARTNAME``.

If the conditional decision overlaps a live random state, if there is no safe
blank corridor for the final O0, or if the shape is not yet proven, this module
falls back to the conservative Cartesian materializer in ``ssc_division``.
"""

from __future__ import annotations

from dataclasses import replace

from stepnx.exporters.ssc import SscExportError
from stepnx.exporters.ssc_division import (
    SscDivisionDecision,
    SscDivisionRuntime,
    _route_variant,
    _split_bounds,
    _table,
    compile_division_decisions,
    materialize_division_routes,
)
from stepnx.exporters.ssc_random import SscLabeledChart, SscRandomExportReport
from stepnx.exporters.ssc_xsanity import (
    _control_cells,
    _dense_rows,
    _measure_rows,
    _split_cells,
)

_RETURN = "O"
_WRAP = "T"
_HOLD_HEAD_KINDS = frozenset({"2", "4"})
_HOLD_TAIL_KIND = "3"

# Keep two SSC beats after the final O0 and two beats before a late Division
# route becomes relevant. On the writer's 8-row beat grid this is 16 rows.
_RETURN_TAIL_ROWS = 16
_DIVISION_LEAD_ROWS = 16


def _cell_kind(cell: str) -> str:
    if not cell:
        return ""
    if cell.startswith("{"):
        return cell[1:2]
    return cell[0]


def _safe_blank_mask(rows: list[str], columns: int, length: int) -> tuple[bool, ...]:
    """Rows where a Steps swap sees no note and no active sustain."""

    blank = "0" * columns
    active = [False] * columns
    safe: list[bool] = []
    for row_index in range(length):
        line = rows[row_index] if row_index < len(rows) else blank
        cells = _split_cells(line, columns)
        active_before = any(active)
        touches_hold = False
        for lane, cell in enumerate(cells):
            kind = _cell_kind(cell)
            if kind in _HOLD_HEAD_KINDS:
                touches_hold = True
                active[lane] = True
            elif kind == _HOLD_TAIL_KIND:
                touches_hold = True
                active[lane] = False
        safe.append(
            not active_before
            and not any(active)
            and not touches_hold
            and all(cell == "0" for cell in cells)
        )
    return tuple(safe)


def _combined_safe_mask(
    charts: tuple[SscLabeledChart, ...],
    columns: int,
) -> tuple[bool, ...]:
    rows = tuple(_dense_rows(item.chart.notes, columns) for item in charts)
    length = max((len(item) for item in rows), default=0)
    masks = tuple(_safe_blank_mask(item, columns, length) for item in rows)
    return tuple(all(mask[index] for mask in masks) for index in range(length))


def _runs(mask: tuple[bool, ...], start: int, end: int) -> tuple[tuple[int, int], ...]:
    start = max(0, start)
    end = min(len(mask) - 1, end)
    if end < start:
        return ()
    result: list[tuple[int, int]] = []
    cursor = start
    while cursor <= end:
        if not mask[cursor]:
            cursor += 1
            continue
        run_start = cursor
        while cursor + 1 <= end and mask[cursor + 1]:
            cursor += 1
        result.append((run_start, cursor))
        cursor += 1
    return tuple(result)


def _planning_last_return(report: SscRandomExportReport) -> int | None:
    """Last semantic Wrap0 marker emitted by the random compiler."""

    if report.helper_count <= 0 or len(report.charts) <= 1:
        return None
    columns = report.program.base_snapshot.columns
    last_rows: list[int] = []
    expected: int | None = None
    for item in report.charts[1:]:
        controls = _control_cells(_dense_rows(item.chart.notes, columns), columns, _RETURN)
        if not controls:
            return None
        if expected is None:
            expected = len(controls)
        elif len(controls) != expected:
            raise SscExportError(
                "compiled random helpers disagree on the number of Wrap0 planning markers"
            )
        last_rows.append(controls[-1][0])
    return max(last_rows) if last_rows else None


def _runtime_last_wrap(runtime: tuple[SscLabeledChart, ...], columns: int) -> int | None:
    if not runtime:
        return None
    wraps = _control_cells(_dense_rows(runtime[0].chart.notes, columns), columns, _WRAP)
    return wraps[-1][0] if wraps else None


def _first_decision_row(
    report: SscRandomExportReport,
    decisions: tuple[SscDivisionDecision, ...],
) -> int:
    bounds = _split_bounds(report.program.base_snapshot)
    return min(bounds[decision.split_index][0] for decision in decisions)


def _find_final_return_row(
    report: SscRandomExportReport,
    runtime: tuple[SscLabeledChart, ...],
    decisions: tuple[SscDivisionDecision, ...],
) -> int | None:
    """Find a safe final O0 after random state dies and before tail Division."""

    planning_return = _planning_last_return(report)
    if planning_return is None:
        return None
    columns = report.program.base_snapshot.columns
    last_wrap = _runtime_last_wrap(runtime, columns)
    if last_wrap is not None and planning_return <= last_wrap:
        return None

    first_division = _first_decision_row(report, decisions)
    latest = first_division - _RETURN_TAIL_ROWS - 1
    if latest < planning_return:
        return None

    safe = _combined_safe_mask(runtime, columns)
    for run_start, run_end in _runs(safe, planning_return, latest + _RETURN_TAIL_ROWS):
        candidate = max(run_start, planning_return)
        if candidate > latest:
            continue
        if run_end - candidate >= _RETURN_TAIL_ROWS:
            return candidate
    return None


def _put_return(rows: list[str], columns: int, row_index: int) -> None:
    if not (0 <= row_index < len(rows)):
        raise SscExportError(f"final Wrap0 row {row_index} is outside the helper chart")
    cells = _split_cells(rows[row_index], columns)
    lane = next((index for index, cell in enumerate(cells) if cell == "0"), None)
    if lane is None:
        raise SscExportError(f"final Wrap0 has no empty lane at row {row_index}")
    cells[lane] = _RETURN
    rows[row_index] = "".join(cells)


def _trim_random_helper(
    item: SscLabeledChart,
    *,
    columns: int,
    return_row: int,
) -> SscLabeledChart:
    """End a dead random helper shortly after its final O0."""

    rows = _dense_rows(item.chart.notes, columns)
    _put_return(rows, columns, return_row)
    end = min(len(rows), return_row + _RETURN_TAIL_ROWS + 1)
    return replace(item, chart=replace(item.chart, notes=_measure_rows(rows[:end], columns)))


def _sparse_tail_route(
    item: SscLabeledChart,
    *,
    columns: int,
    suffix_start: int,
) -> SscLabeledChart:
    """Drop route payload before the late Division lead window."""

    rows = _dense_rows(item.chart.notes, columns)
    blank = "0" * columns
    for row_index in range(min(len(rows), max(0, suffix_start))):
        rows[row_index] = blank
    return replace(item, chart=replace(item.chart, notes=_measure_rows(rows, columns)))


def _tail_separated_runtime(
    report: SscRandomExportReport,
    runtime: tuple[SscLabeledChart, ...],
    decisions: tuple[SscDivisionDecision, ...],
    *,
    prefix: str,
) -> SscDivisionRuntime | None:
    """Separate one terminal Division from an already-dead random pool."""

    # More than one independent conditional decision needs a second liveness
    # analysis of conditional route state. Avoid silently correlating them by a
    # single route index until that graph exists.
    if report.helper_count <= 0 or len(decisions) != 1:
        return None
    if len(runtime) != report.helper_count + 1:
        return None

    decision = decisions[0]
    route_count = decision.route_count
    if route_count <= 1:
        return None

    return_row = _find_final_return_row(report, runtime, decisions)
    if return_row is None:
        return None

    bounds = _split_bounds(report.program.base_snapshot)
    division_start, _ = bounds[decision.split_index]
    suffix_start = max(0, division_start - _DIVISION_LEAD_ROWS)
    columns = report.program.base_snapshot.columns

    base = runtime[0]
    charts: list[SscLabeledChart] = [base]
    names: list[str] = [prefix + "_BASE"]
    tables: list[tuple[str, ...]] = [()]

    # Preserve exactly the original random pool. Every helper receives the final
    # O0 and then physically ends after a short guard instead of duplicating the
    # rest of the song hundreds of times.
    for item in runtime[1:]:
        helper_index = item.helper_index
        assert helper_index is not None
        charts.append(
            _trim_random_helper(
                item,
                columns=columns,
                return_row=return_row,
            )
        )
        names.append(prefix + f"_RANDOM_{helper_index + 1:03d}")
        tables.append(())

    # The conditional routes are addressed directly by CHARTNAME and are NORMAL
    # charts, so generated T cannot sample them as random tickets.
    route_names = [names[0]]
    for route_index in range(1, route_count):
        route_name = prefix + f"_DIVISION_{route_index + 1:02d}"
        routed = _route_variant(
            base,
            report.program.base_snapshot,
            decisions,
            route_index,
            description=f"{base.chart.description} [StepNX Division {route_index + 1}]",
            helper_index=None,
        )
        routed = replace(routed, label_type="NORMAL", helper_index=None)
        routed = _sparse_tail_route(
            routed,
            columns=columns,
            suffix_start=suffix_start,
        )
        charts.append(routed)
        names.append(route_name)
        tables.append(())
        route_names.append(route_name)

    tables[0] = _table(decisions, tuple(route_names))
    return SscDivisionRuntime(
        charts=tuple(charts),
        chart_names=tuple(names),
        division_tables=tuple(tables),
        route_count=route_count,
    )


def materialize_division_routes_lifetime_aware(
    report: SscRandomExportReport,
    runtime_charts: tuple[SscLabeledChart, ...],
    *,
    prefix: str = "STEPNX",
) -> SscDivisionRuntime:
    """Choose the smallest proven route allocation for the report's lifetimes.

    Today the optimizer recognizes the EF662 shape: one conditional decision
    strictly after the final random state can safely return to NORMAL. Other
    shapes retain the conservative existing materializer.
    """

    decisions = compile_division_decisions(report)
    if decisions:
        optimized = _tail_separated_runtime(
            report,
            runtime_charts,
            decisions,
            prefix=prefix,
        )
        if optimized is not None:
            return optimized
    return materialize_division_routes(report, runtime_charts, prefix=prefix)


__all__ = ["materialize_division_routes_lifetime_aware"]
