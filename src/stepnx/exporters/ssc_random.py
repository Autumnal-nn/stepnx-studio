"""Compile NX20 random branches into XSanity LABELTYPE:DIVISION helpers.

The low-level :mod:`stepnx.exporters.ssc` writer serializes one already-
materialized authoring snapshot.  This module is the semantic layer above it:
it compiles NX ``0x80``/``0x8n``/``0x4n`` random state into XSanity Wrap
(``T``) and Wrap0 (``O``) controls plus helper ``#NOTEDATA`` sections.

The first implementation deliberately rejects random structures whose helper
identity cannot represent the NX state safely.  Failing loudly is preferable
to flattening a bank follower or silently dropping an outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePath

from stepnx.authoring.random_program import (
    CompiledRandomProgram,
    RandomCompileError,
    compile_random_program,
)
from stepnx.authoring.random_state import RandomPoolPolicy
from stepnx.authoring.snapshot import AuthoringSnapshot, create_authoring_snapshot
from stepnx.core.model import NX20Document
from stepnx.exporters.ssc import (
    LINES_PER_MEASURE,
    LINE_BEAT_SPLIT,
    SscChart,
    SscDiagnostic,
    SscExportError,
    SscSongInfo,
    export_chart,
    render_simfile,
)

_LABEL_NORMAL = "NORMAL"
_LABEL_DIVISION = "DIVISION"
_WRAP = "T"
_RETURN = "O"
_ALT_DROPPED = "ssc.alternate-branches-dropped"


@dataclass(frozen=True, slots=True)
class SscLabeledChart:
    """One generated SSC chart and the LABELTYPE used by XSanity."""

    chart: SscChart
    label_type: str
    helper_index: int | None = None


@dataclass(frozen=True, slots=True)
class SscRandomExportReport:
    """A base chart, its Wrap helpers, and semantic conversion diagnostics."""

    program: CompiledRandomProgram
    charts: tuple[SscLabeledChart, ...]
    diagnostics: tuple[SscDiagnostic, ...]

    @property
    def helper_count(self) -> int:
        return self.program.helper_count

    @property
    def exact_probabilities(self) -> bool:
        pool = self.program.pool
        return pool.helper_count == pool.exact_helper_count

    @property
    def max_probability_error(self) -> float:
        return self.program.pool.max_probability_error


@dataclass(frozen=True, slots=True)
class _RandomRegion:
    random_split_index: int
    return_split_index: int
    bank_id: int


def _default_description(document: NX20Document) -> str:
    source_name = document.source_name
    if source_name:
        return PurePath(source_name).name
    return "chart.nx"


def _regions(program: CompiledRandomProgram) -> tuple[_RandomRegion, ...]:
    analysis = program.analysis
    episodes = {episode.store_split_index: episode for episode in analysis.bank_episodes}
    result: list[_RandomRegion] = []
    for split_index in analysis.random_split_indices:
        selector = analysis.selectors[split_index]
        if selector.stores_bank:
            episode = episodes[split_index]
            result.append(
                _RandomRegion(split_index, episode.last_use_split_index, selector.bank_id)
            )
        else:
            result.append(_RandomRegion(split_index, split_index, 0))
    return tuple(result)


def _validate_row_geometry(program: CompiledRandomProgram) -> None:
    """Keep T/O boundaries on the same logical row grid in every helper.

    XSanity can carry branch-specific timing inside a helper, but a rejoin after
    alternatives with different row counts needs an explicit beat/time mapping.
    That mapping is not implemented yet, so reject it rather than guessing.
    """

    relevant: set[int] = set(program.analysis.random_split_indices)
    for episode in program.analysis.bank_episodes:
        relevant.update(episode.follower_split_indices)

    for split_index in sorted(relevant):
        split = program.base_snapshot.splits[split_index]
        row_counts = {block.row_count for block in split.blocks}
        if len(row_counts) > 1:
            raise SscExportError(
                f"random split {split_index} has branch row counts {sorted(row_counts)}; "
                "safe Wrap/Wrap0 rejoin for variable-length alternatives is not implemented"
            )


def _split_bounds(snapshot: AuthoringSnapshot) -> dict[int, tuple[int, int]]:
    row = 0
    bounds: dict[int, tuple[int, int]] = {}
    for split_index, split in enumerate(snapshot.splits):
        if not split.blocks:
            continue
        block = snapshot.active_block(split.stable_id)
        start = row
        row += block.row_count
        bounds[split_index] = (start, row)
    return bounds


def _split_cells(line: str, columns: int) -> list[str]:
    cells: list[str] = []
    index = 0
    while index < len(line):
        if line[index] == "{":
            end = line.find("}", index + 1)
            if end < 0:
                raise SscExportError(f"generated SSC row has an unterminated cell token: {line!r}")
            cells.append(line[index : end + 1])
            index = end + 1
        else:
            cells.append(line[index])
            index += 1
    if len(cells) != columns:
        raise SscExportError(
            f"generated SSC row has {len(cells)} cells but chart declares {columns}: {line!r}"
        )
    return cells


def _dense_rows(notes: str, columns: int) -> list[str]:
    blank = "0" * columns
    stripped = notes.rstrip("\n")
    if not stripped:
        return []

    result: list[str] = []
    for measure in stripped.split(",\n"):
        rows = measure.splitlines()
        if rows == [blank]:
            result.extend([blank] * LINES_PER_MEASURE)
            continue
        if len(rows) != LINES_PER_MEASURE:
            raise SscExportError(
                "generated SSC measure has "
                f"{len(rows)} rows; expected {LINES_PER_MEASURE} or one collapsed blank row"
            )
        result.extend(rows)
    return result


def _measure_rows(rows: list[str], columns: int) -> str:
    blank = "0" * columns
    if len(rows) % LINES_PER_MEASURE:
        rows = list(rows) + [blank] * (LINES_PER_MEASURE - len(rows) % LINES_PER_MEASURE)

    parts: list[str] = []
    for start in range(0, len(rows), LINES_PER_MEASURE):
        measure = rows[start : start + LINES_PER_MEASURE]
        if all(row == blank for row in measure):
            parts.append(blank + "\n")
        else:
            parts.append("\n".join(measure) + "\n")
    return ",\n".join(parts)


def _inject(
    rows: list[str],
    columns: int,
    token: str,
    candidates,
    *,
    description: str,
) -> int:
    for row_index in candidates:
        if row_index < 0:
            continue
        while row_index >= len(rows):
            rows.append("0" * columns)
        cells = _split_cells(rows[row_index], columns)
        for lane, cell in enumerate(cells):
            if cell != "0":
                continue
            cells[lane] = token
            rows[row_index] = "".join(cells)
            return row_index
    raise SscExportError(description)


def _inject_wraps(chart: SscChart, program: CompiledRandomProgram) -> tuple[SscChart, tuple[int, ...]]:
    columns = program.base_snapshot.columns
    rows = _dense_rows(chart.notes, columns)
    bounds = _split_bounds(program.base_snapshot)
    regions = _regions(program)
    wrap_rows: list[int] = []
    previous_return_end = 0

    for region in regions:
        split_start, _ = bounds[region.random_split_index]
        latest = split_start - LINE_BEAT_SPLIT
        if latest < previous_return_end:
            raise SscExportError(
                f"random split {region.random_split_index} begins too soon after the previous "
                "random region to place Wrap at least one SSC beat before it"
            )
        row_index = _inject(
            rows,
            columns,
            _WRAP,
            range(latest, previous_return_end - 1, -1),
            description=(
                f"no empty lane is available before random split {region.random_split_index} "
                "for a Wrap control"
            ),
        )
        wrap_rows.append(row_index)
        previous_return_end = bounds[region.return_split_index][1]

    return replace(chart, notes=_measure_rows(rows, columns)), tuple(wrap_rows)


def _inject_returns(
    chart: SscChart,
    snapshot: AuthoringSnapshot,
    program: CompiledRandomProgram,
    wrap_rows: tuple[int, ...],
) -> SscChart:
    columns = snapshot.columns
    rows = _dense_rows(chart.notes, columns)
    bounds = _split_bounds(snapshot)
    regions = _regions(program)

    for index, region in enumerate(regions):
        _, return_end = bounds[region.return_split_index]
        next_wrap = wrap_rows[index + 1] if index + 1 < len(wrap_rows) else None
        if next_wrap is None:
            candidates = range(return_end, max(return_end + LINES_PER_MEASURE, len(rows)))
        else:
            if return_end >= next_wrap:
                raise SscExportError(
                    f"random region ending at split {region.return_split_index} overlaps the "
                    f"next Wrap row {next_wrap}; helper cannot safely rejoin the base chart"
                )
            candidates = range(return_end, next_wrap)

        _inject(
            rows,
            columns,
            _RETURN,
            candidates,
            description=(
                f"no empty lane is available after random region ending at split "
                f"{region.return_split_index} for a Wrap0 return"
            ),
        )

    return replace(chart, notes=_measure_rows(rows, columns))


def _correct_scrolls(snapshot: AuthoringSnapshot) -> str:
    """Use the corpus-confirmed NX -> XSanity scroll conversion.

    The PR #27 writer used the inverse BeatSplit factor.  That happens to give
    1.0 for the common NX scroll 0.125 at BeatSplit 8, but it is wrong for
    custom scroll values.  Corpus pairs establish ``SSC scroll = NX scroll * 8``.
    """

    position = 0.0
    entries: list[str] = []
    for split in snapshot.splits:
        if not split.blocks:
            continue
        block = snapshot.active_block(split.stable_id)
        entries.append(f"{position:g}={block.scroll * LINE_BEAT_SPLIT:g},")
        position += block.row_count / LINE_BEAT_SPLIT
    return "".join(entries)


def _project(
    document: NX20Document,
    snapshot: AuthoringSnapshot,
    *,
    description: str,
    difficulty: str | None,
    meter: int | None,
    credit: str | None,
) -> tuple[SscChart, tuple[SscDiagnostic, ...]]:
    report = export_chart(
        document,
        description=description,
        difficulty=difficulty,
        meter=meter,
        credit=credit,
        snapshot=snapshot,
    )
    chart = replace(report.chart, scrolls=_correct_scrolls(snapshot))
    diagnostics = tuple(item for item in report.diagnostics if item.code != _ALT_DROPPED)
    return chart, diagnostics


def _merge_diagnostics(groups: list[tuple[SscDiagnostic, ...]]) -> tuple[SscDiagnostic, ...]:
    order: list[tuple[str, str]] = []
    merged: dict[tuple[str, str], SscDiagnostic] = {}
    for group in groups:
        for item in group:
            key = (item.code, item.message)
            current = merged.get(key)
            if current is None:
                order.append(key)
                merged[key] = item
            else:
                merged[key] = replace(
                    current, occurrences=current.occurrences + item.occurrences
                )
    return tuple(merged[key] for key in order)


def _semantic_diagnostics(program: CompiledRandomProgram) -> tuple[SscDiagnostic, ...]:
    diagnostics: list[SscDiagnostic] = []
    handled = set(program.analysis.random_split_indices)
    for episode in program.analysis.bank_episodes:
        handled.update(episode.follower_split_indices)

    pending = [
        index
        for index, split in enumerate(program.base_snapshot.splits)
        if len(split.blocks) > 1 and index not in handled
    ]
    if pending:
        alternatives = sum(
            len(program.base_snapshot.splits[index].blocks) - 1 for index in pending
        )
        diagnostics.append(
            SscDiagnostic(
                "ssc.conditional-branches-pending",
                f"{alternatives} alternate branch(es) across {len(pending)} non-random split(s) "
                "still require #DIVISION compilation; the active block is exported for now",
                split_index=pending[0],
                occurrences=len(pending),
            )
        )

    pool = program.pool
    if pool.helper_count and pool.helper_count != pool.exact_helper_count:
        diagnostics.append(
            SscDiagnostic(
                "ssc.random-probability-approximation",
                f"exact random probabilities require {pool.exact_helper_count} helper states; "
                f"generated {pool.helper_count} with maximum per-outcome error "
                f"{pool.max_probability_error * 100:.3f} percentage points",
            )
        )
    return tuple(diagnostics)


def compile_ssc_export(
    document: NX20Document,
    *,
    description: str | None = None,
    difficulty: str | None = None,
    meter: int | None = None,
    credit: str | None = None,
    policy: RandomPoolPolicy = RandomPoolPolicy(),
) -> SscRandomExportReport:
    """Compile one NX20 chart into a base SSC chart plus random helper charts.

    Random NX selectors are preserved through XSanity ``T``/``O`` controls and
    ``LABELTYPE:DIVISION`` helper charts.  Non-random alternate blocks are not
    yet compiled into ``#DIVISION`` and are reported explicitly.
    """

    snapshot = create_authoring_snapshot(document)
    try:
        program = compile_random_program(snapshot, policy)
    except (RandomCompileError, ValueError) as exc:
        raise SscExportError(str(exc)) from exc

    _validate_row_geometry(program)
    base_description = description or _default_description(document)
    base, base_diagnostics = _project(
        document,
        program.base_snapshot,
        description=base_description,
        difficulty=difficulty,
        meter=meter,
        credit=credit,
    )
    base, wrap_rows = _inject_wraps(base, program)

    labeled: list[SscLabeledChart] = [SscLabeledChart(base, _LABEL_NORMAL)]
    diagnostic_groups: list[tuple[SscDiagnostic, ...]] = [base_diagnostics]
    for helper_index, helper_snapshot in enumerate(program.helper_snapshots):
        helper_description = f"{base_description} [StepNX random {helper_index + 1}]"
        helper, helper_diagnostics = _project(
            document,
            helper_snapshot,
            description=helper_description,
            difficulty="Edit",
            meter=meter,
            credit=credit,
        )
        helper = _inject_returns(helper, helper_snapshot, program, wrap_rows)
        labeled.append(SscLabeledChart(helper, _LABEL_DIVISION, helper_index))
        diagnostic_groups.append(helper_diagnostics)

    diagnostic_groups.append(_semantic_diagnostics(program))
    return SscRandomExportReport(
        program=program,
        charts=tuple(labeled),
        diagnostics=_merge_diagnostics(diagnostic_groups),
    )


def _with_labeltypes(text: str, labels: tuple[str, ...]) -> str:
    output: list[str] = []
    label_index = 0
    for line in text.splitlines():
        output.append(line)
        if not line.startswith("#DESCRIPTION:"):
            continue
        if label_index >= len(labels):
            raise SscExportError("rendered simfile contains more chart sections than expected")
        output.append(f"#LABELTYPE:{labels[label_index]};")
        label_index += 1
    if label_index != len(labels):
        raise SscExportError(
            f"rendered simfile contains {label_index} chart sections but {len(labels)} labels were expected"
        )
    return "\n".join(output) + "\n"


def render_compiled_simfile(report: SscRandomExportReport, song: SscSongInfo) -> str:
    """Render a standalone XSanity SSC including NORMAL/DIVISION labels."""

    charts = [item.chart for item in report.charts]
    labels = tuple(item.label_type for item in report.charts)
    return _with_labeltypes(render_simfile(charts, song), labels)


__all__ = [
    "SscLabeledChart",
    "SscRandomExportReport",
    "compile_ssc_export",
    "render_compiled_simfile",
]
