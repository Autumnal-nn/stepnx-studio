"""Runtime-facing rendering for semantic XSanity SSC exports.

The semantic compiler in :mod:`stepnx.exporters.ssc_random` owns helper-window
planning, two-visual-beat Wrap lead, and sparse helper note payloads. This module
applies the standalone XSanity metadata envelope and can combine several NX
charts from one song folder into one SSC.

Current evidence-driven rules:

* random helper pools require song-level ``#SPECIAL:LEVEL,RANDOM;``;
* generated ``LABELTYPE:DIVISION`` Steps receive a non-empty unique
  ``#CHARTNAME``;
* ``#TICKCOUNTS`` follows the writer's virtual row grid. The current projection
  maps one NX row to one SSC row and defines one SSC beat as
  ``LINE_BEAT_SPLIT`` rows, so the same tick count preserves one hold tick per
  source NX row after BPM rescaling;
* XSanity Wrap selects from the DIVISION pool of the same StepsType. Until a
  narrower runtime filter is proven, one combined SSC may therefore contain at
  most one random source chart for each StepsType. Non-random charts of that
  StepsType are safe because they remain LABELTYPE:NORMAL.
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


def _single_chart_name(item: SscLabeledChart) -> str:
    if item.helper_index is None:
        return "STEPNX_BASE"
    return f"STEPNX_RANDOM_{item.helper_index + 1:03d}"


def _combined_chart_names(
    reports: tuple[SscRandomExportReport, ...],
) -> tuple[str, ...]:
    names: list[str] = []
    for report_index, report in enumerate(reports, 1):
        prefix = f"STEPNX_{report_index:02d}"
        for item in report.charts:
            if item.helper_index is None:
                names.append(prefix + "_BASE")
            else:
                names.append(prefix + f"_RANDOM_{item.helper_index + 1:04d}")
    return tuple(names)


def _validate_combined_random_pools(
    reports: tuple[SscRandomExportReport, ...],
) -> None:
    random_by_type: dict[str, int] = {}
    for report in reports:
        if report.helper_count <= 0 or not report.charts:
            continue
        steps_type = report.charts[0].chart.steps_type
        random_by_type[steps_type] = random_by_type.get(steps_type, 0) + 1
    conflicts = sorted(steps_type for steps_type, count in random_by_type.items() if count > 1)
    if conflicts:
        raise SscExportError(
            "combined SSC contains more than one random chart for StepsType(s): "
            + ", ".join(conflicts)
            + "; XSanity T would see both DIVISION pools"
        )


def _decorate_runtime_metadata(
    text: str,
    charts: tuple[SscLabeledChart, ...],
    *,
    random_mode: bool,
    chart_names: tuple[str, ...] | None = None,
) -> str:
    """Add chart identity, random gate, labels, and hold tick tags used by XSanity."""

    if chart_names is None:
        chart_names = tuple(_single_chart_name(item) for item in charts)
    if len(chart_names) != len(charts):
        raise SscExportError("runtime chart-name count does not match chart count")

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
            output.append(f"#CHARTNAME:{chart_names[chart_index]};")
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
    """Render a standalone runtime-oriented XSanity SSC from one compiled report."""

    charts = tuple(report.charts)
    if not charts:
        raise SscExportError("a compiled simfile needs at least one chart")
    text = render_simfile([item.chart for item in charts], song)
    return _decorate_runtime_metadata(text, charts, random_mode=report.helper_count > 0)


def render_compiled_reports(
    reports: tuple[SscRandomExportReport, ...] | list[SscRandomExportReport],
    song: SscSongInfo,
) -> str:
    """Render several source charts from one song folder into one XSanity SSC.

    Random reports are intentionally limited to one per StepsType because T is
    known to select from the global DIVISION pool of that StepsType. This guard
    can be relaxed only after runtime evidence proves a narrower filter.
    """

    frozen = tuple(reports)
    if not frozen:
        raise SscExportError("a combined simfile needs at least one source chart")
    _validate_combined_random_pools(frozen)

    charts = tuple(item for report in frozen for item in report.charts)
    if not charts:
        raise SscExportError("a combined simfile needs at least one chart section")
    text = render_simfile([item.chart for item in charts], song)
    return _decorate_runtime_metadata(
        text,
        charts,
        random_mode=any(report.helper_count > 0 for report in frozen),
        chart_names=_combined_chart_names(frozen),
    )


__all__ = ["render_compiled_simfile", "render_compiled_reports"]
