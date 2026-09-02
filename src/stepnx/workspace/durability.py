from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from stepnx.codecs.nx20 import serialize
from stepnx.core.errors import StepNXError
from stepnx.workspace.folder import FolderWorkspace, SavePlan, WorkspaceError, _target_matches
from stepnx.workspace.recovery import RecoveryError, RecoveryStore as _BaseRecoveryStore


def execute_save_plan(
    plan: SavePlan,
    *,
    replace_file: Callable[[str | os.PathLike[str], str | os.PathLike[str]], None] = os.replace,
) -> tuple[Path, ...]:
    """Execute a preflighted save plan without abandoning recoverable originals.

    This keeps the public save semantics from ``workspace.folder`` while making
    failure cleanup explicit enough to survive fault injection. Each target is
    still replaced atomically, but a multi-file plan cannot be one filesystem
    transaction. Completed replacements are therefore rolled back when a later
    stage or commit fails.

    Stage and backup paths are registered immediately after creation, before any
    write/copy/fsync that can fail. If rollback itself cannot restore an existing
    target, its original backup is deliberately left beside the chart and its
    path is included in the raised error instead of being deleted by cleanup.
    """

    if not plan.is_ready:
        raise WorkspaceError("save plan contains blocking diagnostics")
    targets = [operation.target for operation in plan.operations]
    if len(targets) != len(set(targets)):
        raise WorkspaceError("save plan contains duplicate targets")
    for operation in plan.operations:
        if not _target_matches(operation):
            raise WorkspaceError(f"target changed since save planning: {operation.target}")

    staged: dict[Path, Path] = {}
    originals: dict[Path, Path | None] = {}
    preserved_backups: set[Path] = set()
    committed: list[Path] = []
    try:
        for operation in plan.operations:
            operation.target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{operation.target.name}.",
                suffix=".stepnx-stage",
                dir=operation.target.parent,
                delete=False,
            ) as handle:
                stage = Path(handle.name)
                staged[operation.target] = stage
                handle.write(operation.payload)
                handle.flush()
                os.fsync(handle.fileno())

            if operation.target.exists():
                with tempfile.NamedTemporaryFile(
                    prefix=f".{operation.target.name}.",
                    suffix=".stepnx-original",
                    dir=operation.target.parent,
                    delete=False,
                ) as backup_handle:
                    backup = Path(backup_handle.name)
                originals[operation.target] = backup
                shutil.copy2(operation.target, backup)
            else:
                originals[operation.target] = None

        for operation in plan.operations:
            if not _target_matches(operation):
                raise WorkspaceError(f"target changed during save execution: {operation.target}")
            replace_file(staged[operation.target], operation.target)
            staged.pop(operation.target, None)
            committed.append(operation.target)
    except BaseException as exc:
        rollback_errors: list[str] = []
        for target in reversed(committed):
            original = originals[target]
            try:
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(original, target)
                    originals[target] = None
            except OSError as rollback_exc:
                if original is not None:
                    preserved_backups.add(original)
                    rollback_errors.append(
                        f"{target}: {rollback_exc}; original preserved at {original}"
                    )
                else:
                    rollback_errors.append(f"{target}: {rollback_exc}")

        detail = f"save failed and was rolled back: {exc}"
        if rollback_errors:
            detail += "; rollback also failed for " + "; ".join(rollback_errors)

        # Ordinary I/O/program errors remain the WorkspaceError contract. For a
        # process-level Python interruption, restore what we can and then let the
        # interruption propagate unless rollback itself also failed.
        if isinstance(exc, Exception) or rollback_errors:
            raise WorkspaceError(detail) from exc
        raise
    finally:
        for temporary in staged.values():
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        for original in originals.values():
            if original is None or original in preserved_backups:
                continue
            try:
                original.unlink(missing_ok=True)
            except OSError:
                pass
    return tuple(committed)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_final_snapshot_name(name: str) -> bool:
    return len(name) == 32 and all(character in "0123456789abcdef" for character in name)


class RecoveryStore(_BaseRecoveryStore):
    """Recovery store with crash-staging and fault-injection hardening."""

    def write(self, workspace: FolderWorkspace) -> Path | None:
        entries = tuple(entry for entry in workspace.documents if entry.is_modified)
        if not entries:
            return None
        if self.root == workspace.root or self.root.is_relative_to(workspace.root):
            raise RecoveryError("recovery storage must be outside the chart workspace")

        try:
            self.root.mkdir(parents=True, exist_ok=True)
            snapshot_id = uuid.uuid4().hex
            staging = Path(tempfile.mkdtemp(prefix=f".{snapshot_id}.", dir=self.root))
        except OSError as exc:
            raise RecoveryError(f"cannot create recovery staging area: {exc}") from exc

        final = self.root / snapshot_id
        records = []
        try:
            for index, entry in enumerate(entries):
                payload = serialize(entry.document)
                payload_name = f"document-{index:04d}.nx20"
                payload_path = staging / payload_name
                with payload_path.open("wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                records.append(
                    {
                        "source_path": str(entry.path),
                        "output_path": str(entry.output_path) if entry.output_path else None,
                        "source_format": entry.source_format.value,
                        "source_sha256": entry.original_sha256,
                        "profile": entry.document.profile,
                        "payload": payload_name,
                        "payload_sha256": _sha256(payload),
                    }
                )

            manifest = {
                "version": 1,
                "snapshot_id": snapshot_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "workspace_root": str(workspace.root),
                "selected_audio": (
                    str(workspace.selected_audio) if workspace.selected_audio else None
                ),
                "documents": records,
            }
            manifest_path = staging / "manifest.json"
            with manifest_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(manifest, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(staging, final)
            return final
        except BaseException as exc:
            # Hidden staging directories are never published as snapshots, and
            # Python-level interruptions still get a best-effort cleanup pass.
            shutil.rmtree(staging, ignore_errors=True)
            if isinstance(exc, Exception):
                if isinstance(exc, RecoveryError):
                    raise
                raise RecoveryError(f"cannot write recovery snapshot: {exc}") from exc
            raise

    def list(self) -> tuple[Path, ...]:
        if not self.root.is_dir():
            return ()
        return tuple(
            sorted(
                (
                    path
                    for path in self.root.iterdir()
                    if path.is_dir()
                    and _is_final_snapshot_name(path.name)
                    and (path / "manifest.json").is_file()
                ),
                key=lambda path: path.name,
            )
        )

    def load(self, snapshot: str | os.PathLike[str]):
        try:
            return super().load(snapshot)
        except RecoveryError:
            raise
        except (StepNXError, OSError, TypeError, ValueError) as exc:
            raise RecoveryError(f"invalid recovery snapshot payload: {exc}") from exc
