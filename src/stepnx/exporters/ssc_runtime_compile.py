"""Runtime-faithful pre-compilation for the XSanity SSC exporter.

NXA and Fiesta 2 both evaluate every block of an ordered Split, collect the
blocks whose Division predicates pass, and select the *last* matching candidate
when bit 0x80 is clear.  A surprisingly important legacy case is therefore:

    raw_select == 0x00 + several blocks + no Division metadata

Every block matches, so the original games deterministically execute the last
block.  These are not XSanity ``#DIVISION`` decisions and must not be exported
as conditional routes.  EF334 contains several such Splits.

This module applies that runtime rule to the authoring snapshot before the
existing random compiler and SSC projection run. It also resolves header-level
SSC semantics that the low-level writer intentionally does not own: noteskin
slots 900..905 and mission difficulty 1101.
"""

from __future__ import annotations

from dataclasses import replace

from stepnx.authoring.random_program import RandomCompileError, compile_random_program
from stepnx.authoring.random_state import RandomPoolPolicy
from stepnx.authoring.snapshot import AuthoringSnapshot, create_authoring_snapshot
from stepnx.core.model import NX20Document
from stepnx.exporters.ssc import SscExportError
from stepnx.exporters.ssc_header_semantics import (
    apply_header_preloads,
    header_noteskin_context,
    resolved_meter,
)
from stepnx.exporters.ssc_random import (
    SscLabeledChart,
    SscRandomExportReport,
    _DEFAULT_XSANITY_RANDOM_POLICY,
    _LABEL_DIVISION,
    _LABEL_NORMAL,
    _default_description,
    _inject_returns,
    _inject_wraps,
    _merge_diagnostics,
    _plan_windows,
    _project,
    _semantic_diagnostics,
    _sparsify_helper,
    _validate_row_geometry,
)


def resolve_ordered_unconditional_snapshot(snapshot: AuthoringSnapshot) -> AuthoringSnapshot:
    """Collapse unconditional ordered multi-block Splits to their runtime winner.

    Reverse engineering of both ``piu_nxa`` and ``piuf2_160_io`` shows the same
    rule: after condition evaluation, a non-random selector chooses
    ``candidate[count - 1]``. With selector 0x00 and no per-block Division
    metadata, every block is a candidate, hence the final block wins.

    Only that proven shape is collapsed here. Banked selectors and Splits with
    actual Division metadata keep their full topology for the dedicated
    Division compiler.
    """

    choices = dict(snapshot.active_blocks)
    splits = []
    changed = False

    for split in snapshot.splits:
        if (
            split.raw_select == 0x00
            and len(split.blocks) > 1
            and all(not block.divisions for block in split.blocks)
        ):
            winner = split.blocks[-1]
            split = replace(split, blocks=(winner,))
            choices[split.stable_id] = winner.stable_id
            changed = True
        splits.append(split)

    if not changed:
        return snapshot

    split_tuple = tuple(splits)
    active_blocks = tuple(
        (split.stable_id, choices[split.stable_id])
        for split in split_tuple
        if split.blocks
    )
    return replace(snapshot, splits=split_tuple, active_blocks=active_blocks)


def _project_runtime(
    document: NX20Document,
    snapshot: AuthoringSnapshot,
    *,
    description: str,
    difficulty: str | None,
    meter: int | None,
    credit: str | None,
):
    """Project one snapshot with its header noteskin slot table active."""

    with header_noteskin_context(snapshot):
        chart, diagnostics = _project(
            document,
            snapshot,
            description=description,
            difficulty=difficulty,
            meter=meter,
            credit=credit,
        )
    return apply_header_preloads(chart, snapshot), diagnostics


def compile_ssc_export(
    document: NX20Document,
    *,
    description: str | None = None,
    difficulty: str | None = None,
    meter: int | None = None,
    credit: str | None = None,
    policy: RandomPoolPolicy = _DEFAULT_XSANITY_RANDOM_POLICY,
) -> SscRandomExportReport:
    """Compile one NX20 chart using the original game's ordered-block semantics."""

    snapshot = resolve_ordered_unconditional_snapshot(create_authoring_snapshot(document))
    try:
        program = compile_random_program(snapshot, policy)
    except (RandomCompileError, ValueError) as exc:
        raise SscExportError(str(exc)) from exc

    _validate_row_geometry(program)
    windows = _plan_windows(program)
    base_description = description or _default_description(document)
    target_meter = resolved_meter(snapshot, meter)

    base, base_diagnostics = _project_runtime(
        document,
        program.base_snapshot,
        description=base_description,
        difficulty=difficulty,
        meter=target_meter,
        credit=credit,
    )
    base, wrap_rows = _inject_wraps(base, program, windows)

    labeled: list[SscLabeledChart] = [SscLabeledChart(base, _LABEL_NORMAL)]
    diagnostic_groups = [base_diagnostics]
    for helper_index, helper_snapshot in enumerate(program.helper_snapshots):
        helper_description = f"{base_description} [StepNX random {helper_index + 1}]"
        helper, helper_diagnostics = _project_runtime(
            document,
            helper_snapshot,
            description=helper_description,
            difficulty="Edit",
            meter=target_meter,
            credit=credit,
        )
        helper, return_rows = _inject_returns(
            helper,
            helper_snapshot,
            windows,
            wrap_rows,
        )
        helper = _sparsify_helper(
            helper,
            columns=helper_snapshot.columns,
            wrap_rows=wrap_rows,
            return_rows=return_rows,
        )
        labeled.append(SscLabeledChart(helper, _LABEL_DIVISION, helper_index))
        diagnostic_groups.append(helper_diagnostics)

    diagnostic_groups.append(_semantic_diagnostics(program, windows))
    return SscRandomExportReport(
        program=program,
        charts=tuple(labeled),
        diagnostics=_merge_diagnostics(diagnostic_groups),
        windows=windows,
    )


__all__ = ["compile_ssc_export", "resolve_ordered_unconditional_snapshot"]
