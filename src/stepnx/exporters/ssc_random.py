"""Compile NX20 load-time random branches into XSanity helper windows.

The low-level :mod:`stepnx.exporters.ssc` writer serializes one already-
materialized authoring snapshot. This module is the semantic layer above it:
it materializes NX ``0x80``/``0x8n``/``0x4n`` state into a reusable XSanity
``LABELTYPE:DIVISION`` helper pool and schedules Wrap (``T``) / Wrap0 (``O``)
execution windows.

Several NX random decisions can be chosen at chart load with no safe visual gap
between their Split regions. XSanity, however, changes the active Steps at a T
cell. Instead of forcing one visible swap per NX decision, dense decisions are
coalesced into one helper window. The selected helper already contains the
whole vector of choices for that window, including named-bank followers.

The SSC-specific default requests exact marginal probabilities up to 2520
helpers. This deliberately covers the two known corpus outliers whose arities
have LCM(7, 8, 9, 10) = 2520. The full Cartesian joint distribution is not
materialized; decisions coalesced into the same window share one helper draw.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil
from pathlib import PurePath

from stepnx.authoring.random_program import (
    CompiledRandomProgram,
    RandomCompileError,
    compile_random_program,
)
from stepnx.authoring.random_state import RandomPoolPolicy
from stepnx.authoring.snapshot import AuthoringSnapshot, create_authoring_snapshot
from stepnx.core.model import NX20Document
from stepnx.exporters.ssc import (
    LINES_PER_MEASURE,
    LINE_BEAT_SPLIT,
    SscChart,
    SscDiagnostic,
    SscExportError,
    SscSongInfo,
    export_chart,
    render_simfile,
)

_LABEL_NORMAL = "NORMAL"
_LABEL_DIVISION = "DIVISION"
_WRAP = "T"
_RETURN = "O"
_ALT_DROPPED = "ssc.alternate-branches-dropped"
_MIN_VISUAL_LOOKAHEAD_BEATS = 2.0
_DEFAULT_XSANITY_RANDOM_POLICY = RandomPoolPolicy(
    max_probability_error=0.0,
    max_helpers=2520,
)


@dataclass(frozen=True, slots=True)
class SscLabeledChart:
    """One generated SSC chart and the LABELTYPE used by XSanity."""

    chart: SscChart
    label_type: str
    helper_index: int | None = None


@dataclass(frozen=True, slots=True)
class SscRandomWindow:
    """One contiguous period during which a selected helper stays active."""

    random_split_indices: tuple[int, ...]
    start_split_index: int
    return_split_index: int
    latest_wrap_row: int


@dataclass(frozen=True, slots=True)
class SscRandomExportReport:
    """A base chart, its Wrap helpers, execution windows, and diagnostics."""

    program: CompiledRandomProgram
    charts: tuple[SscLabeledChart, ...]
    diagnostics: tuple[SscDiagnostic, ...]
    windows: tuple[SscRandomWindow, ...] = ()

    @property
    def helper_count(self) -> int:
        return self.program.helper_count

    @property
    def window_count(self) -> int:
        return len(self.windows)

    @property
    def exact_probabilities(self) -> bool:
        pool = self.program.pool
        return pool.helper_count == pool.exact_helper_count

    @property
    def max_probability_error(self) -> float:
        return self.program.pool.max_probability_error


@dataclass(frozen=True, slots=True)
class _RandomRegion:
    random_split_index: int
    return_split_index: int
    bank_id: int


def _default_description(document: NX20Document) -> str:
    source_name = document.source_name
    if source_name:
        return PurePath(source_name).name
    return "chart.nx"


def _regions(program: CompiledRandomProgram) -> tuple[_RandomRegion, ...]:
    analysis = program.analysis
    episodes = {episode.store_split_index: episode for episode in analysis.bank_episodes}
    result: list[_RandomRegion] = []
    for split_index in analysis.random_split_indices:
        selector = analysis.selectors[split_index]
        if selector.stores_bank:
            episode = episodes[split_index]
            result.append(
                _RandomRegion(split_index, episode.last_use_split_index, selector.bank_id)
            )
        else:
            result.append(_RandomRegion(split_index, split_index, 0))
    return tuple(result)


def _validate_row_geometry(program: CompiledRandomProgram) -> None:
    """Keep T/O boundaries on the same logical row grid in every helper.

    XSanity can carry branch-specific timing inside a helper, but a rejoin after
    alternatives with different row counts needs an explicit beat/time mapping.
    That mapping is not implemented yet, so reject it rather than guessing.
    """

    relevant: set[int] = set(program.analysis.random_split_indices)
    for episode in program.analysis.bank_episodes:
        relevant.update(episode.follower_split_indices)

    for split_index in sorted(relevant):
        split = program.base_snapshot.splits[split_index]
        row_counts = {block.row_count for block in split.blocks}
        if len(row_counts) > 1:
            raise SscExportError(
                f"random split {split_index} has branch row counts {sorted(row_counts)}; "
                "safe Wrap/Wrap0 rejoin for variable-length alternatives is not implemented"
            )


def _split_bounds(snapshot: AuthoringSnapshot) -> dict[int, tuple[int, int]]:
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
                raise SscExportError(f"generated SSC row has an unterminated cell token: {line!r}")
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


def _visual_lookahead_row(
    snapshot: AuthoringSnapshot,
    bounds: dict[int, tuple[int, int]],
    random_split_index: int,
    *,
    minimum_visual_beats: float = _MIN_VISUAL_LOOKAHEAD_BEATS,
) -> int:
    """Latest source row that leaves the requested visual travel before a split.

    The writer maps one NX row to 1/8 SSC beat and emits
    ``SSC_SCROLL = NX_SCROLL * 8``. One source row therefore contributes
    ``abs(NX_SCROLL)`` normal-scroll beats of visual distance. Zero-scroll rows
    contribute no distance and are crossed completely while walking backward.
    """

    if minimum_visual_beats <= 0.0:
        raise ValueError("minimum visual lookahead must be greater than zero")

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


def _plan_windows(program: CompiledRandomProgram) -> tuple[SscRandomWindow, ...]:
    """Coalesce random decisions until every runtime T has a safe visual gap."""

    regions = _regions(program)
    if not regions:
        return ()

    snapshot = program.base_snapshot
    bounds = _split_bounds(snapshot)
    windows: list[SscRandomWindow] = []

    for region in regions:
        latest = _visual_lookahead_row(snapshot, bounds, region.random_split_index)
        if not windows:
            windows.append(
                SscRandomWindow(
                    (region.random_split_index,),
                    region.random_split_index,
                    region.return_split_index,
                    latest,
                )
            )
            continue

        previous = windows[-1]
        previous_return_end = bounds[previous.return_split_index][1]
        if latest <= previous_return_end:
            windows[-1] = SscRandomWindow(
                previous.random_split_indices + (region.random_split_index,),
                previous.start_split_index,
                max(previous.return_split_index, region.return_split_index),
                previous.latest_wrap_row,
            )
            continue

        windows.append(
            SscRandomWindow(
                (region.random_split_index,),
                region.random_split_index,
                region.return_split_index,
                latest,
            )
        )

    return tuple(windows)


def _inject(
    rows: list[str],
    columns: int,
    token: str,
    candidates,
    *,
    description: str,
) -> int:
    for row_index in candidates:
        if row_index < 0:
            continue
        while row_index >= len(rows):
            rows.append("0" * columns)
        cells = _split_cells(rows[row_index], columns)
        for lane, cell in enumerate(cells):
            if cell != "0":
                continue
            cells[lane] = token
            rows[row_index] = "".join(cells)
            return row_index
    raise SscExportError(description)


def _inject_wraps(
    chart: SscChart,
    program: CompiledRandomProgram,
    windows: tuple[SscRandomWindow, ...],
) -> tuple[SscChart, tuple[int, ...]]:
    columns = program.base_snapshot.columns
    rows = _dense_rows(chart.notes, columns)
    bounds = _split_bounds(program.base_snapshot)
    wrap_rows: list[int] = []
    previous_return_end: int | None = None

    for window in windows:
        earliest = 0 if previous_return_end is None else previous_return_end + 1
        latest = window.latest_wrap_row
        if latest < earliest:
            raise SscExportError(
                f"random window beginning at split {window.start_split_index} cannot place a "
                f"Wrap with {_MIN_VISUAL_LOOKAHEAD_BEATS:g} visual beats of lookahead"
            )
        row_index = _inject(
            rows,
            columns,
            _WRAP,
            range(latest, earliest - 1, -1),
            description=(
                f"no empty lane is available before random window beginning at split "
                f"{window.start_split_index} for a Wrap control"
            ),
        )
        wrap_rows.append(row_index)
        previous_return_end = bounds[window.return_split_index][1]

    return replace(chart, notes=_measure_rows(rows, columns)), tuple(wrap_rows)


def _inject_returns(
    chart: SscChart,
    snapshot: AuthoringSnapshot,
    windows: tuple[SscRandomWindow, ...],
    wrap_rows: tuple[int, ...],
) -> tuple[SscChart, tuple[int, ...]]:
    columns = snapshot.columns
    rows = _dense_rows(chart.notes, columns)
    bounds = _split_bounds(snapshot)
    return_rows: list[int] = []

    for index, window in enumerate(windows):
        _, return_end = bounds[window.return_split_index]
        next_wrap = wrap_rows[index + 1] if index + 1 < len(wrap_rows) else None
        if next_wrap is None:
            candidates = range(return_end, max(return_end + LINES_PER_MEASURE, len(rows)))
        else:
            if return_end >= next_wrap:
                raise SscExportError(
                    f"random window ending at split {window.return_split_index} overlaps the "
                    f"next Wrap row {next_wrap}; helper cannot safely rejoin the base chart"
                )
            candidates = range(return_end, next_wrap)

        return_rows.append(
            _inject(
                rows,
                columns,
                _RETURN,
                candidates,
                description=(
                    f"no empty lane is available after random window ending at split "
                    f"{window.return_split_index} for a Wrap0 return"
                ),
            )
        )

    return replace(chart, notes=_measure_rows(rows, columns)), tuple(return_rows)


def _sparsify_helper(
    chart: SscChart,
    *,
    columns: int,
    wrap_rows: tuple[int, ...],
    return_rows: tuple[int, ...],
) -> SscChart:
    """Drop note payload while the helper can never be active.

    All rows from T through O are retained verbatim so deterministic notes in a
    window's visual lead and tail still exist after XSanity changes Steps. Rows
    between windows become collapsed blank measures, and everything after the
    final O is trimmed entirely. Timing tags are intentionally kept because the
    working Sanity DIVISION corpus carries chart-level timing and we do not yet
    have runtime evidence that omitting it is safe.
    """

    if not wrap_rows:
        return chart
    if len(wrap_rows) != len(return_rows):
        raise SscExportError("helper sparsification received mismatched Wrap/Wrap0 boundaries")

    rows = _dense_rows(chart.notes, columns)
    blank = "0" * columns
    keep = [False] * len(rows)
    for start, end in zip(wrap_rows, return_rows):
        if end < start:
            raise SscExportError(f"helper return row {end} precedes Wrap row {start}")
        if end >= len(keep):
            keep.extend([False] * (end + 1 - len(keep)))
            rows.extend([blank] * (end + 1 - len(rows)))
        for row_index in range(start, end + 1):
            keep[row_index] = True

    for row_index, retained in enumerate(keep):
        if not retained:
            rows[row_index] = blank

    last = max(return_rows) + 1
    return replace(chart, notes=_measure_rows(rows[:last], columns))


def _correct_scrolls(snapshot: AuthoringSnapshot) -> str:
    """Use the corpus-confirmed NX -> XSanity scroll conversion."""

    position = 0.0
    entries: list[str] = []
    for split in snapshot.splits:
        if not split.blocks:
            continue
        block = snapshot.active_block(split.stable_id)
        entries.append(f"{position:g}={block.scroll * LINE_BEAT_SPLIT:g},")
        position += block.row_count / LINE_BEAT_SPLIT
    return "".join(entries)


def _project(
    document: NX20Document,
    snapshot: AuthoringSnapshot,
    *,
    description: str,
    difficulty: str | None,
    meter: int | None,
    credit: str | None,
) -> tuple[SscChart, tuple[SscDiagnostic, ...]]:
    report = export_chart(
        document,
        description=description,
        difficulty=difficulty,
        meter=meter,
        credit=credit,
        snapshot=snapshot,
    )
    chart = replace(report.chart, scrolls=_correct_scrolls(snapshot))
    diagnostics = tuple(item for item in report.diagnostics if item.code != _ALT_DROPPED)
    return chart, diagnostics


def _merge_diagnostics(groups: list[tuple[SscDiagnostic, ...]]) -> tuple[SscDiagnostic, ...]:
    order: list[tuple[str, str]] = []
    merged: dict[tuple[str, str], SscDiagnostic] = {}
    for group in groups:
        for item in group:
            key = (item.code, item.message)
            current = merged.get(key)
            if current is None:
                order.append(key)
                merged[key] = item
            else:
                merged[key] = replace(
                    current, occurrences=current.occurrences + item.occurrences
                )
    return tuple(merged[key] for key in order)


def _semantic_diagnostics(
    program: CompiledRandomProgram,
    windows: tuple[SscRandomWindow, ...],
) -> tuple[SscDiagnostic, ...]:
    diagnostics: list[SscDiagnostic] = []
    handled = set(program.analysis.random_split_indices)
    for episode in program.analysis.bank_episodes:
        handled.update(episode.follower_split_indices)

    pending = [
        index
        for index, split in enumerate(program.base_snapshot.splits)
        if len(split.blocks) > 1 and index not in handled
    ]
    if pending:
        alternatives = sum(
            len(program.base_snapshot.splits[index].blocks) - 1 for index in pending
        )
        diagnostics.append(
            SscDiagnostic(
                "ssc.conditional-branches-pending",
                f"{alternatives} alternate branch(es) across {len(pending)} non-random split(s) "
                "still require #DIVISION compilation; the active block is exported for now",
                split_index=pending[0],
                occurrences=len(pending),
            )
        )

    pool = program.pool
    if pool.helper_count and pool.helper_count != pool.exact_helper_count:
        diagnostics.append(
            SscDiagnostic(
                "ssc.random-probability-approximation",
                f"exact random probabilities require {pool.exact_helper_count} helper states; "
                f"generated {pool.helper_count} with maximum per-outcome error "
                f"{pool.max_probability_error * 100:.3f} percentage points",
            )
        )

    compressed = [window for window in windows if len(window.random_split_indices) > 1]
    if compressed:
        decisions = sum(len(window.random_split_indices) for window in compressed)
        diagnostics.append(
            SscDiagnostic(
                "ssc.random-window-compressed-joint",
                f"{decisions} load-time random decisions are coalesced into "
                f"{len(compressed)} XSanity helper window(s). Per-split ticket probabilities "
                "follow the planned distribution, but decisions inside one window share a "
                "single helper draw instead of materializing the full Cartesian joint state.",
                split_index=compressed[0].start_split_index,
                occurrences=len(compressed),
            )
        )
    return tuple(diagnostics)


def compile_ssc_export(
    document: NX20Document,
    *,
    description: str | None = None,
    difficulty: str | None = None,
    meter: int | None = None,
    credit: str | None = None,
    policy: RandomPoolPolicy = _DEFAULT_XSANITY_RANDOM_POLICY,
) -> SscRandomExportReport:
    """Compile one NX20 chart into a base SSC chart plus sparse random helpers.

    The XSanity profile requests exact marginal ticket counts whenever their LCM
    is at most 2520. Dense load-time decisions are grouped into execution
    windows so T never has to fire with less than two visual beats of lead.
    Non-random alternate blocks are not yet compiled into ``#DIVISION`` and are
    reported explicitly.
    """

    snapshot = create_authoring_snapshot(document)
    try:
        program = compile_random_program(snapshot, policy)
    except (RandomCompileError, ValueError) as exc:
        raise SscExportError(str(exc)) from exc

    _validate_row_geometry(program)
    windows = _plan_windows(program)
    base_description = description or _default_description(document)
    base, base_diagnostics = _project(
        document,
        program.base_snapshot,
        description=base_description,
        difficulty=difficulty,
        meter=meter,
        credit=credit,
    )
    base, wrap_rows = _inject_wraps(base, program, windows)

    labeled: list[SscLabeledChart] = [SscLabeledChart(base, _LABEL_NORMAL)]
    diagnostic_groups: list[tuple[SscDiagnostic, ...]] = [base_diagnostics]
    for helper_index, helper_snapshot in enumerate(program.helper_snapshots):
        helper_description = f"{base_description} [StepNX random {helper_index + 1}]"
        helper, helper_diagnostics = _project(
            document,
            helper_snapshot,
            description=helper_description,
            difficulty="Edit",
            meter=meter,
            credit=credit,
        )
        helper, return_rows = _inject_returns(helper, helper_snapshot, windows, wrap_rows)
        helper = _sparsify_helper(
            helper,
            columns=helper_snapshot.columns,
            wrap_rows=wrap_rows,
            return_rows=return_rows,
        )
        labeled.append(SscLabeledChart(helper, _LABEL_DIVISION, helper_index))
        diagnostic_groups.append(helper_diagnostics)

    diagnostic_groups.append(_semantic_diagnostics(program, windows))
    return SscRandomExportReport(
        program=program,
        charts=tuple(labeled),
        diagnostics=_merge_diagnostics(diagnostic_groups),
        windows=windows,
    )


def _with_labeltypes(text: str, labels: tuple[str, ...]) -> str:
    output: list[str] = []
    label_index = 0
    for line in text.splitlines():
        output.append(line)
        if not line.startswith("#DESCRIPTION:"):
            continue
        if label_index >= len(labels):
            raise SscExportError("rendered simfile contains more chart sections than expected")
        output.append(f"#LABELTYPE:{labels[label_index]};")
        label_index += 1
    if label_index != len(labels):
        raise SscExportError(
            f"rendered simfile contains {label_index} chart sections but {len(labels)} labels were expected"
        )
    return "\n".join(output) + "\n"


def render_compiled_simfile(report: SscRandomExportReport, song: SscSongInfo) -> str:
    """Render a standalone XSanity SSC including NORMAL/DIVISION labels."""

    charts = [item.chart for item in report.charts]
    labels = tuple(item.label_type for item in report.charts)
    return _with_labeltypes(render_simfile(charts, song), labels)


__all__ = [
    "SscLabeledChart",
    "SscRandomWindow",
    "SscRandomExportReport",
    "compile_ssc_export",
    "render_compiled_simfile",
]
