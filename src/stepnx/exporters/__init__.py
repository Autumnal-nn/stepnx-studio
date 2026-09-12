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
)
from stepnx.exporters.ssc_random_skin import random_skin_requested
from stepnx.exporters.ssc_runtime_compile import (
    compile_ssc_export as _compile_ssc_export,
)
from stepnx.exporters.ssc_runtime_final import (
    render_compiled_reports,
    render_compiled_simfile,
)


def compile_ssc_export(*args, **kwargs) -> SscRandomExportReport:
    """Compile the public XSanity export plan.

    The random planner historically reported non-random alternate blocks as
    ``ssc.conditional-branches-pending``. Those branches are now consumed by
    the native Division renderer, while unconditional ordered multi-block
    Splits are resolved using the original NXA/Fiesta 2 last-valid-block rule.
    Unsupported Division grammars still fail explicitly during runtime
    projection instead of being flattened silently.

    Direct noteskin 254 used to report ``ssc.random-noteskin-header`` because
    the low-level writer could not reproduce native Random Skin by itself. The
    final runtime renderer now maps both 254 and Header 19 / RSK to XSanity's
    real ``randomskin`` modifier, so that diagnostic is no longer a loss when
    the source actually requests Random Skin.
    """

    report = _compile_ssc_export(*args, **kwargs)
    ignored = {"ssc.conditional-branches-pending"}
    if random_skin_requested(report.program.base_snapshot):
        ignored.add("ssc.random-noteskin-header")
    diagnostics = tuple(item for item in report.diagnostics if item.code not in ignored)
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
