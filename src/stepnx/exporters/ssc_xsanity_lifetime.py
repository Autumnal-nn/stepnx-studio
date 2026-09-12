"""Runtime renderer that reuses dead random helpers for tail Division routes."""

from __future__ import annotations

from stepnx.exporters.ssc import SscExportError, SscSongInfo, render_simfile
from stepnx.exporters.ssc_division import inject_division_tables
from stepnx.exporters.ssc_division_lifetime import (
    materialize_division_routes_lifetime_aware,
)
from stepnx.exporters.ssc_random import SscRandomExportReport
from stepnx.exporters.ssc_xsanity import (
    _decorate_runtime_metadata,
    _validate_combined_random_pools,
)
from stepnx.exporters.ssc_xsanity_segmented import materialize_segmented_random


def render_compiled_simfile(report: SscRandomExportReport, song: SscSongInfo) -> str:
    """Render one report using random-state and Division lifetime analysis."""

    runtime = materialize_segmented_random(report)
    bundle = materialize_division_routes_lifetime_aware(
        report,
        runtime,
        prefix="STEPNX",
    )
    if not bundle.charts:
        raise SscExportError("a compiled simfile needs at least one chart")
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
    """Render several source charts using lifetime-aware route allocation."""

    frozen = tuple(reports)
    if not frozen:
        raise SscExportError("a combined simfile needs at least one source chart")
    _validate_combined_random_pools(frozen)

    bundles = tuple(
        materialize_division_routes_lifetime_aware(
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


__all__ = ["render_compiled_simfile", "render_compiled_reports"]
