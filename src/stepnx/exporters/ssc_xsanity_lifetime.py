"""Runtime renderer that reuses dead random helpers for tail Division routes.

The final rendering pass also normalizes the single-Decision layout against the
exact Fiesta EX -> Sanity pairs. In those files the initial/base Steps owns the
active ``#DIVISION`` table, alternate target Steps do not repeat that same event,
and the fallback is implicit: if no conditional entry matches, the engine keeps
its current Steps.

Runtime A/B testing established another non-obvious XSanity requirement: the
legacy Division parser is order-sensitive enough to crash when ``#DIVISION`` is
inserted near the beginning of a Steps section. The working corpus shape places
``#DIVISION`` only after the chart timing block (BPMS/STOPS/DELAYS/WARPS,
TICKCOUNTS/SCROLLS/SPEEDS). Keep that placement here rather than treating SSC
Steps tags as freely reorderable StepMania metadata.
"""

from __future__ import annotations

from dataclasses import replace

from stepnx.exporters.ssc import SscExportError, SscSongInfo, render_simfile
from stepnx.exporters.ssc_division import (
    SscDivisionRuntime,
    compile_division_decisions,
)
from stepnx.exporters.ssc_division_lifetime import (
    materialize_division_routes_lifetime_aware,
)
from stepnx.exporters.ssc_random import SscRandomExportReport
from stepnx.exporters.ssc_xsanity import (
    _decorate_runtime_metadata,
    _validate_combined_random_pools,
)
from stepnx.exporters.ssc_xsanity_segmented import materialize_segmented_random


def _single_decision_entries(entries: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize one native Division event to the official Sanity shape.

    Exact Fiesta EX pairs such as EF1225 omit the synthetic 0=0 fallback and
    order the common G/W family as WG, W, G. Fallback behavior is simply to
    remain on the current/base Steps.
    """

    conditioned = tuple(entry for entry in entries if not entry.startswith("0=0="))
    priority = {"WG": 0, "W": 1, "G": 2}
    return tuple(
        sorted(
            conditioned,
            key=lambda entry: (
                priority.get(entry.rsplit("=", 1)[-1], 100),
                entry,
            ),
        )
    )


def _normalize_single_decision_bundle(
    report: SscRandomExportReport,
    bundle: SscDivisionRuntime,
) -> SscDivisionRuntime:
    """Avoid recursively re-triggering a single Division on its target routes."""

    decisions = compile_division_decisions(report)
    if len(decisions) != 1 or not bundle.division_tables:
        return bundle

    tables = tuple(
        _single_decision_entries(table) if table else ()
        for table in bundle.division_tables
    )

    if report.helper_count <= 0:
        # Official one-decision mission files put the active table on STEP1/base
        # only. STEP2+ are named destinations and must not repeat the triggering
        # event after the runtime switches into them.
        source = tables[0] if tables else ()
        tables = (source,) + tuple(() for _ in tables[1:])

    return replace(bundle, division_tables=tables)


def _inject_division_tables_runtime_order(
    text: str,
    division_tables: tuple[tuple[str, ...], ...],
) -> str:
    """Insert XSanity Division metadata after each Steps timing block.

    A generated EF1225 file crashed XSanity when #DIVISION appeared immediately
    after #TICKCOUNTS near the top of the Steps section. Moving the exact same
    table after #SPEEDS made the file load successfully. The official StepPrime
    corpus also places Division after timing metadata. Preserve that order
    explicitly.

    When the simfile contains at least one active Division table, destination
    Steps receive empty ``#DIVISION``/``#SPECIALDIVISION`` tags at the same
    location. That mirrors the official route-stream envelope without repeating
    the triggering event.
    """

    if not any(division_tables):
        return text

    output: list[str] = []
    chart_index = -1
    inserted: set[int] = set()
    for line in text.splitlines():
        if line == "#NOTEDATA:;":
            chart_index += 1
        output.append(line)
        if not line.startswith("#SPEEDS:"):
            continue
        if chart_index < 0 or chart_index >= len(division_tables):
            raise SscExportError("Division table count does not match rendered chart sections")

        entries = division_tables[chart_index]
        if entries:
            output.append("#DIVISION:" + entries[0])
            output.extend("," + entry for entry in entries[1:])
            output.append(";")
        else:
            output.append("#DIVISION:;")
        output.append("#SPECIALDIVISION:;")
        inserted.add(chart_index)

    if chart_index + 1 != len(division_tables):
        raise SscExportError(
            f"rendered simfile contains {chart_index + 1} chart sections but "
            f"{len(division_tables)} Division table slots were expected"
        )
    missing = [index for index in range(len(division_tables)) if index not in inserted]
    if missing:
        raise SscExportError(
            "rendered simfile is missing #SPEEDS for Division chart section(s): "
            + ", ".join(str(index + 1) for index in missing)
        )
    return "\n".join(output) + "\n"


def _bundle(
    report: SscRandomExportReport,
    *,
    prefix: str,
) -> SscDivisionRuntime:
    runtime = materialize_segmented_random(report)
    bundle = materialize_division_routes_lifetime_aware(
        report,
        runtime,
        prefix=prefix,
    )
    return _normalize_single_decision_bundle(report, bundle)


def render_compiled_simfile(report: SscRandomExportReport, song: SscSongInfo) -> str:
    """Render one report using random-state and Division lifetime analysis."""

    bundle = _bundle(report, prefix="STEPNX")
    if not bundle.charts:
        raise SscExportError("a compiled simfile needs at least one chart")
    text = render_simfile([item.chart for item in bundle.charts], song)
    decorated = _decorate_runtime_metadata(
        text,
        bundle.charts,
        random_mode=report.helper_count > 0,
        chart_names=bundle.chart_names,
    )
    return _inject_division_tables_runtime_order(decorated, bundle.division_tables)


def render_compiled_reports(
    reports: tuple[SscRandomExportReport, ...] | list[SscRandomExportReport],
    song: SscSongInfo,
) -> str:
    """Render several source charts using lifetime-aware route allocation."""

    frozen = tuple(reports)
    if not frozen:
        raise SscExportError("a combined simfile needs at least one source chart")
    _validate_combined_random_pools(frozen)

    bundles = tuple(
        _bundle(report, prefix=f"STEPNX_{report_index:02d}")
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
    return _inject_division_tables_runtime_order(decorated, tables)


__all__ = ["render_compiled_simfile", "render_compiled_reports"]
