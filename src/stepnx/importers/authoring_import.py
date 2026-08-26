from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from pathlib import Path

from stepnx.codecs.nx20 import parse_bytes, save_atomic
from stepnx.core.model import (
    DeploymentRole,
    LightmapRow,
    NoteRow,
    NX20Document,
    PackedNoteRow,
)
from stepnx.importers.andamiro import AndamiroImportResult
from stepnx.importers.dispatch import load_importable
from stepnx.importers.legacy import LegacyChart, LegacyContainer, project_nx20
from stepnx.importers.see import SEEImportResult


_WINDOWS_FORBIDDEN = frozenset('<>:"/\\|?*')
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


@dataclass(frozen=True, slots=True)
class AuthoringImportCandidate:
    key: str
    label: str
    source_format: str
    document: NX20Document
    default_filename: str
    diagnostics: tuple[str, ...] = ()
    semantically_lossless: bool = True

    @property
    def statistics(self) -> dict[str, int]:
        return self.document.statistics()


def _legacy_candidate(
    chart: LegacyChart,
    *,
    index: int,
    total: int,
    source: Path,
    profile: str,
) -> AuthoringImportCandidate:
    document = replace(project_nx20(chart), profile=profile)
    suffix = f"_{index + 1}" if total > 1 else ""
    default_filename = f"{source.stem}{suffix}.NX"
    diagnostics = [
        f"{diagnostic.code}: {diagnostic.message}"
        + (f" (offset 0x{diagnostic.offset:X})" if diagnostic.offset is not None else "")
        for diagnostic in chart.diagnostics
    ]
    if chart.controls and chart.source_format != "ucs":
        diagnostics.append(
            "legacy.controls-not-projected: source control records that do not have "
            "a proven NX20 equivalent remain source-only"
        )
    semantically_lossless = chart.source_format == "ucs" and not diagnostics
    if chart.source_format != "ucs":
        diagnostics.insert(
            0,
            "legacy.projection: this format is converted to canonical NX20; "
            "source-only fields outside the verified projection are not written to the new NX",
        )
    return AuthoringImportCandidate(
        key=f"legacy-{index}",
        label=(
            f"{chart.source_format.upper()} chart {index + 1}"
            if total > 1
            else chart.source_format.upper()
        ),
        source_format=chart.source_format,
        document=document,
        default_filename=default_filename,
        diagnostics=tuple(diagnostics),
        semantically_lossless=semantically_lossless,
    )


def load_authoring_import_candidates(
    path: str | Path,
    *,
    profile: str = "nxa-native",
) -> tuple[AuthoringImportCandidate, ...]:
    """Project one supported import source into canonical NX20 candidates."""

    source = Path(path)
    imported = load_importable(source, profile=profile)

    if isinstance(imported, AndamiroImportResult):
        return tuple(
            AuthoringImportCandidate(
                key=chart.key,
                label=chart.label,
                source_format=chart.source_format,
                document=chart.document,
                default_filename=chart.default_filename,
                diagnostics=chart.diagnostics,
                semantically_lossless=chart.semantically_lossless,
            )
            for chart in imported.charts
        )

    if isinstance(imported, SEEImportResult):
        candidates: list[AuthoringImportCandidate] = []
        for chart in imported.charts:
            report = chart.report
            diagnostics = tuple(
                f"{diagnostic.kind.value}: {diagnostic.code}: {diagnostic.message}"
                + (f" [{diagnostic.path}]" if diagnostic.path else "")
                for diagnostic in report.diagnostics
            )
            candidates.append(
                AuthoringImportCandidate(
                    key=chart.mode.key,
                    label=f"{chart.mode.key} — {chart.mode.label}",
                    source_format="see",
                    document=chart.document,
                    default_filename=f"{chart.mode.key}.NX",
                    diagnostics=diagnostics,
                    semantically_lossless=report.is_semantically_lossless,
                )
            )
        return tuple(candidates)

    charts = imported.charts if isinstance(imported, LegacyContainer) else (imported,)
    return tuple(
        _legacy_candidate(
            chart,
            index=index,
            total=len(charts),
            source=source,
            profile=profile,
        )
        for index, chart in enumerate(charts)
    )


def document_has_content(document: NX20Document) -> bool:
    """Return whether a chart contains a non-empty playable/Lightmap row."""

    for split in document.splits:
        for block in split.blocks:
            for row in block.rows:
                if isinstance(row, LightmapRow):
                    if any(row.raw_channels[:3]):
                        return True
                elif isinstance(row, PackedNoteRow):
                    if any(row.raw_cells):
                        return True
                elif isinstance(row, NoteRow):
                    if any(any(cell.raw) for cell in row.cells):
                        return True
    return False


def _empty_lightmap(reference: NX20Document) -> NX20Document:
    split = reference.splits[0] if reference.splits else None
    block = split.blocks[0] if split is not None and split.blocks else None
    start_time = 0.0 if block is None else float(block.start_time.value)
    bpm = 120.0 if block is None else float(block.bpm.value)
    scroll = 0.25 if block is None else float(block.scroll.value)
    delay = 0.0 if block is None else float(block.offset_or_delay.value)
    speed = 1.0 if block is None else float(block.speed_or_freeze.value)
    beat_split = 4 if block is None else max(1, int(block.beat_split.value))
    beat_measure = 4 if block is None else max(1, int(block.beat_measure.value))

    output = bytearray(b"NX20")
    output += struct.pack("<III", 0, 3, 1)
    output += struct.pack("<I", 0)
    output += struct.pack("<I", 1)
    output += b"\x00\x00\x00\x00"
    output += struct.pack("<I", 0)
    output += struct.pack("<I", 1)
    output += struct.pack("<fffff", start_time, bpm, scroll, delay, speed)
    output += bytes((beat_split & 0xFF, beat_measure & 0xFF, 0, 0))
    output += struct.pack("<I", 0)
    output += struct.pack("<I", 1)
    output += b"\x00\x00\x00\x00"
    document = parse_bytes(
        bytes(output),
        source="generated empty LM.NX",
        profile=reference.profile,
    )
    return replace(document, role=DeploymentRole.LIGHTMAP)


def prepare_authoring_import_batch(
    candidates: tuple[AuthoringImportCandidate, ...],
) -> tuple[AuthoringImportCandidate, ...]:
    """Keep non-empty charts, always retaining/providing the required LM.NX."""

    selected = tuple(
        candidate
        for candidate in candidates
        if candidate.document.effective_lightmap or document_has_content(candidate.document)
    )
    if not selected:
        return ()
    if any(candidate.document.effective_lightmap for candidate in selected):
        return selected
    reference = selected[0].document
    generated = AuthoringImportCandidate(
        key="LM",
        label="LM — generated empty Lightmap",
        source_format=selected[0].source_format,
        document=_empty_lightmap(reference),
        default_filename="LM.NX",
        diagnostics=(
            "import.lightmap.generated: source has no Lightmap representation; created an empty LM.NX",
        ),
        semantically_lossless=False,
    )
    return selected + (generated,)


def validate_import_filename(filename: str) -> str:
    """Return a Windows-safe immediate-folder NX filename or raise ValueError."""

    value = filename.strip()
    if not value:
        raise ValueError("target filename cannot be empty")
    if any(character in _WINDOWS_FORBIDDEN for character in value):
        raise ValueError("target filename contains a character not allowed on Windows")
    if value.endswith((" ", ".")):
        raise ValueError("target filename cannot end in a space or period")
    candidate = Path(value)
    if candidate.name != value or value in {".", ".."}:
        raise ValueError("target must be a filename inside the import folder")
    if candidate.suffix.casefold() != ".nx":
        raise ValueError("target filename must end in .NX")
    if candidate.stem.upper() in _WINDOWS_RESERVED:
        raise ValueError(f"{candidate.stem} is a reserved Windows filename")
    return value


def validate_import_target(
    candidate: AuthoringImportCandidate,
    root: str | Path,
    filename: str,
) -> Path:
    safe_name = validate_import_filename(filename)
    folder = Path(root).resolve()
    if not folder.is_dir():
        raise ValueError(f"target import folder is not a directory: {folder}")
    target = (folder / safe_name).resolve()
    if target.parent != folder:
        raise ValueError("target escaped the import folder")
    if target.exists():
        raise FileExistsError(f"target already exists: {target.name}")
    if safe_name.casefold() == "lm.nx" and not candidate.document.effective_lightmap:
        raise ValueError("LM.NX is reserved for a Lightmap document")
    return target


def validate_authoring_import_batch(
    candidates: tuple[AuthoringImportCandidate, ...],
    root: str | Path,
) -> tuple[Path, ...]:
    if not candidates:
        raise ValueError("import batch contains no non-empty charts")
    names = [candidate.default_filename.casefold() for candidate in candidates]
    if len(names) != len(set(names)):
        raise ValueError("import batch contains duplicate target filenames")
    return tuple(
        validate_import_target(candidate, root, candidate.default_filename)
        for candidate in candidates
    )


def materialize_authoring_import(
    candidate: AuthoringImportCandidate,
    root: str | Path,
    filename: str,
) -> Path:
    target = validate_import_target(candidate, root, filename)
    save_atomic(candidate.document, target, overwrite=False)
    return target


def materialize_authoring_import_batch(
    candidates: tuple[AuthoringImportCandidate, ...],
    root: str | Path,
) -> tuple[Path, ...]:
    """Create a complete import set and roll back files if a write fails."""

    targets = validate_authoring_import_batch(candidates, root)
    created: list[Path] = []
    try:
        for candidate, target in zip(candidates, targets):
            save_atomic(candidate.document, target, overwrite=False)
            created.append(target)
    except Exception:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        raise
    return targets
