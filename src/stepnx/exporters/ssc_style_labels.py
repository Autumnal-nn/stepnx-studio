"""Project NX Division metadata 200 to Sanity playfield control labels.

Fiesta 2 uses Division ID 200 as a per-block playfield-style override. Exact
Fiesta EX -> StepPrime pairs show that the historical converter does not encode
the raw integer. It encodes the resulting geometry as reserved ``#LABELS``
commands consumed by the Sanity/StepPrime fork::

    CENTERED (3) -> OFFSET00
    SINGLE   (0) -> OFFSET01 for P1 / OFFSET02 for P2
    VERSUS   (2) -> OFFSET01
    DOUBLE   (1) -> OFFSET02

The same pairs also show state-change semantics: repeated values do not emit
repeated labels. EF1329 is the small reference case, with CENTERED at beat 0,
SINGLE at 92.5, CENTERED at 93.75, SINGLE at 95.25, and CENTERED at 100.25.

This is intentionally a runtime decoration layer. ``OFFSETxx`` is a semantic
projection of geometry, not an invertible serialization of the original ID 200
integer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from stepnx.authoring.snapshot import AuthoringSnapshot
from stepnx.exporters.ssc import LINE_BEAT_SPLIT, SscExportError
from stepnx.exporters.ssc_division import (
    SscDivisionRuntime,
    SscDivisionDecision,
    _snapshot_for_route,
    compile_division_decisions,
)
from stepnx.exporters.ssc_random import SscRandomExportReport
from stepnx.preview.geometry import PlayfieldStyle, default_playfield_style

_DIV200 = 200
_ROUTE_RE = re.compile(r"_DIVISION_(\d+)$|_ROUTE_(\d+)$")


@dataclass(frozen=True, slots=True)
class _StyleEvent:
    beat: float
    label: str


def _division_style(block) -> int | None:
    value: int | None = None
    for entry in block.divisions:
        if int(entry.meta_id) == _DIV200:
            value = int(entry.value)
    return value


def _has_div200(snapshot: AuthoringSnapshot) -> bool:
    return any(
        _division_style(snapshot.active_block(split.stable_id)) is not None
        for split in snapshot.splits
        if split.blocks
    )


def _style_label(style: int, *, start_column: int) -> str:
    try:
        parsed = PlayfieldStyle(int(style))
    except ValueError as exc:
        raise SscExportError(
            f"Division 200 style {style} has no proven Sanity OFFSET projection"
        ) from exc

    if parsed is PlayfieldStyle.CENTERED:
        return "OFFSET00"
    if parsed is PlayfieldStyle.SINGLE:
        return "OFFSET02" if int(start_column) >= 5 else "OFFSET01"
    if parsed is PlayfieldStyle.VERSUS:
        return "OFFSET01"
    if parsed is PlayfieldStyle.DOUBLE:
        return "OFFSET02"
    raise AssertionError(parsed)


def _style_events(snapshot: AuthoringSnapshot) -> tuple[_StyleEvent, ...]:
    """Return effective geometry changes on the writer's virtual beat axis."""

    if not _has_div200(snapshot):
        return ()

    default_style = int(default_playfield_style(snapshot.columns))
    beat = 0.0
    previous: str | None = None
    result: list[_StyleEvent] = []
    for split in snapshot.splits:
        if not split.blocks:
            continue
        block = snapshot.active_block(split.stable_id)
        style = _division_style(block)
        if style is None:
            style = default_style
        label = _style_label(style, start_column=snapshot.start_column)
        if label != previous:
            result.append(_StyleEvent(beat, label))
            previous = label
        beat += block.row_count / LINE_BEAT_SPLIT
    return tuple(result)


def _beat_at_split(snapshot: AuthoringSnapshot, split_index: int) -> float:
    beat = 0.0
    for index, split in enumerate(snapshot.splits):
        if index >= split_index:
            break
        if split.blocks:
            beat += snapshot.active_block(split.stable_id).row_count / LINE_BEAT_SPLIT
    return beat


def _event_value_at(events: tuple[_StyleEvent, ...], beat: float) -> str | None:
    value: str | None = None
    for event in events:
        if event.beat > beat:
            break
        value = event.label
    return value


def _normalize_events(events: list[_StyleEvent]) -> tuple[_StyleEvent, ...]:
    ordered = sorted(events, key=lambda event: event.beat)
    result: list[_StyleEvent] = []
    for event in ordered:
        if result and abs(result[-1].beat - event.beat) < 1e-9:
            result[-1] = event
            continue
        if result and result[-1].label == event.label:
            continue
        result.append(event)
    return tuple(result)


def _hybrid_tail_events(
    helper: AuthoringSnapshot,
    routed: AuthoringSnapshot,
    decision: SscDivisionDecision,
) -> tuple[_StyleEvent, ...]:
    """Combine a random helper prefix with a late named Division route suffix."""

    boundary = _beat_at_split(helper, decision.split_index)
    prefix = [event for event in _style_events(helper) if event.beat < boundary]
    routed_events = _style_events(routed)
    suffix: list[_StyleEvent] = []
    state = _event_value_at(routed_events, boundary)
    if state is not None:
        suffix.append(_StyleEvent(boundary, state))
    suffix.extend(event for event in routed_events if event.beat > boundary)
    return _normalize_events(prefix + suffix)


def _route_from_name(name: str) -> int | None:
    match = _ROUTE_RE.search(name)
    if match is None:
        return None
    raw = match.group(1) or match.group(2)
    assert raw is not None
    return int(raw) - 1


def _entry_target(entry: str) -> str | None:
    parts = entry.split("=")
    return parts[2] if len(parts) >= 5 else None


def _condition_route_index(
    entry: str,
    decision: SscDivisionDecision,
) -> int | None:
    parts = entry.split("=")
    if len(parts) < 5:
        return None
    try:
        minimum = int(parts[0])
        maximum = int(parts[1])
    except ValueError:
        return None
    operator = parts[-1]
    for index, condition in enumerate(decision.conditions):
        if condition is None:
            continue
        if (
            condition.minimum == minimum
            and condition.maximum == maximum
            and condition.operator == operator
        ):
            return index
    return None


def _named_tail_routes(
    bundle: SscDivisionRuntime,
    decisions: tuple[SscDivisionDecision, ...],
) -> dict[str, int]:
    """Recover route indices for helpers reused as late Division destinations."""

    if len(decisions) != 1:
        return {}
    decision = decisions[0]
    result: dict[str, int] = {}
    for table in bundle.division_tables:
        for entry in table:
            target = _entry_target(entry)
            route = _condition_route_index(entry, decision)
            if target is not None and route is not None:
                result[target] = route
    return result


def _snapshot_events_for_chart(
    report: SscRandomExportReport,
    bundle: SscDivisionRuntime,
    chart_index: int,
    decisions: tuple[SscDivisionDecision, ...],
    tail_routes: dict[str, int],
) -> tuple[_StyleEvent, ...]:
    item = bundle.charts[chart_index]
    name = bundle.chart_names[chart_index]
    route_index = _route_from_name(name)

    if item.helper_index is not None:
        helper = report.program.helper_snapshots[item.helper_index]
        if route_index is not None and decisions:
            routed = _snapshot_for_route(helper, decisions, route_index)
            return _style_events(routed)

        tail_route = tail_routes.get(name)
        if tail_route is not None and len(decisions) == 1:
            routed = _snapshot_for_route(
                report.program.base_snapshot,
                decisions,
                tail_route,
            )
            return _hybrid_tail_events(helper, routed, decisions[0])
        return _style_events(helper)

    if route_index is not None and decisions:
        routed = _snapshot_for_route(report.program.base_snapshot, decisions, route_index)
        return _style_events(routed)
    return _style_events(report.program.base_snapshot)


def div200_label_tables(
    report: SscRandomExportReport,
    bundle: SscDivisionRuntime,
) -> tuple[tuple[str, ...], ...]:
    """Build per-Steps reserved OFFSET label tables for one runtime bundle."""

    decisions = compile_division_decisions(report)
    tail_routes = _named_tail_routes(bundle, decisions)
    tables: list[tuple[str, ...]] = []
    for chart_index in range(len(bundle.charts)):
        events = _snapshot_events_for_chart(
            report,
            bundle,
            chart_index,
            decisions,
            tail_routes,
        )
        tables.append(
            tuple(f"{event.beat:.6f}={event.label}" for event in events)
        )
    return tuple(tables)


def inject_steps_labels(
    text: str,
    tables: tuple[tuple[str, ...], ...],
) -> str:
    """Insert generated ``#LABELS`` immediately before each Steps ``#NOTES``.

    Division metadata is inserted earlier in the pipeline immediately after
    ``#SPEEDS``. Injecting here therefore reproduces the official StepPrime
    ordering: SPEEDS -> DIVISION -> SPECIALDIVISION -> LABELS -> NOTES.
    """

    if not any(tables):
        return text

    output: list[str] = []
    chart_index = -1
    inserted: set[int] = set()
    for line in text.splitlines():
        if line == "#NOTEDATA:;":
            chart_index += 1
        if line.startswith("#NOTES:") and 0 <= chart_index < len(tables):
            entries = tables[chart_index]
            if entries:
                output.append("#LABELS:" + entries[0])
                output.extend("," + entry for entry in entries[1:])
                output.append(";")
                inserted.add(chart_index)
        output.append(line)

    if chart_index + 1 != len(tables):
        raise SscExportError(
            f"rendered simfile contains {chart_index + 1} chart sections but "
            f"{len(tables)} Division-200 label tables were expected"
        )
    missing = [index for index, entries in enumerate(tables) if entries and index not in inserted]
    if missing:
        raise SscExportError(
            "rendered simfile is missing #NOTES for Division-200 chart section(s): "
            + ", ".join(str(index + 1) for index in missing)
        )
    return "\n".join(output) + "\n"


__all__ = ["div200_label_tables", "inject_steps_labels"]
