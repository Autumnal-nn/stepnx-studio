from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from stepnx.authoring.semantics import ConditionClause, DivisionTrigger, project_routes
from stepnx.core.model import NX20Document, Row
from stepnx.core.validation import Severity, validate
from stepnx.preview.modifiers import EffectiveModifier, StepParam, apply_step_params


@dataclass(frozen=True, slots=True)
class PreviewBlock:
    stable_id: int
    split_id: int
    index: int
    start_time_ms: float
    bpm: float
    scroll: float
    offset_or_delay_ms: float
    speed_or_freeze: float
    beat_split: int
    beat_measure: int
    smooth_speed: int
    rows: Sequence[Row]
    conditions: tuple[ConditionClause, ...]
    triggers: tuple[DivisionTrigger, ...]
    brain_question_count: int
    step_params: tuple[StepParam, ...] = ()


@dataclass(frozen=True, slots=True)
class PreviewSplit:
    stable_id: int
    index: int
    raw_select: int
    random_at_start: bool
    random_at_trigger: bool
    force_select: bool
    group: int
    blocks: tuple[PreviewBlock, ...]
    step_params: tuple[StepParam, ...] = ()

    def block(self, stable_id: int) -> PreviewBlock:
        for block in self.blocks:
            if block.stable_id == stable_id:
                return block
        raise KeyError(stable_id)


@dataclass(frozen=True, slots=True)
class PreviewDiagnostic:
    severity: Severity
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class PreviewSnapshot:
    """Read-only gameplay projection with every route alternative retained."""

    document_stable_id: int
    source_name: str | None
    profile: str
    start_column: int
    columns: int
    splits: tuple[PreviewSplit, ...]
    diagnostics: tuple[PreviewDiagnostic, ...]
    header_step_params: tuple[StepParam, ...] = ()

    def split(self, stable_id: int) -> PreviewSplit:
        for split in self.splits:
            if split.stable_id == stable_id:
                return split
        raise KeyError(stable_id)

    def effective_modifier(
        self, base: EffectiveModifier | None = None
    ) -> EffectiveModifier:
        """Apply Header StepParams with profile-gated Metadata 32 extensions."""

        return apply_step_params(
            self.header_step_params,
            base,
            allow_mid=self.profile == "nxa-step5-patched",
        )


def _step_params(entries) -> tuple[StepParam, ...]:
    return tuple(
        StepParam(int(entry.meta_id.value), int(entry.value.value)) for entry in entries
    )


def create_preview_snapshot(document: NX20Document) -> PreviewSnapshot:
    report = validate(document)
    diagnostics = [
        PreviewDiagnostic(issue.severity, issue.code, issue.path, issue.message)
        for issue in report.issues
    ]
    if document.effective_lightmap:
        diagnostics.append(
            PreviewDiagnostic(
                Severity.ERROR,
                "preview.lightmap",
                "role",
                "Lightmap documents do not contain a playable note route",
            )
        )

    projected = {route.split_id: route for route in project_routes(document)}
    splits: list[PreviewSplit] = []
    for split_index, split in enumerate(document.splits):
        route = projected.get(split.stable_id)
        blocks: list[PreviewBlock] = []
        for block_index, block in enumerate(split.blocks):
            branch = None if route is None else route.branches[block_index]
            question_count = next(
                (
                    int(entry.value.value)
                    for entry in reversed(block.divisions)
                    if int(entry.meta_id.value) == 23
                ),
                0,
            )
            blocks.append(
                PreviewBlock(
                    block.stable_id,
                    split.stable_id,
                    block_index,
                    float(block.start_time.value),
                    float(block.bpm.value),
                    float(block.scroll.value),
                    float(block.offset_or_delay.value),
                    float(block.speed_or_freeze.value),
                    int(block.beat_split.value),
                    int(block.beat_measure.value),
                    int(block.smooth_speed.value),
                    block.rows,
                    () if branch is None else branch.conditions,
                    () if branch is None else branch.triggers,
                    max(0, question_count),
                    _step_params(block.divisions),
                )
            )
        raw = int(split.raw_select.value)
        splits.append(
            PreviewSplit(
                split.stable_id,
                split_index,
                raw,
                bool(raw & 0x80),
                bool(raw & 0x40),
                bool(raw & 0x20),
                raw & 0x1F,
                tuple(blocks),
                _step_params(split.metadata),
            )
        )
    return PreviewSnapshot(
        document.stable_id,
        document.source_name,
        document.profile,
        int(document.start_column.value),
        int(document.columns.value),
        tuple(splits),
        tuple(diagnostics),
        _step_params(document.header_metadata),
    )
