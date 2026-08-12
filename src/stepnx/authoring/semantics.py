from __future__ import annotations

from dataclasses import dataclass

from stepnx.core.model import NoteRow, NX20Document, PackedNoteRow
from stepnx.core.profiles import (
    MetadataDefinition,
    MetadataScope,
    metadata_definition,
    unpack_u16_range,
)
from stepnx.core.validation import Severity, ValidationIssue, ValidationReport


@dataclass(frozen=True, slots=True)
class SemanticMetadata:
    stable_id: int
    scope: MetadataScope
    meta_id: int
    value: int
    definition: MetadataDefinition | None
    path: str

    @property
    def label(self) -> str:
        return (
            self.definition.label if self.definition else f"Unknown ID {self.meta_id}"
        )

    @property
    def display_value(self) -> str:
        return (
            self.definition.display_value(self.value)
            if self.definition
            else str(self.value)
        )


@dataclass(frozen=True, slots=True)
class ConditionClause:
    metadata_id: int
    metric: str
    minimum: int
    maximum: int
    source_id: int


@dataclass(frozen=True, slots=True)
class DivisionTrigger:
    row_index: int
    column: int
    division_id: int
    triggers: bool


@dataclass(frozen=True, slots=True)
class RouteBranch:
    block_id: int
    block_index: int
    conditions: tuple[ConditionClause, ...]
    triggers: tuple[DivisionTrigger, ...]


@dataclass(frozen=True, slots=True)
class SplitRoute:
    split_id: int
    split_index: int
    random_at_start: bool
    random_at_trigger: bool
    force_select: bool
    group: int
    branches: tuple[RouteBranch, ...]


@dataclass(frozen=True, slots=True)
class BrainShowerBlock:
    block_id: int
    opcode: int | None
    instruction_sprite: int | None
    question_count: int | None
    puzzle_delay: int | None
    result_hold_time: int | None
    answer_count: int | None
    variant: int | None
    preset: int | None
    correct_range: tuple[int, int] | None
    wrong_range: tuple[int, int] | None
    context_a: tuple[int, int] | None
    context_b: tuple[int, int] | None
    duplicate_ids: tuple[int, ...]
    unknown_ids: tuple[int, ...]


_BRAIN_SCALARS = {21, 22, 23, 24, 25, 26, 31, 34}
_BRAIN_RANGES = {11, 12, 32, 33}


def semantic_metadata(document: NX20Document) -> tuple[SemanticMetadata, ...]:
    result: list[SemanticMetadata] = []

    def append(entries, scope: MetadataScope, prefix: str) -> None:
        for index, entry in enumerate(entries):
            meta_id = int(entry.meta_id.value)
            result.append(
                SemanticMetadata(
                    entry.stable_id,
                    scope,
                    meta_id,
                    int(entry.value.value),
                    metadata_definition(document.profile, scope, meta_id),
                    f"{prefix}[{index}]",
                )
            )

    append(document.header_metadata, MetadataScope.HEADER, "header_metadata")
    for split_index, split in enumerate(document.splits):
        append(split.metadata, MetadataScope.SPLIT, f"splits[{split_index}].metadata")
        for block_index, block in enumerate(split.blocks):
            append(
                block.divisions,
                MetadataScope.DIVISION,
                f"splits[{split_index}].blocks[{block_index}].divisions",
            )
    return tuple(result)


def _triggers(block) -> tuple[DivisionTrigger, ...]:
    result: list[DivisionTrigger] = []
    for row_index, row in enumerate(block.rows):
        # Division triggers exist only in playable note cells.  Empty rows and
        # Lightmap rows are structural data and deliberately have no cells.
        if not isinstance(row, (NoteRow, PackedNoteRow)):
            continue
        for column, cell in enumerate(row.cells):
            if cell.note_type == 0x02:
                result.append(
                    DivisionTrigger(
                        row_index, column, cell.raw[2], bool(cell.raw[0] & 0x20)
                    )
                )
    return tuple(result)


def project_routes(document: NX20Document) -> tuple[SplitRoute, ...]:
    if document.effective_lightmap:
        return ()
    routes: list[SplitRoute] = []
    for split_index, split in enumerate(document.splits):
        branches: list[RouteBranch] = []
        for block_index, block in enumerate(split.blocks):
            conditions = []
            for entry in block.divisions:
                meta_id = int(entry.meta_id.value)
                definition = metadata_definition(
                    document.profile, MetadataScope.DIVISION, meta_id
                )
                if definition is None or not definition.condition:
                    continue
                minimum, maximum = unpack_u16_range(int(entry.value.value))
                conditions.append(
                    ConditionClause(
                        meta_id, definition.label, minimum, maximum, entry.stable_id
                    )
                )
            branches.append(
                RouteBranch(
                    block.stable_id, block_index, tuple(conditions), _triggers(block)
                )
            )
        raw = int(split.raw_select.value)
        routes.append(
            SplitRoute(
                split.stable_id,
                split_index,
                bool(raw & 0x80),
                bool(raw & 0x40),
                bool(raw & 0x20),
                raw & 0x1F,
                tuple(branches),
            )
        )
    return tuple(routes)


def project_brain_shower(document: NX20Document) -> tuple[BrainShowerBlock, ...]:
    blocks: list[BrainShowerBlock] = []
    for split in document.splits:
        for block in split.blocks:
            values: dict[int, int] = {}
            duplicates: set[int] = set()
            unknown: set[int] = set()
            for entry in block.divisions:
                meta_id = int(entry.meta_id.value)
                definition = metadata_definition(
                    document.profile, MetadataScope.DIVISION, meta_id
                )
                if definition is None or not definition.brain_shower:
                    continue
                if meta_id in values:
                    duplicates.add(meta_id)
                values[meta_id] = int(entry.value.value)
                if not definition.authorable:
                    unknown.add(meta_id)
            if not values:
                continue

            def scalar(meta_id: int, source=values) -> int | None:
                return source.get(meta_id)

            def packed(meta_id: int, source=values) -> tuple[int, int] | None:
                value = source.get(meta_id)
                return None if value is None else unpack_u16_range(value)

            blocks.append(
                BrainShowerBlock(
                    block.stable_id,
                    scalar(21),
                    scalar(22),
                    scalar(23),
                    scalar(24),
                    scalar(25),
                    scalar(26),
                    scalar(31),
                    scalar(34),
                    packed(11),
                    packed(12),
                    packed(32),
                    packed(33),
                    tuple(sorted(duplicates)),
                    tuple(sorted(unknown)),
                )
            )
    return tuple(blocks)


def validate_authoring(document: NX20Document) -> ValidationReport:
    issues: list[ValidationIssue] = []
    known_profiles = {"nxa-native", "nxa-step5-patched"}
    if document.profile not in known_profiles:
        return ValidationReport(
            (
                ValidationIssue(
                    Severity.WARNING,
                    "profile.unknown",
                    "profile",
                    f"no authoring registry is installed for {document.profile!r}",
                ),
            )
        )

    for item in semantic_metadata(document):
        definition = item.definition
        if definition is None:
            issues.append(
                ValidationIssue(
                    Severity.WARNING,
                    "metadata.unknown",
                    item.path,
                    f"metadata ID {item.meta_id} is unknown in {item.scope.value} scope for {document.profile}",
                )
            )
            continue
        if definition.minimum is not None and item.value < definition.minimum:
            issues.append(
                ValidationIssue(
                    Severity.ERROR,
                    "metadata.value-low",
                    item.path,
                    f"{definition.label} value {item.value} is below {definition.minimum}",
                )
            )
        if definition.maximum is not None and item.value > definition.maximum:
            issues.append(
                ValidationIssue(
                    Severity.ERROR,
                    "metadata.value-high",
                    item.path,
                    f"{definition.label} value {item.value} exceeds {definition.maximum}",
                )
            )
        if definition.kind.value == "packed-u16-range":
            minimum, maximum = unpack_u16_range(item.value)
            if maximum and minimum > maximum:
                issues.append(
                    ValidationIssue(
                        Severity.WARNING,
                        "metadata.range-reversed",
                        item.path,
                        f"{definition.label} minimum {minimum} exceeds maximum {maximum}",
                    )
                )

    for brain in project_brain_shower(document):
        if brain.duplicate_ids:
            issues.append(
                ValidationIssue(
                    Severity.WARNING,
                    "brain.duplicate-field",
                    f"block#{brain.block_id}.divisions",
                    "duplicate Brain Shower IDs are preserved; typed editing requires an explicit entry choice: "
                    + ", ".join(map(str, brain.duplicate_ids)),
                )
            )
        if brain.answer_count is not None and not 1 <= brain.answer_count <= 10:
            issues.append(
                ValidationIssue(
                    Severity.ERROR,
                    "brain.answer-count",
                    f"block#{brain.block_id}.divisions",
                    f"Brain Shower answer count {brain.answer_count} is outside 1..10",
                )
            )
    return ValidationReport(tuple(issues))
