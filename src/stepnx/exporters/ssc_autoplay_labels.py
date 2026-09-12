"""Project NX Division metadata 999 to Sanity AUTOPLAY control labels.

NX names Division metadata 999 ``dpAutoplay``. The official Fiesta EX Sanity
corpus represents that state through reserved ``#LABELS`` commands::

    AUTOPLAYON
    AUTOPLAYOFF

EF1329 is the clean reference fixture. Its ID-999 blocks begin at generated
beats 92.500 and 95.250, while the official labels are at 92.750 and 95.500;
the OFF transitions likewise land one quarter beat after the following block
boundary. This module therefore emits state changes at block start + 0.25 beat,
matching that proven converter convention rather than treating 999 as an
ordinary #DIVISION predicate.

The native field is a JUDGE-like autoplay parameter and rare corpus values 3/4
exist, but the Sanity control vocabulary observed in the supplied corpus is
binary. Consequently zero/absence means OFF and any non-zero value means ON.
The raw NX value remains preserved in the source document; this SSC projection
only promises the observable autoplay state supported by the target.
"""

from __future__ import annotations

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
from stepnx.exporters.ssc_style_labels import (
    _beat_at_split,
    _named_tail_routes,
    _route_from_name,
)

_AUTOPLAY_ID = 999
_AUTOPLAY_EVENT_DELAY_BEATS = 0.25


@dataclass(frozen=True, slots=True)
class _AutoplayEvent:
    beat: float
    enabled: bool

    @property
    def label(self) -> str:
        return "AUTOPLAYON" if self.enabled else "AUTOPLAYOFF"


def _block_autoplay(block) -> bool:
    """Return the last-value-wins autoplay state for one active NX block."""

    value = 0
    for entry in block.divisions:
        if int(entry.meta_id) == _AUTOPLAY_ID:
            value = int(entry.value)
    return value != 0


def _autoplay_events(snapshot: AuthoringSnapshot) -> tuple[_AutoplayEvent, ...]:
    """Compile effective autoplay state changes on the SSC virtual beat axis."""

    beat = 0.0
    previous = False
    result: list[_AutoplayEvent] = []
    for split in snapshot.splits:
        if not split.blocks:
            continue
        block = snapshot.active_block(split.stable_id)
        enabled = _block_autoplay(block)
        if enabled != previous:
            result.append(
                _AutoplayEvent(
                    beat + _AUTOPLAY_EVENT_DELAY_BEATS,
                    enabled,
                )
            )
            previous = enabled
        beat += block.row_count / LINE_BEAT_SPLIT
    return tuple(result)


def _event_value_at(events: tuple[_AutoplayEvent, ...], beat: float) -> bool:
    value = False
    for event in events:
        if event.beat > beat:
            break
        value = event.enabled
    return value


def _normalize_events(events: list[_AutoplayEvent]) -> tuple[_AutoplayEvent, ...]:
    ordered = sorted(events, key=lambda event: event.beat)
    result: list[_AutoplayEvent] = []
    for event in ordered:
        if result and abs(result[-1].beat - event.beat) < 1e-9:
            result[-1] = event
            continue
        if result and result[-1].enabled == event.enabled:
            continue
        result.append(event)
    return tuple(result)


def _hybrid_tail_events(
    helper: AuthoringSnapshot,
    routed: AuthoringSnapshot,
    decision: SscDivisionDecision,
) -> tuple[_AutoplayEvent, ...]:
    """Combine a random helper prefix with a late named Division route suffix."""

    boundary = _beat_at_split(helper, decision.split_index)
    helper_events = _autoplay_events(helper)
    routed_events = _autoplay_events(routed)

    prefix = [event for event in helper_events if event.beat < boundary]
    before = _event_value_at(helper_events, boundary)
    after = _event_value_at(routed_events, boundary)
    suffix: list[_AutoplayEvent] = []
    if after != before:
        # The route has already established its state at the handoff. Apply it at
        # the boundary itself rather than adding another +0.25 beat delay.
        suffix.append(_AutoplayEvent(boundary, after))
    suffix.extend(event for event in routed_events if event.beat > boundary)
    return _normalize_events(prefix + suffix)


def _snapshot_events_for_chart(
    report: SscRandomExportReport,
    bundle: SscDivisionRuntime,
    chart_index: int,
    decisions: tuple[SscDivisionDecision, ...],
    tail_routes: dict[str, int],
) -> tuple[_AutoplayEvent, ...]:
    item = bundle.charts[chart_index]
    name = bundle.chart_names[chart_index]
    route_index = _route_from_name(name)

    if item.helper_index is not None:
        helper = report.program.helper_snapshots[item.helper_index]
        if route_index is not None and decisions:
            routed = _snapshot_for_route(helper, decisions, route_index)
            return _autoplay_events(routed)

        tail_route = tail_routes.get(name)
        if tail_route is not None and len(decisions) == 1:
            routed = _snapshot_for_route(
                report.program.base_snapshot,
                decisions,
                tail_route,
            )
            return _hybrid_tail_events(helper, routed, decisions[0])
        return _autoplay_events(helper)

    if route_index is not None and decisions:
        routed = _snapshot_for_route(report.program.base_snapshot, decisions, route_index)
        return _autoplay_events(routed)
    return _autoplay_events(report.program.base_snapshot)


def autoplay_label_tables(
    report: SscRandomExportReport,
    bundle: SscDivisionRuntime,
) -> tuple[tuple[str, ...], ...]:
    """Build per-Steps AUTOPLAYON/OFF label tables for one runtime bundle."""

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


def _label_beat(entry: str) -> float:
    raw, separator, _label = entry.partition("=")
    if not separator:
        raise SscExportError(f"generated control label has no beat separator: {entry!r}")
    try:
        return float(raw)
    except ValueError as exc:
        raise SscExportError(f"generated control label has invalid beat: {entry!r}") from exc


def merge_control_label_tables(
    *groups: tuple[tuple[str, ...], ...],
) -> tuple[tuple[str, ...], ...]:
    """Merge independently compiled reserved-label families by beat.

    Group order is the tie-breaker. The runtime currently passes OFFSET labels
    first and AUTOPLAY labels second, matching EF1329 when both features occur
    in the same neighborhood.
    """

    active = tuple(group for group in groups if group)
    if not active:
        return ()
    count = len(active[0])
    if any(len(group) != count for group in active[1:]):
        raise SscExportError("generated control-label table counts do not match")

    merged: list[tuple[str, ...]] = []
    for chart_index in range(count):
        indexed: list[tuple[float, int, int, str]] = []
        for group_index, group in enumerate(active):
            for entry_index, entry in enumerate(group[chart_index]):
                indexed.append((_label_beat(entry), group_index, entry_index, entry))
        indexed.sort(key=lambda item: (item[0], item[1], item[2]))

        unique: list[str] = []
        seen: set[str] = set()
        for _beat, _group_index, _entry_index, entry in indexed:
            if entry not in seen:
                unique.append(entry)
                seen.add(entry)
        merged.append(tuple(unique))
    return tuple(merged)


__all__ = ["autoplay_label_tables", "merge_control_label_tables"]
