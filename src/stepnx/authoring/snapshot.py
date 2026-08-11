from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum

from stepnx.core.model import NX20Document, Row
from stepnx.core.validation import Severity, validate


class MetadataScope(str, Enum):
    HEADER = "header"
    SPLIT = "split"
    DIVISION = "division"


@dataclass(frozen=True, slots=True)
class MetadataSnapshot:
    stable_id: int
    scope: MetadataScope
    meta_id: int
    value: int
    raw_meta_id: bytes
    raw_value: bytes
    path: str


@dataclass(frozen=True, slots=True)
class BlockSnapshot:
    stable_id: int
    split_id: int
    index: int
    start_time: float
    bpm: float
    scroll: float
    offset_or_delay: float
    speed_or_freeze: float
    beat_split: int
    beat_measure: int
    smooth_speed: int
    raw_flag: int
    rows: Sequence[Row]
    divisions: tuple[MetadataSnapshot, ...]

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class SplitSnapshot:
    stable_id: int
    index: int
    raw_select: int
    raw_brain: int
    raw_padding: int
    metadata: tuple[MetadataSnapshot, ...]
    blocks: tuple[BlockSnapshot, ...]

    def block(self, stable_id: int) -> BlockSnapshot:
        for block in self.blocks:
            if block.stable_id == stable_id:
                return block
        raise KeyError(stable_id)


@dataclass(frozen=True, slots=True)
class SnapshotDiagnostic:
    severity: Severity
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class AuthoringSnapshot:
    """Immutable, GUI-independent projection of one canonical document.

    Row collections remain source-backed sequences. They are immutable and are
    indexed only for the visible viewport, preserving compact storage on very
    large charts.
    """

    document_stable_id: int
    source_name: str | None
    profile: str
    role: str
    start_column: int
    columns: int
    effective_lightmap: bool
    header_metadata: tuple[MetadataSnapshot, ...]
    splits: tuple[SplitSnapshot, ...]
    active_blocks: tuple[tuple[int, int], ...]
    diagnostics: tuple[SnapshotDiagnostic, ...]

    def split(self, stable_id: int) -> SplitSnapshot:
        for split in self.splits:
            if split.stable_id == stable_id:
                return split
        raise KeyError(stable_id)

    def active_block_id(self, split_id: int) -> int:
        for candidate_split_id, block_id in self.active_blocks:
            if candidate_split_id == split_id:
                return block_id
        raise KeyError(split_id)

    def active_block(self, split_id: int) -> BlockSnapshot:
        split = self.split(split_id)
        return split.block(self.active_block_id(split_id))

    def with_active_block(self, split_id: int, block_id: int) -> AuthoringSnapshot:
        split = self.split(split_id)
        split.block(block_id)
        choices = dict(self.active_blocks)
        choices[split_id] = block_id
        ordered = tuple((item.stable_id, choices[item.stable_id]) for item in self.splits if item.blocks)
        return replace(self, active_blocks=ordered)

    def cycle_block(self, split_id: int, delta: int = 1) -> AuthoringSnapshot:
        split = self.split(split_id)
        if not split.blocks:
            return self
        current = self.active_block_id(split_id)
        index = next(i for i, block in enumerate(split.blocks) if block.stable_id == current)
        return self.with_active_block(split_id, split.blocks[(index + delta) % len(split.blocks)].stable_id)


def _metadata(entry, scope: MetadataScope, path: str) -> MetadataSnapshot:
    return MetadataSnapshot(
        stable_id=entry.stable_id,
        scope=scope,
        meta_id=int(entry.meta_id.value),
        value=int(entry.value.value),
        raw_meta_id=entry.meta_id.raw,
        raw_value=entry.value.raw,
        path=path,
    )


def create_authoring_snapshot(document: NX20Document) -> AuthoringSnapshot:
    header_metadata = tuple(
        _metadata(entry, MetadataScope.HEADER, f"header_metadata[{index}]")
        for index, entry in enumerate(document.header_metadata)
    )
    splits: list[SplitSnapshot] = []
    active_blocks: list[tuple[int, int]] = []
    for split_index, split in enumerate(document.splits):
        split_path = f"splits[{split_index}]"
        blocks: list[BlockSnapshot] = []
        for block_index, block in enumerate(split.blocks):
            block_path = f"{split_path}.blocks[{block_index}]"
            blocks.append(
                BlockSnapshot(
                    stable_id=block.stable_id,
                    split_id=split.stable_id,
                    index=block_index,
                    start_time=float(block.start_time.value),
                    bpm=float(block.bpm.value),
                    scroll=float(block.scroll.value),
                    offset_or_delay=float(block.offset_or_delay.value),
                    speed_or_freeze=float(block.speed_or_freeze.value),
                    beat_split=int(block.beat_split.value),
                    beat_measure=int(block.beat_measure.value),
                    smooth_speed=int(block.smooth_speed.value),
                    raw_flag=int(block.raw_flag.value),
                    rows=block.rows,
                    divisions=tuple(
                        _metadata(
                            entry,
                            MetadataScope.DIVISION,
                            f"{block_path}.divisions[{index}]",
                        )
                        for index, entry in enumerate(block.divisions)
                    ),
                )
            )
        block_tuple = tuple(blocks)
        if block_tuple:
            active_blocks.append((split.stable_id, block_tuple[0].stable_id))
        splits.append(
            SplitSnapshot(
                stable_id=split.stable_id,
                index=split_index,
                raw_select=int(split.raw_select.value),
                raw_brain=int(split.raw_brain.value),
                raw_padding=int(split.raw_padding.value),
                metadata=tuple(
                    _metadata(
                        entry,
                        MetadataScope.SPLIT,
                        f"{split_path}.metadata[{index}]",
                    )
                    for index, entry in enumerate(split.metadata)
                ),
                blocks=block_tuple,
            )
        )

    report = validate(document)
    diagnostics = tuple(
        SnapshotDiagnostic(issue.severity, issue.code, issue.path, issue.message)
        for issue in report.issues
    )
    return AuthoringSnapshot(
        document_stable_id=document.stable_id,
        source_name=document.source_name,
        profile=document.profile,
        role=document.role.value,
        start_column=int(document.start_column.value),
        columns=int(document.columns.value),
        effective_lightmap=document.effective_lightmap,
        header_metadata=header_metadata,
        splits=tuple(splits),
        active_blocks=tuple(active_blocks),
        diagnostics=diagnostics,
    )
