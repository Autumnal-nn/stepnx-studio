"""Lifetime-aware XSanity Division allocation.

Random helper identity is only valuable while a generated ``T``/``O`` window is
live.  Once the final random window has returned to the initial NORMAL chart,
those helper Steps are dead state.  A later native ``#DIVISION`` decision can
therefore reuse a few of the existing helper chart identities as its alternate
routes instead of multiplying every random ticket by every conditional route.

The important case is EF662-style structure::

    NORMAL --T--> random helper ... --O0--> NORMAL ... #DIVISION

For a pool of N random helpers and a four-way terminal Division, the runtime
still contains N helpers, not N*4.  Three helpers keep their original random
prefix and are recycled as W/G/WG route carriers after the final O0.  All other
helpers are truncated shortly after O0.  The route carriers keep only a sparse
late suffix around the Division decision, so the optimization also removes the
otherwise duplicated full-song payload.

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

# The runtime test that validated Wrap0 used visible breathing room around the
# swap.  Keep two SSC beats after the final O0 and two beats before a reused
# route's first conditional region.  On the writer's 8-row beat grid this is 16
# rows each side.
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
        # A later runtime draw still exists.  The state is not globally dead at
        # this semantic return, so helper reuse would alias two live purposes.
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


def _with_final_return(
    item: SscLabeledChart,
    *,
    columns: int,
    row_index: int,
) -> SscLabeledChart:
    rows = _dense_rows(item.chart.notes, columns)
    _put_return(rows, columns, row_index)
    return replace(item, chart=replace(item.chart, notes=_measure_rows(rows, columns)))


def _sparsify_after_return(
    item: SscLabeledChart,
    *,
    columns: int,
    return_row: int,
    suffix_start: int | None = None,
) -> SscLabeledChart:
    """Keep random prefix, optional Division suffix, and blank the dead middle."""

    rows = _dense_rows(item.chart.notes, columns)
    blank = "0" * columns
    prefix_end = min(len(rows), return_row + _RETURN_TAIL_ROWS + 1)
    if suffix_start is None:
        rows = rows[:prefix_end]
    else:
        suffix_start = max(prefix_end, min(len(rows), suffix_start))
        for row_index in range(prefix_end, suffix_start):
            rows[row_index] = blank
    return replace(item, chart=replace(item.chart, notes=_measure_rows(rows, columns)))


def _tail_reuse_runtime(
    report: SscRandomExportReport,
    runtime: tuple[SscLabeledChart, ...],
    decisions: tuple[SscDivisionDecision, ...],
    *,
    prefix: str,
) -> SscDivisionRuntime | None:
    """Reuse dead random helpers for one terminal conditional decision."""

    # Multiple independent conditional decisions need their own liveness graph;
    # correlating them by one route index would be another hidden Cartesian
    # product.  Keep the optimization intentionally narrow until that graph is
    # implemented.
    if report.helper_count <= 0 or len(decisions) != 1:
        return None
    if len(runtime) != report.helper_count + 1:
        return None

    decision = decisions[0]
    route_count = decision.route_count
    alternates = route_count - 1
    if alternates <= 0 or alternates > report.helper_count:
        return None

    return_row = _find_final_return_row(report, runtime, decisions)
    if return_row is None:
        return None

    bounds = _split_bounds(report.program.base_snapshot)
    division_start, _ = bounds[decision.split_index]
    suffix_start = max(return_row + _RETURN_TAIL_ROWS + 1, division_start - _DIVISION_LEAD_ROWS)
    columns = report.program.base_snapshot.columns

    names = [prefix + "_BASE"]
    for item in runtime[1:]:
        assert item.helper_index is not None
        names.append(prefix + f"_RANDOM_{item.helper_index + 1:03d}")

    # Block 0 stays on the initial chart. Alternate block routes borrow existing
    # random helper identities. They remain valid random tickets before O0, then
    # become sparse late route carriers after their random state has died.
    route_names = tuple([names[0], *names[1 : 1 + alternates]])
    common_table = _table(decisions, route_names)

    charts: list[SscLabeledChart] = [runtime[0]]
    tables: list[tuple[str, ...]] = [common_table]
    for helper_position, source in enumerate(runtime[1:], 1):
        returned = _with_final_return(source, columns=columns, row_index=return_row)
        route_index = helper_position if helper_position <= alternates else 0
        if route_index:
            helper_index = source.helper_index
            assert helper_index is not None
            routed = _route_variant(
                returned,
                report.program.helper_snapshots[helper_index],
                decisions,
                route_index,
                description=(
                    f"{runtime[0].chart.description} [StepNX random {helper_index + 1} "
                    f"+ tail Division {route_index + 1}]"
                ),
                helper_index=helper_index,
            )
            charts.append(
                _sparsify_after_return(
                    routed,
                    columns=columns,
                    return_row=return_row,
                    suffix_start=suffix_start,
                )
            )
            # This is a terminal one-decision route, so only the base chart is
            # active when the table is evaluated. Keeping the carrier table
            # empty avoids redundant metadata on hundreds of random helpers.
            tables.append(())
        else:
            charts.append(
                _sparsify_after_return(
                    returned,
                    columns=columns,
                    return_row=return_row,
                )
            )
            tables.append(())

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

    Today the optimizer recognizes the high-value EF662 shape: one conditional
    decision strictly after the final random state can safely return to NORMAL.
    Other shapes retain the conservative existing materializer.
    """

    decisions = compile_division_decisions(report)
    if decisions:
        optimized = _tail_reuse_runtime(
            report,
            runtime_charts,
            decisions,
            prefix=prefix,
        )
        if optimized is not None:
            return optimized
    return materialize_division_routes(report, runtime_charts, prefix=prefix)


__all__ = [
    "materialize_division_routes_lifetime_aware",
]
