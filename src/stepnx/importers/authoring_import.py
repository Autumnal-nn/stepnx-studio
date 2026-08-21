from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from stepnx.codecs.nx20 import save_atomic
from stepnx.core.model import NX20Document
from stepnx.importers.dispatch import load_importable
from stepnx.importers.legacy import LegacyChart, LegacyContainer, project_nx20
from stepnx.importers.see import SEEImportResult


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
    diagnostics = tuple(
        f"{diagnostic.code}: {diagnostic.message}"
        + (f" (offset 0x{diagnostic.offset:X})" if diagnostic.offset is not None else "")
        for diagnostic in chart.diagnostics
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
        diagnostics=diagnostics,
        semantically_lossless=not diagnostics,
    )


def load_authoring_import_candidates(
    path: str | Path,
    *,
    profile: str = "nxa-native",
) -> tuple[AuthoringImportCandidate, ...]:
    """Project one supported import source into selectable NX20 candidates.

    The source is never modified. SEE deliberately keeps StepEdit's native
    mode split, so one .SEE may expose several independent NX20 candidates.
    """

    source = Path(path)
    imported = load_importable(source, profile=profile)

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


def validate_import_filename(filename: str) -> str:
    """Return a safe immediate-folder NX filename or raise ValueError."""

    value = filename.strip()
    if not value:
        raise ValueError("target filename cannot be empty")
    candidate = Path(value)
    if candidate.name != value or value in {".", ".."}:
        raise ValueError("target must be a filename inside the open folder")
    if candidate.suffix.casefold() != ".nx":
        raise ValueError("target filename must end in .NX")
    return value


def materialize_authoring_import(
    candidate: AuthoringImportCandidate,
    root: str | Path,
    filename: str,
) -> Path:
    """Write one imported NX20 candidate without replacing an existing file."""

    safe_name = validate_import_filename(filename)
    folder = Path(root).resolve()
    if not folder.is_dir():
        raise ValueError(f"target workspace is not a directory: {folder}")
    target = (folder / safe_name).resolve()
    if target.parent != folder:
        raise ValueError("target escaped the open folder")
    if target.exists():
        raise FileExistsError(f"target already exists: {target.name}")
    save_atomic(candidate.document, target, overwrite=False)
    return target
