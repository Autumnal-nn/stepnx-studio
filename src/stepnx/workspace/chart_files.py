from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

from stepnx.authoring.field import FieldGeometry
from stepnx.codecs.nx20 import serialize
from stepnx.core.model import (
    DeploymentRole,
    EmptyRow,
    NX20Document,
)
from stepnx.core.scalars import RawU8, RawU16, RawU32, SourceSpan
from stepnx.core.validation import validate
from stepnx.workspace.folder import (
    FolderDocument,
    FolderWorkspace,
    SaveOperation,
    SavePlan,
    WorkspaceDiagnostic,
    WorkspaceError,
)
from stepnx.core.validation import Severity


_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_WINDOWS_INVALID = frozenset('<>:"/\\|?*')


def normalize_nx_filename(value: str) -> str:
    """Return a Windows-safe immediate `.NX` filename or raise ValueError."""

    name = str(value).strip()
    if not name:
        raise ValueError("NX filename cannot be empty")
    if any(character in _WINDOWS_INVALID or ord(character) < 32 for character in name):
        raise ValueError("NX filename contains a character that is invalid on Windows")
    if name.endswith((" ", ".")):
        raise ValueError("NX filename cannot end with a space or period on Windows")
    path = Path(name)
    if path.name != name or path.parent != Path("."):
        raise ValueError("NX filename must be an immediate filename, not a path")
    if not path.suffix:
        name += ".NX"
        path = Path(name)
    if path.suffix.casefold() != ".nx":
        raise ValueError("workspace chart filenames must use the .NX extension")
    if path.stem.upper() in _WINDOWS_RESERVED:
        raise ValueError(f"{path.stem} is a reserved Windows filename")
    if name.casefold() == "lm.nx":
        raise ValueError("LM.NX is the protected workspace Lightmap")
    return name


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _target_for(workspace: FolderWorkspace, filename: str) -> Path:
    name = normalize_nx_filename(filename)
    folded = name.casefold()
    collisions = tuple(
        path
        for path in workspace.root.iterdir()
        if path.name.casefold() == folded
    )
    if collisions:
        raise FileExistsError(
            f"target collides with existing workspace file: {collisions[0].name}"
        )
    return (workspace.root / name).resolve()


def _exact_lightmap(workspace: FolderWorkspace) -> FolderDocument:
    matches = tuple(
        entry
        for entry in workspace.documents
        if entry.path.name == "LM.NX"
    )
    if len(matches) != 1:
        raise WorkspaceError("creating a chart requires exactly one loaded LM.NX")
    entry = matches[0]
    if not entry.document.effective_lightmap or not entry.validation.is_valid:
        raise WorkspaceError("creating a chart requires a structurally valid LM.NX")
    return entry


def create_chart_from_lightmap(
    lightmap: NX20Document,
    geometry: FieldGeometry,
    *,
    source_name: str | None = None,
) -> NX20Document:
    """Build an empty note chart using the Lightmap's timing/header skeleton.

    The header metadata and envelope remain paired so later-engine trailer
    references stay valid. Split/Block timing topology is retained, while
    branch metadata, Division metadata, Lightmap channels and route selector
    bytes are deliberately cleared. Every source row becomes an NX20 empty-row
    marker, so the result contains no gameplay notes.
    """

    if not lightmap.effective_lightmap:
        raise ValueError("chart template source must be an NX20 Lightmap")
    if int(geometry.columns) == 3:
        raise ValueError("Columns = 3 is reserved for NX20 Lightmap geometry")

    header_metadata = tuple(
        replace(
            entry,
            meta_id=replace(entry.meta_id, span=None),
            value=replace(entry.value, span=None),
            span=None,
        )
        for entry in lightmap.header_metadata
    )
    splits = []
    for split in lightmap.splits:
        blocks = []
        for block in split.blocks:
            rows = tuple(
                EmptyRow(row.stable_id, b"\x80\x00\x00\x00", None)
                for row in block.rows
            )
            blocks.append(
                replace(
                    block,
                    start_time=replace(block.start_time, span=None),
                    bpm=replace(block.bpm, span=None),
                    scroll=replace(block.scroll, span=None),
                    offset_or_delay=replace(block.offset_or_delay, span=None),
                    speed_or_freeze=replace(block.speed_or_freeze, span=None),
                    beat_split=replace(block.beat_split, span=None),
                    beat_measure=replace(block.beat_measure, span=None),
                    smooth_speed=replace(block.smooth_speed, span=None),
                    raw_flag=RawU8.from_value(0),
                    division_count=RawU32.from_value(0),
                    divisions=(),
                    row_count=RawU32.from_value(len(rows)),
                    rows=rows,
                    span=None,
                )
            )
        splits.append(
            replace(
                split,
                raw_select=RawU8.from_value(0),
                raw_brain=RawU8.from_value(0),
                raw_padding=RawU16.from_value(0),
                metadata_count=RawU32.from_value(0),
                metadata=(),
                block_count=RawU32.from_value(len(blocks)),
                blocks=tuple(blocks),
                span=None,
            )
        )

    return replace(
        lightmap,
        start_column=RawU32.from_value(int(geometry.start_column)),
        columns=RawU32.from_value(int(geometry.columns)),
        lightmap_flag=RawU32.from_value(0),
        header_metadata_count=RawU32.from_value(len(header_metadata)),
        header_metadata=header_metadata,
        split_count=RawU32.from_value(len(splits)),
        splits=tuple(splits),
        body_span=SourceSpan(0, 0),
        envelope=replace(lightmap.envelope, span=None),
        role=DeploymentRole.CHART,
        source_name=source_name,
        source_bytes=b"",
    )


def plan_create_nx_chart(
    workspace: FolderWorkspace,
    filename: str,
    geometry: FieldGeometry,
) -> SavePlan:
    target = _target_for(workspace, filename)
    lightmap = _exact_lightmap(workspace)
    document = create_chart_from_lightmap(
        lightmap.document,
        geometry,
        source_name=str(target),
    )
    report = validate(document)
    issues = tuple(
        WorkspaceDiagnostic(
            issue.severity,
            f"document.{issue.code}",
            issue.path,
            issue.message,
        )
        for issue in report.errors
    )
    if issues:
        return SavePlan((), issues, False)
    return SavePlan(
        (SaveOperation(None, target, serialize(document), None, False),),
        (),
        False,
    )


def _workspace_entry(
    workspace: FolderWorkspace,
    source: str | os.PathLike[str],
) -> FolderDocument:
    try:
        return workspace.document_for(source)
    except KeyError as exc:
        raise WorkspaceError(f"NX file is not a loaded workspace document: {source}") from exc


def _require_unchanged_source(entry: FolderDocument) -> bytes:
    if entry.path.name.casefold() == "lm.nx":
        raise WorkspaceError("LM.NX is protected and cannot be duplicated or deleted")
    try:
        payload = entry.path.read_bytes()
    except OSError as exc:
        raise WorkspaceError(f"cannot read workspace source: {entry.path}") from exc
    if _sha256(payload) != entry.original_sha256:
        raise WorkspaceError(
            f"workspace source changed outside StepNX Studio: {entry.path.name}"
        )
    return payload


def plan_duplicate_nx_chart(
    workspace: FolderWorkspace,
    source: str | os.PathLike[str],
    filename: str,
) -> SavePlan:
    entry = _workspace_entry(workspace, source)
    payload = _require_unchanged_source(entry)
    target = _target_for(workspace, filename)
    return SavePlan(
        (SaveOperation(entry.path.resolve(), target, payload, None, False),),
        (),
        False,
    )


def delete_nx_chart(
    workspace: FolderWorkspace,
    source: str | os.PathLike[str],
) -> Path:
    entry = _workspace_entry(workspace, source)
    _require_unchanged_source(entry)
    path = entry.path.resolve()
    try:
        path.unlink()
    except OSError as exc:
        raise WorkspaceError(f"cannot delete workspace chart: {path}") from exc
    return path
