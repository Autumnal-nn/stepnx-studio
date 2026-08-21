from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from stepnx.core.errors import UnsupportedFormatError
from stepnx.importers.legacy import LegacyChart, LegacyContainer, load_legacy, parse_stf
from stepnx.importers.see import SEEImportResult, load as load_see
from stepnx.importers.ucs import parse_ucs


LEGACY_IMPORT_SUFFIXES = frozenset({".stf", ".st2", ".not", ".not5", ".stx", ".see", ".ksf", ".ucs"})


def load_importable(
    path: str | Path,
    *,
    profile: str = "nxa-native",
) -> LegacyChart | LegacyContainer | SEEImportResult:
    """Load any one-way non-NX20 source supported by the authoring import flow."""

    source = Path(path)
    suffix = source.suffix.casefold()
    data = source.read_bytes()
    if suffix == ".st2":
        return replace(parse_stf(data, source=str(source)), source_format="st2")
    if suffix == ".ucs":
        return parse_ucs(data, source=str(source))
    if suffix == ".see":
        return load_see(source, profile=profile)
    if suffix in LEGACY_IMPORT_SUFFIXES:
        return load_legacy(source)
    raise UnsupportedFormatError(f"unsupported import suffix: {source.suffix}")
