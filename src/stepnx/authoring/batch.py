from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from stepnx.authoring.metadata import (
    MetadataDraft,
    ReplaceMetadataCollection,
    metadata_drafts,
)
from stepnx.authoring.timing import ShiftBlockStartTimes
from stepnx.core.model import DeploymentRole
from stepnx.workspace.folder import FolderWorkspace


class MetadataBatchMode(str, Enum):
    APPEND = "append"
    REPLACE_ALL = "replace-all"
    UPSERT_LAST = "upsert-last"


@dataclass(frozen=True, slots=True)
class BatchDocumentCommand:
    document_index: int
    path: Path
    command: object
    summary: str


@dataclass(frozen=True, slots=True)
class FolderBatchPlan:
    label: str
    commands: tuple[BatchDocumentCommand, ...]
    skipped: tuple[Path, ...]

    @property
    def document_count(self) -> int:
        return len(self.commands)


def _chart_documents(workspace: FolderWorkspace, *, include_lightmaps: bool):
    for index, entry in enumerate(workspace.documents):
        if not include_lightmaps and entry.document.role is DeploymentRole.LIGHTMAP:
            continue
        yield index, entry


def plan_batch_header_metadata(
    workspace: FolderWorkspace,
    meta_id: int,
    value: int,
    *,
    mode: MetadataBatchMode = MetadataBatchMode.UPSERT_LAST,
    include_lightmaps: bool = False,
) -> FolderBatchPlan:
    if not 0 <= meta_id <= 0xFFFFFFFF or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("metadata ID and value must fit unsigned 32-bit storage")
    commands: list[BatchDocumentCommand] = []
    skipped: list[Path] = []
    for index, entry in _chart_documents(
        workspace, include_lightmaps=include_lightmaps
    ):
        document = entry.document
        drafts = list(metadata_drafts(document.header_metadata))
        matches = [
            position
            for position, draft in enumerate(drafts)
            if draft.meta_id == meta_id
        ]
        if mode is MetadataBatchMode.APPEND:
            drafts.append(MetadataDraft(meta_id, value))
            detail = "append"
        elif mode is MetadataBatchMode.REPLACE_ALL:
            if not matches:
                skipped.append(entry.path)
                continue
            for position in matches:
                draft = drafts[position]
                drafts[position] = MetadataDraft(meta_id, value, draft.stable_id)
            detail = f"replace {len(matches)} existing"
        else:
            if matches:
                position = matches[-1]
                draft = drafts[position]
                drafts[position] = MetadataDraft(meta_id, value, draft.stable_id)
                detail = "replace last existing"
            else:
                drafts.append(MetadataDraft(meta_id, value))
                detail = "append missing"
        commands.append(
            BatchDocumentCommand(
                index,
                entry.path,
                ReplaceMetadataCollection(document.stable_id, tuple(drafts)),
                detail,
            )
        )
    return FolderBatchPlan(
        f"Header metadata {meta_id} = {value} ({mode.value})",
        tuple(commands),
        tuple(skipped),
    )


def plan_batch_shift_start_times(
    workspace: FolderWorkspace,
    delta_ms: float,
    *,
    include_lightmaps: bool = False,
) -> FolderBatchPlan:
    if not math.isfinite(delta_ms):
        raise ValueError("Start Time shift must be finite")
    commands = tuple(
        BatchDocumentCommand(
            index,
            entry.path,
            ShiftBlockStartTimes(delta_ms),
            f"shift every Block by {delta_ms:g} ms",
        )
        for index, entry in _chart_documents(
            workspace, include_lightmaps=include_lightmaps
        )
    )
    return FolderBatchPlan(f"Shift Start Times by {delta_ms:g} ms", commands, ())


def apply_batch_plan(
    workspace: FolderWorkspace, plan: FolderBatchPlan
) -> FolderWorkspace:
    updated = workspace
    for item in plan.commands:
        entry = updated.documents[item.document_index]
        document = item.command.apply(entry.document)
        updated = updated.replace_document(entry.with_document(document))
    return updated
