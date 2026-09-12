"""Projections from the canonical NX20 model to foreign chart formats."""

from dataclasses import replace

from stepnx.exporters.ssc import (
    UNKNOWN_NOTE_EMPTY,
    UNKNOWN_NOTE_ERROR,
    UNKNOWN_NOTE_MINE,
    UNKNOWN_NOTE_POLICIES,
    SscChart,
    SscDiagnostic,
    SscExportError,
    SscExportReport,
    SscRouteChoice,
    SscSongInfo,
    difficulty_for_name,
    escape_tag_value,
    export_chart,
    render_extension,
    render_simfile,
)
from stepnx.exporters.ssc_item_semantics import install_item_semantics

# Keep the pre-PR public convenience property for callers that still use it.
# It is only a shorthand for an empty low-level diagnostic report, not a claim
# that NX -> SSC can be globally lossless.
if not hasattr(SscExportReport, "lossless"):
    SscExportReport.lossless = property(lambda self: not self.diagnostics)

# PR #27's original low-level table stopped at item 21. Exact Fiesta 2/Sanity
# pairs prove the remaining official item symbols (22=Nuke -> n, 23=HyPot -> t).
install_item_semantics()

from stepnx.exporters.ssc_division import (
    SscDivisionCondition,
    SscDivisionDecision,
    SscDivisionRuntime,
    compile_division_decisions,
)
import stepnx.exporters.ssc_random as _ssc_random
from stepnx.exporters.ssc_random import (
    SscLabeledChart,
    SscRandomExportReport,
    SscRandomWindow,
)

# The updated PR #27 low-level writer now reports metadata/conditions/Brain
# Shower that a *single flattened route* cannot carry. StepNX's runtime compiler
# sits above that layer and does carry a proven subset of those semantics through
# DIVISION/helpers. Suppress only those low-level ownership diagnostics while
# compiling the richer runtime projection; direct export_chart() still reports
# them normally.
_runtime_owned_lowlevel_codes = {
    "ssc.metadata-not-carried",
    "ssc.conditions-not-carried",
    "ssc.brain-shower-not-carried",
}
_original_random_project = _ssc_random._project


def _runtime_project(*args, **kwargs):
    chart, diagnostics = _original_random_project(*args, **kwargs)
    return chart, tuple(
        item for item in diagnostics if item.code not in _runtime_owned_lowlevel_codes
    )


_ssc_random._project = _runtime_project


import stepnx.exporters.ssc_header_semantics as _ssc_header_semantics

# Header-level noteskin projection temporarily replaces the low-level cell
# renderer. Keep PR #27's unknown-note policy active inside that context too;
# otherwise runtime compilation would silently revive the old mine fallback.
_original_header_render_cell = _ssc_header_semantics._render_cell_with_header


def _header_render_cell_with_unknown_policy(configured, state, raw, brain_char, where):
    kind = raw[0]
    if (
        kind
        and raw[3] != 0xC0
        and kind != 0x42
        and kind not in _ssc_header_semantics.ssc._NOTE_TABLE
    ):
        split_index, block_index, row_index, lane = where
        if state.unknown_notes == _ssc_header_semantics.ssc.UNKNOWN_NOTE_ERROR:
            raise _ssc_header_semantics.ssc.SscExportError(
                f"note byte 0x{kind:02X} at Split {split_index + 1}, Div "
                f"{block_index + 1}, row {row_index}, lane {lane + 1} has no "
                "XSanity equivalent; pass unknown_notes to choose a fallback"
            )
        fallback = (
            _ssc_header_semantics.ssc._MINE_CHAR
            if state.unknown_notes == _ssc_header_semantics.ssc.UNKNOWN_NOTE_MINE
            else "0"
        )
        state.note(
            "ssc.unknown-note",
            f"note byte 0x{kind:02X} has no XSanity equivalent and is written as "
            + ("a mine" if fallback == _ssc_header_semantics.ssc._MINE_CHAR else "an empty lane"),
            *where,
        )
        return fallback
    return _original_header_render_cell(configured, state, raw, brain_char, where)


_ssc_header_semantics._render_cell_with_header = _header_render_cell_with_unknown_policy

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
    "UNKNOWN_NOTE_EMPTY",
    "UNKNOWN_NOTE_ERROR",
    "UNKNOWN_NOTE_MINE",
    "UNKNOWN_NOTE_POLICIES",
    "SscChart",
    "SscDiagnostic",
    "SscExportError",
    "SscExportReport",
    "SscRouteChoice",
    "SscSongInfo",
    "SscLabeledChart",
    "SscRandomWindow",
    "SscRandomExportReport",
    "SscDivisionCondition",
    "SscDivisionDecision",
    "SscDivisionRuntime",
    "difficulty_for_name",
    "escape_tag_value",
    "export_chart",
    "render_extension",
    "render_simfile",
    "compile_ssc_export",
    "compile_division_decisions",
    "render_compiled_simfile",
    "render_compiled_reports",
]
