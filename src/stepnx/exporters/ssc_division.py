"""Compile non-random NX branch splits into XSanity ``#DIVISION`` routes.

This layer sits after the random/Wrap materializer. Random helper identity is
kept as the backing state, while each supported conditional block index becomes
a route variant of that state. XSanity ``#DIVISION`` then switches among the
variants by ``#CHARTNAME`` without flattening the alternate NX blocks.

The first implementation deliberately covers the branch family for which the
NX/SSC corpus is strong enough to generate rather than guess:

* block 0 is the unconditional/fallback route;
* division metadata 5 is Step G and 6 is Step W;
* one of those ranges maps to ``G`` or ``W``;
* matching G+W ranges map to ``WG``;
* the fourth ``#DIVISION`` field is an absolute timestamp in seconds.

Asymmetric G/W ranges and other condition families remain explicit export
errors until their synthesis rule is established. This is preferable to
silently widening a branch condition.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from stepnx.authoring.snapshot import BlockSnapshot
from stepnx.core.model import EmptyRow, LightmapRow, NoteRow, PackedNoteRow
from stepnx.exporters.ssc import (
    SscExportError,
    _ExportState,
    _brain_char,
    _render_cell,
    _row_cells,
)
from stepnx.exporters.ssc_random import SscLabeledChart, SscRandomExportReport
from stepnx.exporters.ssc_xsanity import (
    _control_cells,
    _dense_rows,
    _measure_rows,
    _split_cells,
)

_G_ID = 5
_W_ID = 6
_WRAP = "T"
_RETURN = "O"


@dataclass(frozen=True, slots=True)
class SscDivisionCondition:
    minimum: int
    maximum: int
    operator: str


@dataclass(frozen=True, slots=True)
class SscDivisionDecision:
    split_index: int
    timestamp_seconds: float
    conditions: tuple[SscDivisionCondition | None, ...]

    @property
    def route_count(self) -> int:
        return len(self.conditions)


@dataclass(frozen=True, slots=True)
class SscDivisionRuntime:
    charts: tuple[SscLabeledChart, ...]
    chart_names: tuple[str, ...]
    division_tables: tuple[tuple[str, ...], ...]
    route_count: int


def _range(value: int) -> tuple[int, int]:
    minimum = int(value) & 0xFFFF
    maximum = (int(value) >> 16) & 0xFFFF
    if maximum == 0 and minimum:
        maximum = minimum
    if maximum < minimum:
        raise SscExportError(f"unsupported NX Division range {minimum}..{maximum}")
    return minimum, maximum


def _condition(block: BlockSnapshot, *, split_index: int) -> SscDivisionCondition | None:
    if block.index == 0 and not block.divisions:
        return None

    by_id: dict[int, tuple[int, int]] = {}
    for entry in block.divisions:
        metadata_id = int(entry.meta_id)
        if metadata_id not in {_G_ID, _W_ID}:
            raise SscExportError(
                f"conditional split {split_index} block {block.index} uses Division metadata "
                f"{metadata_id}; automatic XSanity synthesis currently supports only G/W "
                "metadata IDs 5 and 6"
            )
        if metadata_id in by_id:
            raise SscExportError(
                f"conditional split {split_index} block {block.index} repeats Division "
                f"metadata {metadata_id}; the XSanity reduction is ambiguous"
            )
        by_id[metadata_id] = _range(entry.value)

    if not by_id:
        if block.index == 0:
            return None
        raise SscExportError(
            f"conditional split {split_index} block {block.index} has no supported "
            "Division condition"
        )

    g = by_id.get(_G_ID)
    w = by_id.get(_W_ID)
    if g is not None and w is not None:
        if g != w:
            raise SscExportError(
                f"conditional split {split_index} block {block.index} has asymmetric "
                f"G {g[0]}..{g[1]} and W {w[0]}..{w[1]} ranges; the corpus does not "
                "establish a lossless generic WG reduction for that case"
            )
        return SscDivisionCondition(g[0], g[1], "WG")
    if g is not None:
        return SscDivisionCondition(g[0], g[1], "G")
    assert w is not None
    return SscDivisionCondition(w[0], w[1], "W")


def _row_key(row: object) -> object:
    if isinstance(row, EmptyRow):
        return None
    if isinstance(row, (NoteRow, PackedNoteRow)):
        return tuple(cell.raw for cell in row.cells)
    if isinstance(row, LightmapRow):
        raise SscExportError("Lightmap rows have no XSanity Division representation")
    return repr(row)


def _timing_signature(block: BlockSnapshot) -> tuple[object, ...]:
    return (
        block.start_time,
        block.bpm,
        block.scroll,
        block.offset_or_delay,
        block.speed_or_freeze,
        block.beat_split,
        block.beat_measure,
        block.smooth_speed,
        block.raw_flag,
    )


def _first_route_divergence(split) -> int:
    blocks = split.blocks
    if len(blocks) <= 1:
        return 0

    reference = blocks[0]
    signature = _timing_signature(reference)
    for block in blocks[1:]:
        if _timing_signature(block) != signature:
            raise SscExportError(
                f"conditional split {split.index} changes timing between blocks; "
                "the current XSanity Division route splicer only supports note-equivalent timing"
            )

    common = min(block.row_count for block in blocks)
    for row_index in range(common):
        key = _row_key(reference.rows[row_index])
        if any(_row_key(block.rows[row_index]) != key for block in blocks[1:]):
            return row_index
    if any(block.row_count != reference.row_count for block in blocks[1:]):
        return common
    return 0


def _decision_timestamp(split, divergence_row: int) -> float:
    block = split.blocks[0]
    milliseconds = float(block.start_time)
    if divergence_row:
        if block.bpm <= 0.0 or block.beat_split <= 0:
            raise SscExportError(
                f"conditional split {split.index} diverges after row {divergence_row} "
                "but has no usable BPM/BeatSplit for a Division timestamp"
            )
        milliseconds += divergence_row * 60000.0 / (block.bpm * block.beat_split)
    return milliseconds / 1000.0


def _handled_random_splits(report: SscRandomExportReport) -> set[int]:
    handled = set(report.program.analysis.random_split_indices)
    for episode in report.program.analysis.bank_episodes:
        handled.update(episode.follower_split_indices)
    return handled


def compile_division_decisions(
    report: SscRandomExportReport,
) -> tuple[SscDivisionDecision, ...]:
    """Return exportable non-random branch decisions or fail explicitly."""

    snapshot = report.program.base_snapshot
    handled = _handled_random_splits(report)
    decisions: list[SscDivisionDecision] = []
    for split_index, split in enumerate(snapshot.splits):
        if split_index in handled or len(split.blocks) <= 1:
            continue

        row_counts = {block.row_count for block in split.blocks}
        if len(row_counts) != 1:
            raise SscExportError(
                f"conditional split {split_index} has branch row counts "
                f"{sorted(row_counts)}; safe full-chart StepSwap routes require equal geometry"
            )
        if split.blocks[0].divisions:
            raise SscExportError(
                f"conditional split {split_index} block 0 is not an unconditional fallback; "
                "that Division ordering has not been proven for automatic export"
            )

        conditions = tuple(
            _condition(block, split_index=split_index) for block in split.blocks
        )
        divergence = _first_route_divergence(split)
        decisions.append(
            SscDivisionDecision(
                split_index,
                _decision_timestamp(split, divergence),
                conditions,
            )
        )
    return tuple(decisions)


def _split_bounds(snapshot) -> dict[int, tuple[int, int]]:
    cursor = 0
    bounds: dict[int, tuple[int, int]] = {}
    for split_index, split in enumerate(snapshot.splits):
        if not split.blocks:
            continue
        block = snapshot.active_block(split.stable_id)
        start = cursor
        cursor += block.row_count
        bounds[split_index] = (start, cursor)
    return bounds


def _render_block_rows(
    block: BlockSnapshot,
    *,
    columns: int,
    split_index: int,
) -> tuple[list[str], tuple[str, ...]]:
    blank = "0" * columns
    state = _ExportState()
    brain = _brain_char(block)
    rows: list[str] = []
    for row_index, row in enumerate(block.rows):
        cells = _row_cells(row, columns)
        if cells is None:
            rows.append(blank)
            continue
        rendered: list[str] = []
        for lane in range(columns):
            if lane >= len(cells):
                rendered.append("0")
                continue
            rendered.append(
                _render_cell(
                    state,
                    cells[lane],
                    brain,
                    (split_index, block.index, row_index, lane),
                )
            )
        rows.append("".join(rendered))
    if state.diagnostics:
        first = state.diagnostics[0]
        raise SscExportError(
            "alternate Division route introduces an SSC projection warning: "
            f"{first.code}: {first.message}"
        )
    return rows, tuple(sorted(state.banks))


def _put_control(rows: list[str], columns: int, row_index: int, preferred_lane: int, token: str) -> None:
    if row_index >= len(rows):
        raise SscExportError(f"Division route ends before runtime {token} row {row_index}")
    cells = _split_cells(rows[row_index], columns)
    lane = preferred_lane if cells[preferred_lane] == "0" else next(
        (index for index, cell in enumerate(cells) if cell == "0"),
        None,
    )
    if lane is None:
        raise SscExportError(
            f"Division route has no empty lane for runtime {token} at row {row_index}"
        )
    cells[lane] = token
    rows[row_index] = "".join(cells)


def _route_variant(
    source: SscLabeledChart,
    snapshot,
    decisions: tuple[SscDivisionDecision, ...],
    route_index: int,
    *,
    description: str,
    helper_index: int | None,
) -> SscLabeledChart:
    columns = snapshot.columns
    source_rows = _dense_rows(source.chart.notes, columns)
    controls = tuple(
        (*item, token)
        for token in (_WRAP, _RETURN)
        for item in _control_cells(source_rows, columns, token)
    )
    rows = list(source_rows)
    bounds = _split_bounds(snapshot)
    banks = list(source.chart.noteskin_banks)

    for decision in decisions:
        split = snapshot.splits[decision.split_index]
        block_index = route_index if route_index < len(split.blocks) else 0
        if block_index == 0:
            continue
        start, end = bounds[decision.split_index]
        replacement_rows, replacement_banks = _render_block_rows(
            split.blocks[block_index],
            columns=columns,
            split_index=decision.split_index,
        )
        if len(replacement_rows) != end - start:
            raise SscExportError(
                f"conditional split {decision.split_index} route {route_index} changed row geometry"
            )
        rows[start:end] = replacement_rows
        for bank in replacement_banks:
            if bank not in banks:
                banks.append(bank)

    for row_index, lane, token in controls:
        _put_control(rows, columns, row_index, lane, token)

    chart = replace(
        source.chart,
        description=description,
        difficulty="Edit",
        notes=_measure_rows(rows, columns),
        noteskin_banks=tuple(banks),
    )
    return SscLabeledChart(chart, "DIVISION", helper_index)


def _table(
    decisions: tuple[SscDivisionDecision, ...],
    route_names: tuple[str, ...],
) -> tuple[str, ...]:
    entries: list[str] = []
    for decision in decisions:
        timestamp = f"{decision.timestamp_seconds:.5f}"
        for block_index, condition in enumerate(decision.conditions):
            target = route_names[block_index]
            if condition is None:
                entries.append(f"0=0={target}={timestamp}=WG")
            else:
                entries.append(
                    f"{condition.minimum}={condition.maximum}={target}="
                    f"{timestamp}={condition.operator}"
                )
    return tuple(entries)


def materialize_division_routes(
    report: SscRandomExportReport,
    runtime_charts: tuple[SscLabeledChart, ...],
    *,
    prefix: str = "STEPNX",
) -> SscDivisionRuntime:
    """Expand materialized random states into XSanity conditional routes."""

    if not runtime_charts:
        raise SscExportError("Division materializer received no runtime charts")

    decisions = compile_division_decisions(report)
    if not decisions:
        names = []
        for item in runtime_charts:
            if item.helper_index is None:
                names.append(prefix + "_BASE")
            else:
                names.append(prefix + f"_RANDOM_{item.helper_index + 1:03d}")
        return SscDivisionRuntime(
            runtime_charts,
            tuple(names),
            tuple(() for _ in runtime_charts),
            1,
        )

    route_count = max(decision.route_count for decision in decisions)
    base = runtime_charts[0]
    charts: list[SscLabeledChart] = [base]
    names: list[str] = [prefix + "_BASE"]
    tables: list[tuple[str, ...]] = [()]
    base_description = base.chart.description

    if report.helper_count <= 0:
        route_names = tuple(
            names[0] if route == 0 else prefix + f"_DIVISION_{route + 1:02d}"
            for route in range(route_count)
        )
        common_table = _table(decisions, route_names)
        tables[0] = common_table
        for route in range(1, route_count):
            item = _route_variant(
                base,
                report.program.base_snapshot,
                decisions,
                route,
                description=f"{base_description} [StepNX Division {route + 1}]",
                helper_index=None,
            )
            charts.append(item)
            names.append(route_names[route])
            tables.append(common_table)
        return SscDivisionRuntime(tuple(charts), tuple(names), tuple(tables), route_count)

    if len(runtime_charts) != report.helper_count + 1:
        raise SscExportError(
            "random Division expansion expected one materialized chart per helper state"
        )

    # Replicate every random ticket by the same number of conditional routes.
    # XSanity T can therefore see the entire LABELTYPE:DIVISION pool without
    # changing the random-state marginal distribution.
    for helper_index, route0 in enumerate(runtime_charts[1:]):
        route_names = tuple(
            prefix + f"_RANDOM_{helper_index + 1:03d}_ROUTE_{route + 1:02d}"
            for route in range(route_count)
        )
        common_table = _table(decisions, route_names)
        charts.append(route0)
        names.append(route_names[0])
        tables.append(common_table)

        helper_snapshot = report.program.helper_snapshots[helper_index]
        for route in range(1, route_count):
            item = _route_variant(
                route0,
                helper_snapshot,
                decisions,
                route,
                description=(
                    f"{base_description} [StepNX random {helper_index + 1} "
                    f"Division {route + 1}]"
                ),
                helper_index=helper_index,
            )
            charts.append(item)
            names.append(route_names[route])
            tables.append(common_table)

    return SscDivisionRuntime(tuple(charts), tuple(names), tuple(tables), route_count)


__all__ = [
    "SscDivisionCondition",
    "SscDivisionDecision",
    "SscDivisionRuntime",
    "compile_division_decisions",
    "materialize_division_routes",
]
