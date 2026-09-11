"""Runtime-facing rendering for semantic XSanity SSC exports.

The semantic compiler in :mod:`stepnx.exporters.ssc_random` now owns helper
window planning, two-visual-beat Wrap lead, and sparse helper note payloads.
This module only applies the standalone XSanity metadata envelope that has been
validated against the working Sanity corpus.

Current evidence-driven rules:

* random helper pools require song-level ``#SPECIAL:LEVEL,RANDOM;``;
* generated ``LABELTYPE:DIVISION`` Steps receive a non-empty unique
  ``#CHARTNAME``;
* ``#TICKCOUNTS`` follows the writer's virtual row grid. The current projection
  maps one NX row to one SSC row and defines one SSC beat as
  ``LINE_BEAT_SPLIT`` rows, so the same tick count preserves one hold tick per
  source NX row after BPM rescaling.
"""

from __future__ import annotations

from stepnx.exporters.ssc import (
    LINE_BEAT_SPLIT,
    SscExportError,
    SscSongInfo,
    render_simfile,
)
from stepnx.exporters.ssc_random import SscLabeledChart, SscRandomExportReport

_CORPUS_VERSION_LINE = "#VERSION:0.83;"
_PR_VERSION_LINE = "#VERSION:0.83 xSanity;"
_RANDOM_SPECIAL_LINE = "#SPECIAL:LEVEL,RANDOM;"


def _chart_name(item: SscLabeledChart) -> str:
    if item.helper_index is None:
        return "STEPNX_BASE"
    return f"STEPNX_RANDOM_{item.helper_index + 1:04d}"


def _decorate_runtime_metadata(
    text: str,
    charts: tuple[SscLabeledChart, ...],
    *,
    random_mode: bool,
) -> str:
    """Add chart identity, random gate, labels, and hold tick tags used by XSanity."""

    output: list[str] = []
    chart_index = -1
    awaiting_description = False
    random_gate_present = _RANDOM_SPECIAL_LINE in text.splitlines()
    random_gate_inserted = random_gate_present

    for raw_line in text.splitlines():
        line = _CORPUS_VERSION_LINE if raw_line == _PR_VERSION_LINE else raw_line
        output.append(line)

        if random_mode and not random_gate_inserted and line.startswith("#TITLE:"):
            output.append(_RANDOM_SPECIAL_LINE)
            random_gate_inserted = True

        if line == "#NOTEDATA:;":
            chart_index += 1
            if chart_index >= len(charts):
                raise SscExportError(
                    "rendered simfile contains more chart sections than the compiled report"
                )
            output.append(f"#CHARTNAME:{_chart_name(charts[chart_index])};")
            awaiting_description = True
            continue

        if awaiting_description and line.startswith("#DESCRIPTION:"):
            item = charts[chart_index]
            output.append(f"#LABELTYPE:{item.label_type};")
            output.append(f"#TICKCOUNTS:0.000000={LINE_BEAT_SPLIT};")
            awaiting_description = False

    if random_mode and not random_gate_inserted:
        raise SscExportError(
            "rendered simfile is missing #TITLE, so the XSanity random gate cannot be inserted"
        )
    if chart_index + 1 != len(charts):
        raise SscExportError(
            f"rendered simfile contains {chart_index + 1} chart sections but "
            f"{len(charts)} were expected"
        )
    if awaiting_description:
        raise SscExportError("rendered simfile chart section is missing #DESCRIPTION")
    return "\n".join(output) + "\n"


def render_compiled_simfile(report: SscRandomExportReport, song: SscSongInfo) -> str:
    """Render a standalone runtime-oriented XSanity SSC from a compiled report."""

    charts = tuple(report.charts)
    if not charts:
        raise SscExportError("a compiled simfile needs at least one chart")
    text = render_simfile([item.chart for item in charts], song)
    return _decorate_runtime_metadata(text, charts, random_mode=report.helper_count > 0)


__all__ = ["render_compiled_simfile"]
