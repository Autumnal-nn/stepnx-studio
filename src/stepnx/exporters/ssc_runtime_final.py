"""Final XSanity runtime pass for the public SSC exporter.

This layer sits above the validated random/Division lifetime renderer. It adds
runtime-wide semantics that do not belong to the low-level note writer:
Random Skin / RSK and Division-200 playfield OFFSET control labels.
"""

from __future__ import annotations

from stepnx.exporters.ssc import SscExportError, SscSongInfo, render_simfile
from stepnx.exporters.ssc_random import SscRandomExportReport
from stepnx.exporters.ssc_random_skin import (
    add_random_skin_preloads,
    inject_random_skin_attacks,
    random_skin_flags,
    random_skin_projection_context,
)
from stepnx.exporters.ssc_style_labels import div200_label_tables, inject_steps_labels
from stepnx.exporters.ssc_xsanity import (
    _decorate_runtime_metadata,
    _validate_combined_random_pools,
)
from stepnx.exporters.ssc_xsanity_lifetime import (
    _bundle as _lifetime_bundle,
    _inject_division_tables_runtime_order,
)


def _bundle(report: SscRandomExportReport, *, prefix: str):
    snapshot = report.program.base_snapshot
    # Alternate Division routes are projected lazily inside the lifetime pass.
    # Keep Random Skin's diagnostic suppression active there too so direct 254
    # is recognized as a preserved runtime modifier, not a lossy projection.
    with random_skin_projection_context(snapshot):
        bundle = _lifetime_bundle(report, prefix=prefix)
    return add_random_skin_preloads(bundle, snapshot)


def render_compiled_simfile(report: SscRandomExportReport, song: SscSongInfo) -> str:
    """Render one report with random, Division, style and noteskin semantics."""

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
    divided = _inject_division_tables_runtime_order(decorated, bundle.division_tables)
    styled = inject_steps_labels(divided, div200_label_tables(report, bundle))
    return inject_random_skin_attacks(
        styled,
        random_skin_flags(report.program.base_snapshot, len(bundle.charts)),
    )


def render_compiled_reports(
    reports: tuple[SscRandomExportReport, ...] | list[SscRandomExportReport],
    song: SscSongInfo,
) -> str:
    """Render several source charts while keeping per-source runtime ownership."""

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
    divided = _inject_division_tables_runtime_order(decorated, tables)

    style_tables = tuple(
        table
        for report, bundle in zip(frozen, bundles, strict=True)
        for table in div200_label_tables(report, bundle)
    )
    styled = inject_steps_labels(divided, style_tables)

    flags = tuple(
        flag
        for report, bundle in zip(frozen, bundles, strict=True)
        for flag in random_skin_flags(report.program.base_snapshot, len(bundle.charts))
    )
    return inject_random_skin_attacks(styled, flags)


__all__ = ["render_compiled_simfile", "render_compiled_reports"]
