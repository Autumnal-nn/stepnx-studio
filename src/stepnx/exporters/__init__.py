"""Projections from the canonical NX20 model to foreign chart formats."""

from dataclasses import replace

from stepnx.exporters.ssc import (
    SscChart,
    SscDiagnostic,
    SscExportError,
    SscExportReport,
    SscSongInfo,
    difficulty_for_name,
    export_chart,
    render_extension,
    render_simfile,
)
from stepnx.exporters.ssc_division import (
    SscDivisionCondition,
    SscDivisionDecision,
    SscDivisionRuntime,
    compile_division_decisions,
)
from stepnx.exporters.ssc_random import (
    SscLabeledChart,
    SscRandomExportReport,
    SscRandomWindow,
    compile_ssc_export as _compile_ssc_export,
)
from stepnx.exporters.ssc_xsanity_segmented import (
    render_compiled_reports,
    render_compiled_simfile,
)


def compile_ssc_export(*args, **kwargs) -> SscRandomExportReport:
    """Compile the public XSanity export plan.

    The random planner historically reported non-random alternate blocks as
    ``ssc.conditional-branches-pending``.  Those branches are now consumed by
    the native Division renderer, so the public report removes that obsolete
    diagnostic. Unsupported Division grammars still fail explicitly when the
    runtime projection is rendered/preflighted instead of being flattened.
    """

    report = _compile_ssc_export(*args, **kwargs)
    diagnostics = tuple(
        item
        for item in report.diagnostics
        if item.code != "ssc.conditional-branches-pending"
    )
    if diagnostics == report.diagnostics:
        return report
    return replace(report, diagnostics=diagnostics)


__all__ = [
    "SscChart",
    "SscDiagnostic",
    "SscExportError",
    "SscExportReport",
    "SscSongInfo",
    "SscLabeledChart",
    "SscRandomWindow",
    "SscRandomExportReport",
    "SscDivisionCondition",
    "SscDivisionDecision",
    "SscDivisionRuntime",
    "difficulty_for_name",
    "export_chart",
    "render_extension",
    "render_simfile",
    "compile_ssc_export",
    "compile_division_decisions",
    "render_compiled_simfile",
    "render_compiled_reports",
]
