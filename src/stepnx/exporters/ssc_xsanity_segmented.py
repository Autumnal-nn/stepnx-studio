"""Experimental XSanity runtime projection with safe Wrap0 handoffs.

NX load-time random choices may be compressed into a reusable helper pool. A
single startup Wrap is runtime-safe but correlates every random decision in the
song to one helper index. For charts without conditional routes this projection
can reuse the semantic compiler's random windows to introduce a small number of
fresh draws:

    NORMAL --T--> DIVISION --O0--> NORMAL --T--> DIVISION

Both Wrap and Wrap0 perform StepSwap operations in XSanity, and runtime testing
has shown that swapping near visible taps or an active hold can drop notes. A
candidate corridor must therefore be blank and hold-free in the NORMAL chart
and in every materialized helper, with a quiet guard after each control.

Conditional NX branches are compiled after this stage into full backing routes
with native XSanity #DIVISION metadata. When such routes exist, the selected
random helper is deliberately kept active for the whole chart. This gives the
Division compiler a stable helper identity to move among sibling routes and
avoids trying to map O0/T rows across branch-specific BeatSplit/row geometry.
"""

from __future__ import annotations

from dataclasses import replace

from stepnx.exporters.ssc import SscExportError, SscSongInfo, render_simfile
from stepnx.exporters.ssc_division import (
    inject_division_tables,
    materialize_division_routes,
)
from stepnx.exporters.ssc_random import SscLabeledChart, SscRandomExportReport
from stepnx.exporters.ssc_xsanity import (
    _control_cells,
    _decorate_runtime_metadata,
    _dense_rows,
    _materialize_startup_random,
    _measure_rows,
    _split_cells,
    _validate_combined_random_pools,
)

_WRAP = "T"
_RETURN = "O"  # bare O is Wrap0: return to the initial/base Steps
_HOLD_HEAD_KINDS = frozenset({"2", "4"})
_HOLD_TAIL_KIND = "3"

# Runtime-tested guard. O0 gets eight completely empty rows before the next T;
# the new T then gets sixteen completely empty rows before any chart content.
# With the writer's eight-row beat grid, the latter is two SSC beats of dead air.
_EMPTY_ROWS_AFTER_RETURN = 8
_EMPTY_ROWS_AFTER_WRAP = 16
_MIN_CORRIDOR_ROWS = 1 + _EMPTY_ROWS_AFTER_RETURN + 1 + _EMPTY_ROWS_AFTER_WRAP


def _cell_kind(cell: str) -> str:
    if not cell:
        return ""
    if cell.startswith("{"):
        return cell[1:2]
    return cell[0]


def _safe_blank_mask(rows: list[str], columns: int, length: int) -> tuple[bool, ...]:
    """Return rows where a StepSwap sees neither notes nor an active sustain."""

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


def _combined_safe_blank_mask(
    chart_rows: tuple[list[str], ...],
    columns: int,
) -> tuple[bool, ...]:
    length = max((len(rows) for rows in chart_rows), default=0)
    masks = tuple(_safe_blank_mask(rows, columns, length) for rows in chart_rows)
    return tuple(all(mask[row] for mask in masks) for row in range(length))


def _runs(mask: tuple[bool, ...], start: int, end: int) -> tuple[tuple[int, int], ...]:
    """Return inclusive safe runs intersecting ``[start, end]``."""

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


def _find_handoff_corridor(
    safe: tuple[bool, ...],
    *,
    after_row: int,
    latest_wrap_row: int,
) -> tuple[int, int] | None:
    """Choose O0/T inside the best dead-air run before the next random window."""

    search_start = after_row + 1
    search_end = min(len(safe) - 1, latest_wrap_row + _EMPTY_ROWS_AFTER_WRAP)
    candidates: list[tuple[int, int, int]] = []
    for run_start, run_end in _runs(safe, search_start, search_end):
        if run_end - run_start + 1 < _MIN_CORRIDOR_ROWS:
            continue
        latest_t = min(latest_wrap_row, run_end - _EMPTY_ROWS_AFTER_WRAP)
        earliest_t = run_start + 1 + _EMPTY_ROWS_AFTER_RETURN
        if latest_t < earliest_t:
            continue
        candidates.append((run_end - run_start + 1, run_start, latest_t))

    if not candidates:
        return None
    _, return_row, wrap_row = max(candidates, key=lambda item: (item[0], item[2]))
    return return_row, wrap_row


def _put_control(rows: list[str], columns: int, row_index: int, token: str) -> None:
    if not (0 <= row_index < len(rows)):
        raise SscExportError(f"runtime control row {row_index} is outside the materialized chart")
    cells = _split_cells(rows[row_index], columns)
    lane = next((index for index, cell in enumerate(cells) if cell == "0"), None)
    if lane is None:
        raise SscExportError(f"runtime control {token} has no empty lane at row {row_index}")
    cells[lane] = token
    rows[row_index] = "".join(cells)


def _conditional_row_bounds(report: SscRandomExportReport) -> tuple[tuple[int, int], ...]:
    """Locate non-random multi-block regions without validating their condition grammar."""

    program = getattr(report, "program", None)
    snapshot = getattr(program, "base_snapshot", None)
    splits = getattr(snapshot, "splits", ())
    if not splits:
        return ()

    analysis = getattr(program, "analysis", None)
    handled = set(getattr(analysis, "random_split_indices", ()))
    for episode in getattr(analysis, "bank_episodes", ()):
        handled.update(getattr(episode, "follower_split_indices", ()))

    result: list[tuple[int, int]] = []
    cursor = 0
    for split_index, split in enumerate(splits):
        blocks = getattr(split, "blocks", ())
        if not blocks:
            continue
        try:
            block = snapshot.active_block(split.stable_id)
        except (AttributeError, KeyError):
            block = blocks[0]
        start = cursor
        cursor += int(block.row_count)
        if len(blocks) > 1 and split_index not in handled:
            result.append((start, cursor))
    return tuple(result)


def _crosses_conditional_region(
    bounds: tuple[tuple[int, int], ...],
    *,
    previous_return: int,
    next_wrap: int,
) -> bool:
    return any(
        start <= next_wrap and end > previous_return
        for start, end in bounds
    )


def materialize_segmented_random(
    report: SscRandomExportReport,
) -> tuple[SscLabeledChart, ...]:
    """Materialize helpers, using redraw handoffs only when no Division routes exist."""

    runtime = list(_materialize_startup_random(report))
    if report.helper_count <= 0 or len(runtime) <= 1:
        return tuple(runtime)

    conditional_bounds = _conditional_row_bounds(report)
    if conditional_bounds:
        # Division route siblings can have completely different row grids. Keep
        # the startup-selected helper identity stable rather than trying to map
        # O0/T redraw controls through those incompatible coordinate systems.
        return tuple(runtime)

    columns = report.program.base_snapshot.columns
    planning_base = _dense_rows(report.charts[0].chart.notes, columns)
    planning_wraps = _control_cells(planning_base, columns, _WRAP)
    if len(planning_wraps) <= 1:
        return tuple(runtime)

    planning_returns: list[tuple[tuple[int, int], ...]] = []
    for item in report.charts[1:]:
        controls = _control_cells(_dense_rows(item.chart.notes, columns), columns, _RETURN)
        if len(controls) != len(planning_wraps):
            raise SscExportError(
                "compiled helper contains a different number of Wrap0 planning markers than "
                "the base Wrap count"
            )
        planning_returns.append(controls)

    runtime_rows = [_dense_rows(item.chart.notes, columns) for item in runtime]
    safe = _combined_safe_blank_mask(tuple(runtime_rows), columns)

    for boundary in range(len(planning_wraps) - 1):
        previous_return = max(controls[boundary][0] for controls in planning_returns)
        next_planning_wrap = planning_wraps[boundary + 1][0]
        corridor = _find_handoff_corridor(
            safe,
            after_row=previous_return,
            latest_wrap_row=next_planning_wrap,
        )
        if corridor is None:
            continue

        return_row, wrap_row = corridor
        for rows in runtime_rows[1:]:
            _put_control(rows, columns, return_row, _RETURN)
        _put_control(runtime_rows[0], columns, wrap_row, _WRAP)

    for index, rows in enumerate(runtime_rows):
        runtime[index] = replace(
            runtime[index],
            chart=replace(runtime[index].chart, notes=_measure_rows(rows, columns)),
        )
    return tuple(runtime)


def render_compiled_simfile(report: SscRandomExportReport, song: SscSongInfo) -> str:
    """Render one report with safe random redraws and native Division routes."""

    runtime = materialize_segmented_random(report)
    bundle = materialize_division_routes(report, runtime, prefix="STEPNX")
    text = render_simfile([item.chart for item in bundle.charts], song)
    decorated = _decorate_runtime_metadata(
        text,
        bundle.charts,
        random_mode=report.helper_count > 0,
        chart_names=bundle.chart_names,
    )
    return inject_division_tables(decorated, bundle.division_tables)


def render_compiled_reports(
    reports: tuple[SscRandomExportReport, ...] | list[SscRandomExportReport],
    song: SscSongInfo,
) -> str:
    """Render several source charts with safe random and Division StepSwap routes."""

    frozen = tuple(reports)
    if not frozen:
        raise SscExportError("a combined simfile needs at least one source chart")
    _validate_combined_random_pools(frozen)

    bundles = tuple(
        materialize_division_routes(
            report,
            materialize_segmented_random(report),
            prefix=f"STEPNX_{report_index:02d}",
        )
        for report_index, report in enumerate(frozen, 1)
    )
    charts = tuple(item for bundle in bundles for item in bundle.charts)
    names = tuple(name for bundle in bundles for name in bundle.chart_names)
    tables = tuple(table for bundle in bundles for table in bundle.division_tables)
    if not charts:
        raise SscExportError("a combined simfile needs at least one chart section")
    text = render_simfile([item.chart for item in charts], song)
    decorated = _decorate_runtime_metadata(
        text,
        charts,
        random_mode=any(report.helper_count > 0 for report in frozen),
        chart_names=names,
    )
    return inject_division_tables(decorated, tables)


__all__ = [
    "materialize_segmented_random",
    "render_compiled_simfile",
    "render_compiled_reports",
]
