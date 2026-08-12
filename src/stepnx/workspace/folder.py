from __future__ import annotations

import hashlib
import math
import os
import shutil
import struct
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Literal

from stepnx.codecs.nx20 import load, parse_bytes, serialize
from stepnx.core.diff import StructuralChange, diff_documents
from stepnx.core.errors import StepNXError
from stepnx.core.model import NX20Document
from stepnx.core.validation import Severity, ValidationReport, validate
from stepnx.importers.nx10 import NX10ImportReport
from stepnx.importers.nx10 import import_bytes as import_nx10_bytes

AUDIO_SUFFIXES = frozenset({".AUD", ".FLAC", ".MP2", ".MP3", ".OGG", ".WAV"})
STEPEDIT_BLANK_LIGHTMAP_ROWS = 400


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class SourceFormat(str, Enum):
    NX20 = "nx20"
    NX10_IMPORT = "nx10-import"


@dataclass(frozen=True, slots=True)
class WorkspaceDiagnostic:
    severity: Severity
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class FolderFailure:
    path: Path
    error: str


@dataclass(frozen=True, slots=True)
class AudioCandidate:
    path: Path
    score: int


@dataclass(frozen=True, slots=True)
class FolderDocument:
    path: Path
    document: NX20Document
    source_format: SourceFormat
    original_sha256: str
    projected_sha256: str
    validation: ValidationReport
    import_report: NX10ImportReport | None = None
    output_path: Path | None = None

    @property
    def current_bytes(self) -> bytes:
        return serialize(self.document)

    @property
    def is_modified(self) -> bool:
        return _sha256(self.current_bytes) != self.projected_sha256

    @property
    def needs_native_target(self) -> bool:
        # Every NX10 input is only provenance for an editable NX20 projection.
        # Publication must materialize that projection even when the user has
        # not changed it after import; otherwise Save All would leave an NX10
        # deployment file behind while claiming the workspace is native.
        return self.source_format is SourceFormat.NX10_IMPORT and self.output_path is None

    def with_document(self, document: NX20Document) -> FolderDocument:
        return replace(self, document=document, validation=validate(document))

    def with_output_path(self, path: str | os.PathLike[str] | None) -> FolderDocument:
        return replace(self, output_path=None if path is None else Path(path))


@dataclass(frozen=True, slots=True)
class PublicationReport:
    issues: tuple[WorkspaceDiagnostic, ...]

    @property
    def errors(self) -> tuple[WorkspaceDiagnostic, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def is_ready(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class FolderWorkspace:
    root: Path
    documents: tuple[FolderDocument, ...]
    failures: tuple[FolderFailure, ...]
    diagnostics: tuple[WorkspaceDiagnostic, ...]
    audio_candidates: tuple[AudioCandidate, ...]
    selected_audio: Path | None = None

    def document_for(self, path: str | os.PathLike[str]) -> FolderDocument:
        wanted = Path(path).resolve()
        for entry in self.documents:
            if entry.path.resolve() == wanted:
                return entry
        raise KeyError(path)

    def replace_document(self, entry: FolderDocument) -> FolderWorkspace:
        resolved = entry.path.resolve()
        found = False
        replacements = []
        for current in self.documents:
            if current.path.resolve() == resolved:
                replacements.append(entry)
                found = True
            else:
                replacements.append(current)
        if not found:
            raise KeyError(entry.path)
        return replace(self, documents=tuple(replacements))

    def select_audio(self, path: str | os.PathLike[str] | None) -> FolderWorkspace:
        if path is None:
            return replace(self, selected_audio=None)
        selected = Path(path)
        if not selected.is_file():
            raise WorkspaceError(f"selected audio is not a file: {selected}")
        if selected.suffix.upper() not in AUDIO_SUFFIXES:
            raise WorkspaceError(
                f"unsupported audio suffix for session selection: {selected.suffix}"
            )
        return replace(self, selected_audio=selected.resolve())

    @property
    def lightmaps(self) -> tuple[FolderDocument, ...]:
        return tuple(entry for entry in self.documents if entry.path.name.upper() == "LM.NX")

    def publication_report(self) -> PublicationReport:
        issues = list(self.diagnostics)
        for failure in self.failures:
            issues.append(
                WorkspaceDiagnostic(
                    Severity.ERROR,
                    "folder.unreadable-document",
                    str(failure.path),
                    failure.error,
                )
            )

        if not self.documents:
            issues.append(
                WorkspaceDiagnostic(
                    Severity.ERROR,
                    "folder.no-documents",
                    str(self.root),
                    "folder has no immediate NX documents",
                )
            )

        for entry in self.documents:
            for issue in entry.validation.errors:
                issues.append(
                    WorkspaceDiagnostic(
                        issue.severity,
                        f"document.{issue.code}",
                        f"{entry.path}:{issue.path}",
                        issue.message,
                    )
                )
            if entry.needs_native_target and entry.output_path is None:
                issues.append(
                    WorkspaceDiagnostic(
                        Severity.ERROR,
                        "nx10.native-target-required",
                        str(entry.path),
                        "NX10 import needs an explicit NX20 materialization target",
                    )
                )

        exact_lightmaps = tuple(entry for entry in self.lightmaps if entry.path.name == "LM.NX")
        if not exact_lightmaps:
            issues.append(
                WorkspaceDiagnostic(
                    Severity.ERROR,
                    "lightmap.missing",
                    str(self.root / "LM.NX"),
                    "complete-folder publication requires an exact-case LM.NX",
                )
            )
        elif len(exact_lightmaps) > 1:
            issues.append(
                WorkspaceDiagnostic(
                    Severity.ERROR,
                    "lightmap.duplicate",
                    str(self.root),
                    "folder contains more than one exact LM.NX entry",
                )
            )
        else:
            lightmap = exact_lightmaps[0]
            if not lightmap.document.effective_lightmap:
                issues.append(
                    WorkspaceDiagnostic(
                        Severity.ERROR,
                        "lightmap.wrong-layout",
                        str(lightmap.path),
                        "LM.NX does not use the NX20 Lightmap row layout",
                    )
                )
        return PublicationReport(tuple(issues))


class WorkspaceError(StepNXError):
    """A folder operation cannot be completed safely."""


def create_blank_lightmap(
    bpm: float,
    *,
    profile: str = "nxa-native",
) -> NX20Document:
    """Create the native NX20 equivalent of StepEdit's blank Lightmap.

    Two independently regenerated StepEdit 5.63 NX10 Lightmaps differed only
    in their inherited BPM.  Their fixed layout is one 4/4 block at BeatSplit
    2 with 400 zeroed four-channel Lightmap rows.  Constructing NX20 directly
    keeps NX10 at the import boundary instead of making it an authoring format.
    """

    try:
        selected_bpm = float(bpm)
        packed_bpm = struct.pack("<f", selected_bpm)
    except (OverflowError, TypeError, ValueError) as exc:
        raise WorkspaceError(f"invalid blank Lightmap BPM: {bpm!r}") from exc
    if not math.isfinite(selected_bpm) or selected_bpm <= 0.0:
        raise WorkspaceError("blank Lightmap BPM must be finite and greater than zero")

    payload = bytearray(b"NX20")
    payload += struct.pack("<III", 0, 3, 1)
    payload += struct.pack("<II", 0, 1)  # no global metadata; one split
    payload += b"\x00\x00\x00\x00"  # select, brain, padding
    payload += struct.pack("<II", 0, 1)  # no split metadata; one block
    payload += struct.pack("<f", 0.0)
    payload += packed_bpm
    payload += struct.pack("<fff", 0.5, 0.0, 1.0)
    payload += bytes((2, 4, 0, 0))  # BeatSplit, measure, smooth, flag
    payload += struct.pack("<II", 0, STEPEDIT_BLANK_LIGHTMAP_ROWS)
    payload += b"\x00\x00\x00\x00" * STEPEDIT_BLANK_LIGHTMAP_ROWS
    return parse_bytes(
        bytes(payload),
        source="LM.NX",
        profile=profile,
        row_storage="compact",
    )


def _audio_score(path: Path, folder_name: str) -> int:
    stem = path.stem.casefold()
    score = 0
    if stem == folder_name.casefold():
        score += 100
    if stem in {"audio", "music", "song"}:
        score += 50
    score += {".WAV": 5, ".FLAC": 4, ".OGG": 3, ".MP3": 2, ".MP2": 1}.get(
        path.suffix.upper(), 0
    )
    return score


def discover_audio(root: str | os.PathLike[str]) -> tuple[AudioCandidate, ...]:
    folder = Path(root)
    candidates = [
        AudioCandidate(path.resolve(), _audio_score(path, folder.name))
        for path in folder.iterdir()
        if path.is_file() and not path.is_symlink() and path.suffix.upper() in AUDIO_SUFFIXES
    ]
    return tuple(sorted(candidates, key=lambda item: (-item.score, item.path.name.casefold())))


def open_folder(
    root: str | os.PathLike[str],
    *,
    profile: str = "nxa-native",
    row_storage: Literal["rich", "compact"] = "compact",
) -> FolderWorkspace:
    folder = Path(root)
    if not folder.is_dir():
        raise WorkspaceError(f"workspace is not a directory: {folder}")
    folder = folder.resolve()
    documents: list[FolderDocument] = []
    failures: list[FolderFailure] = []
    diagnostics: list[WorkspaceDiagnostic] = []

    candidates = sorted(
        (path for path in folder.iterdir() if path.suffix.upper() == ".NX"),
        key=lambda path: (path.name.casefold(), path.name),
    )
    folded: dict[str, list[Path]] = {}
    for path in candidates:
        folded.setdefault(path.name.casefold(), []).append(path)
    for paths in folded.values():
        if len(paths) > 1:
            diagnostics.append(
                WorkspaceDiagnostic(
                    Severity.ERROR,
                    "folder.case-collision",
                    str(folder),
                    "case-colliding NX names are unsafe on Windows: "
                    + ", ".join(path.name for path in paths),
                )
            )

    for path in candidates:
        if path.is_symlink():
            failures.append(
                FolderFailure(path, "symbolic links are not accepted as workspace documents")
            )
            continue
        if not path.is_file():
            failures.append(FolderFailure(path, "NX candidate is not a regular file"))
            continue
        try:
            source = path.read_bytes()
            source_hash = _sha256(source)
            if source[:4] == b"NX10":
                imported = import_nx10_bytes(source, source=str(path), profile=profile)
                document = imported.document
                projected_hash = _sha256(serialize(document))
                documents.append(
                    FolderDocument(
                        path.resolve(),
                        document,
                        SourceFormat.NX10_IMPORT,
                        source_hash,
                        projected_hash,
                        validate(document),
                        imported.report,
                    )
                )
            else:
                document = parse_bytes(
                    source,
                    source=str(path),
                    profile=profile,
                    row_storage=row_storage,
                )
                documents.append(
                    FolderDocument(
                        path.resolve(),
                        document,
                        SourceFormat.NX20,
                        source_hash,
                        source_hash,
                        validate(document),
                    )
                )
        except (OSError, StepNXError, ValueError) as exc:
            failures.append(FolderFailure(path.resolve(), str(exc)))

    return FolderWorkspace(
        folder,
        tuple(documents),
        tuple(failures),
        tuple(diagnostics),
        discover_audio(folder),
    )


@dataclass(frozen=True, slots=True)
class SaveOperation:
    source: Path | None
    target: Path
    payload: bytes
    expected_target_sha256: str | None
    expected_target_exists: bool


@dataclass(frozen=True, slots=True)
class SavePlan:
    operations: tuple[SaveOperation, ...]
    issues: tuple[WorkspaceDiagnostic, ...]
    complete_folder: bool

    @property
    def errors(self) -> tuple[WorkspaceDiagnostic, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def is_ready(self) -> bool:
        return not self.errors


def _operation_for(
    entry: FolderDocument,
    target: Path,
    *,
    allow_explicit_import_replacement: bool = False,
) -> SaveOperation:
    target = target.resolve()
    source = entry.path.resolve()
    if (
        entry.source_format is SourceFormat.NX10_IMPORT
        and target == source
        and not allow_explicit_import_replacement
    ):
        raise WorkspaceError("refusing to overwrite an NX10 import source with NX20")
    if target.exists():
        expected = entry.original_sha256 if target == source else _sha256(target.read_bytes())
        expected_exists = True
    else:
        expected = None
        expected_exists = False
    return SaveOperation(source, target, entry.current_bytes, expected, expected_exists)


def plan_individual_save(
    entry: FolderDocument,
    target: str | os.PathLike[str] | None = None,
) -> SavePlan:
    issues = [
        WorkspaceDiagnostic(issue.severity, f"document.{issue.code}", issue.path, issue.message)
        for issue in entry.validation.errors
    ]
    selected = Path(target) if target is not None else entry.output_path
    if selected is None and entry.source_format is SourceFormat.NX20:
        selected = entry.path
    if selected is None:
        issues.append(
            WorkspaceDiagnostic(
                Severity.ERROR,
                "nx10.native-target-required",
                str(entry.path),
                "NX10 imports require an explicit NX20 materialization target",
            )
        )
        return SavePlan((), tuple(issues), False)
    try:
        operation = _operation_for(
            entry,
            selected,
            allow_explicit_import_replacement=(
                entry.source_format is SourceFormat.NX10_IMPORT and target is not None
            ),
        )
    except (OSError, WorkspaceError) as exc:
        issues.append(
            WorkspaceDiagnostic(Severity.ERROR, "save.invalid-target", str(selected), str(exc))
        )
        return SavePlan((), tuple(issues), False)
    return SavePlan((operation,), tuple(issues), False)


def plan_blank_lightmap(
    workspace: FolderWorkspace,
    bpm: float,
) -> SavePlan:
    """Ensure a valid exact-case LM.NX exists, creating only when absent."""

    issues: list[WorkspaceDiagnostic] = []
    collisions = tuple(
        path
        for path in workspace.root.iterdir()
        if path.name.casefold() == "lm.nx"
    )
    target = (workspace.root / "LM.NX").resolve()
    exact = tuple(path for path in collisions if path.name == "LM.NX")
    if len(collisions) > 1:
        issues.append(
            WorkspaceDiagnostic(
                Severity.ERROR,
                "lightmap.case-collision",
                str(target),
                "case-colliding Lightmap names are unsafe on Windows: "
                + ", ".join(path.name for path in collisions),
            )
        )
        return SavePlan((), tuple(issues), False)
    if exact:
        loaded = tuple(
            entry
            for entry in workspace.lightmaps
            if entry.path.name == "LM.NX" and entry.path.resolve() == target
        )
        if (
            len(exact) == 1
            and len(loaded) == 1
            and loaded[0].document.effective_lightmap
            and loaded[0].validation.is_valid
        ):
            return SavePlan((), (), False)
        issues.append(
            WorkspaceDiagnostic(
                Severity.ERROR,
                "lightmap.existing-invalid",
                str(target),
                "existing LM.NX is unreadable or does not use the Lightmap layout; "
                "repair it explicitly instead of replacing it with a blank file",
            )
        )
        return SavePlan((), tuple(issues), False)
    if collisions:
        issues.append(
            WorkspaceDiagnostic(
                Severity.ERROR,
                "lightmap.case-collision",
                str(target),
                "blank Lightmap generation cannot create LM.NX beside a case-colliding name: "
                + ", ".join(path.name for path in collisions),
            )
        )
        return SavePlan((), tuple(issues), False)

    try:
        document = create_blank_lightmap(bpm, profile=(
            workspace.documents[0].document.profile
            if workspace.documents
            else "nxa-native"
        ))
    except WorkspaceError as exc:
        issues.append(
            WorkspaceDiagnostic(
                Severity.ERROR,
                "lightmap.invalid-bpm",
                str(target),
                str(exc),
            )
        )
        return SavePlan((), tuple(issues), False)

    validation = validate(document)
    for issue in validation.errors:
        issues.append(
            WorkspaceDiagnostic(
                issue.severity,
                f"document.{issue.code}",
                issue.path,
                issue.message,
            )
        )
    if issues:
        return SavePlan((), tuple(issues), False)
    operation = SaveOperation(None, target, serialize(document), None, False)
    return SavePlan((operation,), (), False)


def plan_save_all(workspace: FolderWorkspace) -> SavePlan:
    publication = workspace.publication_report()
    issues = list(publication.issues)
    operations: list[SaveOperation] = []
    targets: dict[str, Path] = {}
    existing_names = {
        entry.path.name.casefold(): entry.path for entry in workspace.documents
    }
    if publication.is_ready:
        for entry in workspace.documents:
            requested_target = entry.output_path or entry.path
            target = requested_target.resolve()
            if target.parent != workspace.root:
                issues.append(
                    WorkspaceDiagnostic(
                        Severity.ERROR,
                        "save.target-outside-folder",
                        str(target),
                        "Save All targets must be immediate files in the workspace folder",
                    )
                )
                continue
            if target.suffix.upper() != ".NX":
                issues.append(
                    WorkspaceDiagnostic(
                        Severity.ERROR,
                        "save.invalid-folder-suffix",
                        str(target),
                        "Save All targets must remain NX workspace documents",
                    )
                )
                continue
            target_key = requested_target.name.casefold()
            existing = existing_names.get(target_key)
            if existing is not None and existing.name != requested_target.name:
                issues.append(
                    WorkspaceDiagnostic(
                        Severity.ERROR,
                        "save.case-collision",
                        str(target),
                        f"target collides by case with existing workspace document: {existing}",
                    )
                )
                continue
            previous = targets.get(target_key)
            if previous is not None:
                issues.append(
                    WorkspaceDiagnostic(
                        Severity.ERROR,
                        "save.target-collision",
                        str(target),
                        f"multiple documents target the same path: {previous} and {entry.path}",
                    )
                )
                continue
            targets[target_key] = entry.path
            if (
                entry.source_format is SourceFormat.NX10_IMPORT
                or entry.is_modified
                or target != entry.path.resolve()
            ):
                try:
                    operations.append(
                        _operation_for(
                            entry,
                            target,
                            allow_explicit_import_replacement=(
                                entry.source_format is SourceFormat.NX10_IMPORT
                                and entry.output_path is not None
                            ),
                        )
                    )
                except (OSError, WorkspaceError) as exc:
                    issues.append(
                        WorkspaceDiagnostic(
                            Severity.ERROR, "save.invalid-target", str(target), str(exc)
                        )
                    )
    return SavePlan(tuple(operations), tuple(issues), True)


def _target_matches(operation: SaveOperation) -> bool:
    if operation.target.exists() != operation.expected_target_exists:
        return False
    if not operation.expected_target_exists:
        return True
    try:
        return _sha256(operation.target.read_bytes()) == operation.expected_target_sha256
    except OSError:
        return False


def execute_save_plan(
    plan: SavePlan,
    *,
    replace_file: Callable[[str | os.PathLike[str], str | os.PathLike[str]], None] = os.replace,
) -> tuple[Path, ...]:
    """Execute a preflighted multi-file plan with best-effort rollback.

    Each target is replaced atomically. No filesystem offers an atomic commit
    spanning several files, so staged originals are retained until every
    replacement succeeds and are restored if a later replacement fails.
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
                handle.write(operation.payload)
                handle.flush()
                os.fsync(handle.fileno())
                staged[operation.target] = Path(handle.name)

            if operation.target.exists():
                with tempfile.NamedTemporaryFile(
                    prefix=f".{operation.target.name}.",
                    suffix=".stepnx-original",
                    dir=operation.target.parent,
                    delete=False,
                ) as backup_handle:
                    backup = Path(backup_handle.name)
                shutil.copy2(operation.target, backup)
                originals[operation.target] = backup
            else:
                originals[operation.target] = None

        for operation in plan.operations:
            if not _target_matches(operation):
                raise WorkspaceError(f"target changed during save execution: {operation.target}")
            replace_file(staged[operation.target], operation.target)
            staged.pop(operation.target, None)
            committed.append(operation.target)
    except Exception as exc:
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
                rollback_errors.append(f"{target}: {rollback_exc}")
        detail = f"save failed and was rolled back: {exc}"
        if rollback_errors:
            detail += "; rollback also failed for " + "; ".join(rollback_errors)
        raise WorkspaceError(detail) from exc
    finally:
        for temporary in (*staged.values(), *(path for path in originals.values() if path)):
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return tuple(committed)


@dataclass(frozen=True, slots=True)
class MirrorComparison:
    target: Path
    binary_identical: bool
    structural_changes: tuple[StructuralChange, ...]
    target_document: NX20Document


def compare_mirror(
    document: NX20Document,
    target: str | os.PathLike[str],
    *,
    max_changes: int = 100,
) -> MirrorComparison:
    path = Path(target)
    target_document = load(path, profile=document.profile)
    return MirrorComparison(
        path.resolve(),
        serialize(document) == target_document.source_bytes,
        diff_documents(document, target_document, max_changes=max_changes),
        target_document,
    )


def plan_mirror_export(document: NX20Document, target: str | os.PathLike[str]) -> SavePlan:
    path = Path(target)
    if path.suffix.upper() not in {".NX", ".NFO"}:
        issue = WorkspaceDiagnostic(
            Severity.ERROR,
            "mirror.invalid-suffix",
            str(path),
            "mirror export target must use .NX or .NFO",
        )
        return SavePlan((), (issue,), False)
    report = validate(document)
    issues = tuple(
        WorkspaceDiagnostic(item.severity, f"document.{item.code}", item.path, item.message)
        for item in report.errors
    )
    resolved = path.resolve()
    operation = SaveOperation(
        Path(document.source_name).resolve() if document.source_name else None,
        resolved,
        serialize(document),
        _sha256(resolved.read_bytes()) if resolved.exists() else None,
        resolved.exists(),
    )
    return SavePlan((operation,), issues, False)
