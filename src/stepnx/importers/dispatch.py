from __future__ import annotations

from pathlib import Path

from stepnx.core.errors import UnsupportedFormatError
from stepnx.importers.andamiro import AndamiroImportResult, load_andamiro
from stepnx.importers.legacy import LegacyChart, LegacyContainer, load_legacy
from stepnx.importers.see import SEEImportResult, load as load_see
from stepnx.importers.ucs import parse_ucs


LEGACY_IMPORT_SUFFIXES = frozenset({".stf", ".st2", ".not", ".not5", ".stx", ".see", ".ksf", ".ucs"})
_ANDAMIRO_SUFFIXES = frozenset({".stf", ".st2", ".not", ".not5", ".stx"})


def load_importable(
    path: str | Path,
    *,
    profile: str = "nxa-native",
) -> LegacyChart | LegacyContainer | SEEImportResult | AndamiroImportResult:
    """Load any one-way non-NX20 source supported by the authoring import flow."""

    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix in _ANDAMIRO_SUFFIXES:
        return load_andamiro(source, profile=profile)
    if suffix == ".ucs":
        return parse_ucs(source.read_bytes(), source=str(source))
    if suffix == ".see":
        return load_see(source, profile=profile)
    if suffix == ".ksf":
        return load_legacy(source)
    raise UnsupportedFormatError(f"unsupported import suffix: {source.suffix}")
