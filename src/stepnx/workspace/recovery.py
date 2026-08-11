from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.errors import StepNXError
from stepnx.core.model import NX20Document
from stepnx.core.validation import validate
from stepnx.workspace.folder import FolderWorkspace, SourceFormat


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class RecoveryError(StepNXError):
    """A recovery snapshot is corrupt, unsafe, or cannot be written."""


def default_recovery_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "StepNX Studio" / "recovery"
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state) / "stepnx-studio" / "recovery"
    return Path.home() / ".local" / "state" / "stepnx-studio" / "recovery"


@dataclass(frozen=True, slots=True)
class RecoveredDocument:
    source_path: Path
    output_path: Path | None
    source_format: str
    source_sha256: str
    document: NX20Document


@dataclass(frozen=True, slots=True)
class RecoverySnapshot:
    snapshot_id: str
    created_at: str
    workspace_root: Path
    path: Path
    documents: tuple[RecoveredDocument, ...]
    selected_audio: Path | None


class RecoveryStore:
    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = (Path(root) if root is not None else default_recovery_root()).resolve()

    def write(self, workspace: FolderWorkspace) -> Path | None:
        entries = tuple(entry for entry in workspace.documents if entry.is_modified)
        if not entries:
            return None
        if self.root == workspace.root or self.root.is_relative_to(workspace.root):
            raise RecoveryError("recovery storage must be outside the chart workspace")
        self.root.mkdir(parents=True, exist_ok=True)
        snapshot_id = uuid.uuid4().hex
        staging = Path(tempfile.mkdtemp(prefix=f".{snapshot_id}.", dir=self.root))
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
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def list(self) -> tuple[Path, ...]:
        if not self.root.is_dir():
            return ()
        return tuple(
            sorted(
                (
                    path
                    for path in self.root.iterdir()
                    if path.is_dir() and (path / "manifest.json").is_file()
                ),
                key=lambda path: path.name,
            )
        )

    def load(self, snapshot: str | os.PathLike[str]) -> RecoverySnapshot:
        path = Path(snapshot)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        if path.parent != self.root:
            raise RecoveryError("snapshot path falls outside the recovery root")
        try:
            manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RecoveryError(f"cannot read recovery manifest: {exc}") from exc
        if manifest.get("version") != 1 or manifest.get("snapshot_id") != path.name:
            raise RecoveryError("unsupported or mismatched recovery manifest")
        records = manifest.get("documents")
        if not isinstance(records, list) or not records:
            raise RecoveryError("recovery manifest contains no document records")
        documents = []
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise RecoveryError(f"document {index} is not a recovery record")
            payload_name = record.get("payload")
            if not isinstance(payload_name, str) or Path(payload_name).name != payload_name:
                raise RecoveryError(f"document {index} has an unsafe payload path")
            payload_path = path / payload_name
            try:
                payload = payload_path.read_bytes()
            except OSError as exc:
                raise RecoveryError(f"cannot read recovery payload {payload_name}: {exc}") from exc
            if _sha256(payload) != record.get("payload_sha256"):
                raise RecoveryError(f"recovery payload hash mismatch: {payload_name}")
            profile = record.get("profile")
            if not isinstance(profile, str) or not profile:
                raise RecoveryError(f"document {index} has no engine profile")
            try:
                source_path = Path(record["source_path"])
                source_format = str(record["source_format"])
                source_sha256 = str(record["source_sha256"])
            except (KeyError, TypeError) as exc:
                raise RecoveryError(f"document {index} has incomplete provenance") from exc
            if source_format not in {item.value for item in SourceFormat}:
                raise RecoveryError(f"document {index} has an unknown source format")
            if len(source_sha256) != 64 or any(
                character not in "0123456789abcdef" for character in source_sha256.casefold()
            ):
                raise RecoveryError(f"document {index} has an invalid source hash")
            document = parse_bytes(payload, source=str(source_path), profile=profile)
            documents.append(
                RecoveredDocument(
                    source_path,
                    Path(record["output_path"]) if record.get("output_path") else None,
                    source_format,
                    source_sha256,
                    document,
                )
            )
        try:
            created_at = str(manifest["created_at"])
            workspace_root = Path(manifest["workspace_root"])
        except (KeyError, TypeError) as exc:
            raise RecoveryError("recovery manifest has incomplete workspace provenance") from exc
        selected_audio = manifest.get("selected_audio")
        if selected_audio is not None and not isinstance(selected_audio, str):
            raise RecoveryError("recovery manifest has an invalid selected audio path")
        return RecoverySnapshot(
            str(manifest["snapshot_id"]),
            created_at,
            workspace_root,
            path,
            tuple(documents),
            Path(selected_audio) if selected_audio else None,
        )

    def restore(
        self,
        workspace: FolderWorkspace,
        snapshot: str | os.PathLike[str],
    ) -> FolderWorkspace:
        """Reapply a verified snapshot in memory without writing chart files."""

        recovered = self.load(snapshot)
        if recovered.workspace_root.resolve() != workspace.root.resolve():
            raise RecoveryError("recovery snapshot belongs to a different workspace")
        restored = workspace
        for item in recovered.documents:
            try:
                current = restored.document_for(item.source_path)
            except KeyError as exc:
                raise RecoveryError(
                    f"recovery source is no longer part of the workspace: {item.source_path}"
                ) from exc
            if current.source_format.value != item.source_format:
                raise RecoveryError(f"recovery source format changed: {item.source_path}")
            if current.original_sha256 != item.source_sha256:
                raise RecoveryError(f"recovery source changed on disk: {item.source_path}")
            replacement = current.with_document(item.document).with_output_path(
                item.output_path
            )
            if not validate(replacement.document).is_valid:
                raise RecoveryError(
                    f"recovered document is structurally invalid: {item.source_path}"
                )
            restored = restored.replace_document(replacement)
        return FolderWorkspace(
            restored.root,
            restored.documents,
            restored.failures,
            restored.diagnostics,
            restored.audio_candidates,
            recovered.selected_audio,
        )

    def discard(self, snapshot: str | os.PathLike[str]) -> None:
        loaded = self.load(snapshot)
        shutil.rmtree(loaded.path)
