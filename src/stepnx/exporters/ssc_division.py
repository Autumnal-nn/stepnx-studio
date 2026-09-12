"""Compile non-random NX branch splits into XSanity ``#DIVISION`` routes.

Unlike load-time random helpers, native NX conditional routes are not required to
share row geometry. Official Fiesta EX pairs contain branches that represent the
same wall-clock interval at wildly different BeatSplit values. The important
example is EF1225: one Split has 1206/9648/19296/38592-row alternatives, and the
matching Sanity SSC keeps them as four complete STEP streams with independent
BPMS/SCROLLS.

The exporter therefore never splices an alternate block into the already rendered
base row grid. It materializes a complete AuthoringSnapshot per route and projects
that snapshot through the ordinary NX->SSC writer. This preserves each branch's
own row count, BeatSplit, BPM and scroll while ``#DIVISION`` changes the active
Steps by CHARTNAME at runtime.

Supported condition family:

* block 0 is the unconditional/fallback route;
* Division metadata 5 is G and 6 is W;
* matching G+W ranges map to WG;
* direct official pairs also prove the common-prefix asymmetric form, for example
  G 1..1 + W 1..3 -> WG 1..3;
* G/W counter maxima above 999 are clamped to the native Sanity 999 sentinel used
  by the exact Fiesta EX pairs (NX 30000 -> SSC 999).

A banked non-random selector such as 0x01 establishes a conditional route index;
later 0x41 Splits reuse that route rather than creating a new #DIVISION decision.
That mirrors the STEP1/STEP2/... path construction used by the official converter.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from stepnx.authoring.random_state import decode_split_selector
from stepnx.authoring.snapshot import AuthoringSnapshot, BlockSnapshot
from stepnx.core.model import EmptyRow, LightmapRow, NoteRow, PackedNoteRow
from stepnx.exporters.ssc import (
    LINE_BEAT_SPLIT,
    SscChart,
    SscExportError,
    _BANK_ORDER,
    _ExportState,
    _measures,
    _note_lines,
    _timing,
)
from stepnx.exporters.ssc_random import SscLabeledChart, SscRandomExportReport

_G_ID = 5
_W_ID = 6
_XSANITY_GW_MAX = 999
_RUNTIME_LOOKAHEAD_BEATS = 2.0


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
    route_split_indices: tuple[int, ...] = ()
    bank_id: int = 0

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

    # The exact Fiesta EX pairs encode e.g. 0x75300001 (1..30000) as
    # 1=999 in Sanity. 999 is the observed open-ended G/W sentinel.
    minimum = min(minimum, _XSANITY_GW_MAX)
    maximum = min(maximum, _XSANITY_GW_MAX)
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
        if g == w:
            return SscDivisionCondition(g[0], g[1], "WG")

        # Direct NX<->SSC pairs from the REBIRTH/Fiesta EX family establish
        # common-lower-bound WG widening: G 1..1 + W 1..N -> WG 1..N.
        # Do not extrapolate to crossed or disjoint ranges.
        if g[0] == w[0] and (g[1] <= w[1] or w[1] <= g[1]):
            return SscDivisionCondition(g[0], max(g[1], w[1]), "WG")
        raise SscExportError(
            f"conditional split {split_index} block {block.index} has unsupported "
            f"asymmetric G {g[0]}..{g[1]} and W {w[0]}..{w[1]} ranges"
        )
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
        block.bpm,
        block.scroll,
        block.offset_or_delay,
        block.speed_or_freeze,
        block.beat_split,
        block.beat_measure,
        block.smooth_speed,
        block.raw_flag,
        block.row_count,
    )


def _first_route_divergence(split) -> int:
    blocks = split.blocks
    if len(blocks) <= 1:
        return 0
    common = min(block.row_count for block in blocks)
    for row_index in range(common):
        key = _row_key(blocks[0].rows[row_index])
        if any(_row_key(block.rows[row_index]) != key for block in blocks[1:]):
            return row_index
    return common if any(block.row_count != blocks[0].row_count for block in blocks[1:]) else 0


def _decision_timestamp(split) -> float:
    """Choose a runtime-safe evaluation time for one conditional route change.

    Equal-geometry branches can use their first actual divergence directly.
    Variable-geometry branches need the Steps swap before their row grids split.
    Official EF1225 lands essentially two musical beats before the conditional
    Split, so use that conservative lookahead until the control-arrow timestamp
    compiler is promoted from the mission corpus work.
    """

    base = split.blocks[0]
    signatures = {_timing_signature(block) for block in split.blocks}
    if len(signatures) == 1:
        divergence = _first_route_divergence(split)
        milliseconds = float(base.start_time)
        if divergence:
            if base.bpm <= 0.0 or base.beat_split <= 0:
                raise SscExportError(
                    f"conditional split {split.index} diverges after row {divergence} "
                    "but has no usable BPM/BeatSplit for a Division timestamp"
                )
            milliseconds += divergence * 60000.0 / (base.bpm * base.beat_split)
        return milliseconds / 1000.0

    if base.bpm <= 0.0:
        return max(0.0, float(base.start_time) / 1000.0)
    lead_seconds = _RUNTIME_LOOKAHEAD_BEATS * 60.0 / float(base.bpm)
    return max(0.0, float(base.start_time) / 1000.0 - lead_seconds)


def _handled_random_splits(report: SscRandomExportReport) -> set[int]:
    handled = set(report.program.analysis.random_split_indices)
    for episode in report.program.analysis.bank_episodes:
        handled.update(episode.follower_split_indices)
    return handled


def compile_division_decisions(
    report: SscRandomExportReport,
) -> tuple[SscDivisionDecision, ...]:
    """Compile non-random conditional stores and their bank followers."""

    snapshot = report.program.base_snapshot
    handled = _handled_random_splits(report)
    builders: list[dict[str, object]] = []
    bank_store: dict[int, int] = {}

    for split_index, split in enumerate(snapshot.splits):
        if split_index in handled or len(split.blocks) <= 1:
            continue

        selector = decode_split_selector(split.raw_select)
        if selector.follows_named_bank and not selector.random_start:
            builder_index = bank_store.get(selector.bank_id)
            if builder_index is None:
                raise SscExportError(
                    f"conditional split {split_index} follows bank {selector.bank_id} "
                    "without an earlier conditional store"
                )
            route_splits = builders[builder_index]["route_splits"]
            assert isinstance(route_splits, list)
            route_splits.append(split_index)
            continue

        if split.blocks[0].divisions:
            raise SscExportError(
                f"conditional split {split_index} block 0 is not an unconditional fallback; "
                "that Division ordering has not been proven for automatic export"
            )

        conditions = tuple(_condition(block, split_index=split_index) for block in split.blocks)
        builders.append(
            {
                "split_index": split_index,
                "timestamp": _decision_timestamp(split),
                "conditions": conditions,
                "route_splits": [split_index],
                "bank_id": selector.bank_id if 1 <= selector.bank_id <= 31 else 0,
            }
        )
        if 1 <= selector.bank_id <= 31 and not selector.follow_bank:
            bank_store[selector.bank_id] = len(builders) - 1

    return tuple(
        SscDivisionDecision(
            int(builder["split_index"]),
            float(builder["timestamp"]),
            tuple(builder["conditions"]),
            tuple(builder["route_splits"]),
            int(builder["bank_id"]),
        )
        for builder in builders
    )


def _snapshot_for_route(
    snapshot: AuthoringSnapshot,
    decisions: tuple[SscDivisionDecision, ...],
    route_index: int,
) -> AuthoringSnapshot:
    result = snapshot
    for decision in decisions:
        for split_index in decision.route_split_indices or (decision.split_index,):
            split = result.splits[split_index]
            block_index = route_index if route_index < len(split.blocks) else 0
            result = result.with_active_block(split.stable_id, split.blocks[block_index].stable_id)
    return result


def _split_bounds(snapshot: AuthoringSnapshot) -> dict[int, tuple[int, int]]:
    """Compatibility row bounds for lifetime analysis on equal-grid routes."""

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


def _correct_scrolls(snapshot: AuthoringSnapshot) -> str:
    position = 0.0
    entries: list[str] = []
    for split in snapshot.splits:
        if not split.blocks:
            continue
        block = snapshot.active_block(split.stable_id)
        entries.append(f"{position:g}={block.scroll * LINE_BEAT_SPLIT:g},")
        position += block.row_count / LINE_BEAT_SPLIT
    return "".join(entries)


def _project_snapshot(
    source: SscLabeledChart,
    snapshot: AuthoringSnapshot,
    *,
    description: str,
    difficulty: str,
    label_type: str,
    helper_index: int | None,
) -> SscLabeledChart:
    """Render one complete route without assuming another route's row grid."""

    columns = snapshot.columns
    state = _ExportState()
    lines, blank = _note_lines(snapshot, columns, state)
    bpms, stops, delays, warps, _unused_scrolls, speeds = _timing(snapshot, state)
    if state.diagnostics:
        first = state.diagnostics[0]
        raise SscExportError(
            "alternate Division route introduces an SSC projection warning: "
            f"{first.code}: {first.message}"
        )

    first_block = next(
        (snapshot.active_block(split.stable_id) for split in snapshot.splits if split.blocks),
        None,
    )
    if first_block is None:
        raise SscExportError("Division route contains no playable block")

    chart = replace(
        source.chart,
        description=description,
        difficulty=difficulty,
        offset=-float(first_block.start_time) / 1000.0,
        bpms=bpms,
        stops=stops,
        delays=delays,
        warps=warps,
        scrolls=_correct_scrolls(snapshot),
        speeds=speeds,
        notes=_measures(lines, blank),
        noteskin_banks=tuple(name for name in _BANK_ORDER if name in state.banks),
    )
    return SscLabeledChart(chart, label_type, helper_index)


def _route_variant(
    source: SscLabeledChart,
    snapshot: AuthoringSnapshot,
    decisions: tuple[SscDivisionDecision, ...],
    route_index: int,
    *,
    description: str,
    helper_index: int | None,
) -> SscLabeledChart:
    """Compatibility adapter for lifetime-aware late Division optimization.

    Older lifetime code asks for one alternate route by index. Route generation
    is now full-snapshot projection, so this adapter deliberately avoids the old
    equal-row splicing behavior while keeping that optimizer's API stable.
    """

    routed = _snapshot_for_route(snapshot, decisions, route_index)
    return _project_snapshot(
        source,
        routed,
        description=description,
        difficulty="Edit",
        label_type="DIVISION",
        helper_index=helper_index,
    )


def _table(
    decisions: tuple[SscDivisionDecision, ...],
    route_names: tuple[str, ...],
) -> tuple[str, ...]:
    entries: list[str] = []
    for decision in decisions:
        timestamp = f"{decision.timestamp_seconds:.5f}"
        for block_index, condition in enumerate(decision.conditions):
            if block_index >= len(route_names):
                raise SscExportError("Division route table has fewer CHARTNAMEs than block routes")
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
    """Expand conditional block indices into complete XSanity route streams."""

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
    base_runtime = runtime_charts[0]
    base_description = base_runtime.chart.description

    if report.helper_count <= 0:
        route_names = tuple(
            prefix + "_BASE" if route == 0 else prefix + f"_DIVISION_{route + 1:02d}"
            for route in range(route_count)
        )
        common_table = _table(decisions, route_names)
        charts: list[SscLabeledChart] = []
        for route in range(route_count):
            snapshot = _snapshot_for_route(report.program.base_snapshot, decisions, route)
            charts.append(
                _project_snapshot(
                    base_runtime,
                    snapshot,
                    description=(
                        base_description
                        if route == 0
                        else f"{base_description} [StepNX Division {route + 1}]"
                    ),
                    difficulty=(base_runtime.chart.difficulty if route == 0 else "Edit"),
                    # Native conditional STEP streams are ordinary routes; the
                    # DIVISION label is reserved for Wrap's random helper pool.
                    label_type="NORMAL",
                    helper_index=None,
                )
            )
        return SscDivisionRuntime(
            tuple(charts),
            route_names,
            tuple(common_table for _ in charts),
            route_count,
        )

    if len(runtime_charts) != report.helper_count + 1:
        raise SscExportError(
            "random Division expansion expected one materialized chart per helper state"
        )

    # Keep the NORMAL startup stream (and its T) untouched. Every random ticket
    # is replicated by the same route count, so T's marginal random distribution
    # is unchanged; #DIVISION subsequently moves only among siblings of that
    # helper state.
    charts = [base_runtime]
    names = [prefix + "_BASE"]
    tables: list[tuple[str, ...]] = [()]

    for helper_index, runtime_helper in enumerate(runtime_charts[1:]):
        route_names = tuple(
            prefix + f"_RANDOM_{helper_index + 1:03d}_ROUTE_{route + 1:02d}"
            for route in range(route_count)
        )
        common_table = _table(decisions, route_names)
        helper_snapshot = report.program.helper_snapshots[helper_index]
        for route in range(route_count):
            snapshot = _snapshot_for_route(helper_snapshot, decisions, route)
            charts.append(
                _project_snapshot(
                    runtime_helper,
                    snapshot,
                    description=(
                        f"{base_description} [StepNX random {helper_index + 1} "
                        f"Division {route + 1}]"
                    ),
                    difficulty="Edit",
                    label_type="DIVISION",
                    helper_index=helper_index,
                )
            )
            names.append(route_names[route])
            tables.append(common_table)

    return SscDivisionRuntime(tuple(charts), tuple(names), tuple(tables), route_count)


def inject_division_tables(
    text: str,
    division_tables: tuple[tuple[str, ...], ...],
) -> str:
    """Insert per-Steps Division metadata into an already decorated simfile."""

    if not any(division_tables):
        return text

    output: list[str] = []
    chart_index = -1
    inserted: set[int] = set()
    for line in text.splitlines():
        if line == "#NOTEDATA:;":
            chart_index += 1
        output.append(line)
        if not line.startswith("#TICKCOUNTS:"):
            continue
        if chart_index < 0 or chart_index >= len(division_tables):
            raise SscExportError("Division table count does not match rendered chart sections")
        entries = division_tables[chart_index]
        if not entries:
            continue
        output.append("#DIVISION:" + entries[0])
        output.extend("," + entry for entry in entries[1:])
        output.append(";")
        output.append("#SPECIALDIVISION:;")
        inserted.add(chart_index)

    if chart_index + 1 != len(division_tables):
        raise SscExportError(
            f"rendered simfile contains {chart_index + 1} chart sections but "
            f"{len(division_tables)} Division table slots were expected"
        )
    missing = [
        index
        for index, entries in enumerate(division_tables)
        if entries and index not in inserted
    ]
    if missing:
        raise SscExportError(
            "rendered simfile is missing #TICKCOUNTS for Division chart section(s): "
            + ", ".join(str(index + 1) for index in missing)
        )
    return "\n".join(output) + "\n"


__all__ = [
    "SscDivisionCondition",
    "SscDivisionDecision",
    "SscDivisionRuntime",
    "compile_division_decisions",
    "inject_division_tables",
    "materialize_division_routes",
]
