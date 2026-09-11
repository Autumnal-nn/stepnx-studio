"""Runtime-facing rendering for semantic XSanity SSC exports.

The random compiler in :mod:`stepnx.exporters.ssc_random` builds chart state and
control cells.  This module owns the standalone XSanity envelope that makes
those generated Steps discoverable by the runtime.

Two details here are intentionally corpus-driven rather than inherited from the
mechanical PR #27 writer:

* generated ``LABELTYPE:DIVISION`` Steps receive a non-empty, unique
  ``#CHARTNAME``.  The Sanity corpus does this consistently for Division helper
  Steps and the runtime test of a 20-way pool showed that omitting that identity
  leaves the controller on its base/first route;
* ``#TICKCOUNTS`` follows the writer's virtual row grid.  The current mechanical
  projection maps one NX row to one SSC row and defines one SSC beat as
  ``LINE_BEAT_SPLIT`` rows, so using the same value as the tick count preserves
  one hold tick per source NX row even when BPM is rescaled.

This does not make ``LINE_BEAT_SPLIT == 8`` a property of SSC.  It is merely the
coordinate system of the current writer.  A later rational/adaptive timeline
compiler can replace both the grid and this tick-count projection together.
"""

from __future__ import annotations

from stepnx.exporters.ssc import LINE_BEAT_SPLIT, SscExportError, SscSongInfo, render_simfile
from stepnx.exporters.ssc_random import SscLabeledChart, SscRandomExportReport

_CORPUS_VERSION_LINE = "#VERSION:0.83;"
_PR_VERSION_LINE = "#VERSION:0.83 xSanity;"


def _chart_name(item: SscLabeledChart) -> str:
    if item.helper_index is None:
        return "STEPNX_BASE"
    return f"STEPNX_RANDOM_{item.helper_index + 1:03d}"


def _decorate_runtime_metadata(
    text: str,
    charts: tuple[SscLabeledChart, ...],
) -> str:
    """Add the chart identity/label/tick tags used by working XSanity SSCs."""

    output: list[str] = []
    chart_index = -1
    awaiting_description = False

    for raw_line in text.splitlines():
        line = _CORPUS_VERSION_LINE if raw_line == _PR_VERSION_LINE else raw_line
        output.append(line)

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

    if chart_index + 1 != len(charts):
        raise SscExportError(
            f"rendered simfile contains {chart_index + 1} chart sections but "
            f"{len(charts)} were expected"
        )
    if awaiting_description:
        raise SscExportError("rendered simfile chart section is missing #DESCRIPTION")
    return "\n".join(output) + "\n"


def render_compiled_simfile(report: SscRandomExportReport, song: SscSongInfo) -> str:
    """Render a standalone, runtime-oriented XSanity SSC from a compiled report."""

    charts = tuple(report.charts)
    if not charts:
        raise SscExportError("a compiled simfile needs at least one chart")
    text = render_simfile([item.chart for item in charts], song)
    return _decorate_runtime_metadata(text, charts)


__all__ = ["render_compiled_simfile"]
