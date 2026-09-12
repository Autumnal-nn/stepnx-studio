from __future__ import annotations

from pathlib import Path

from stepnx.core.errors import UnsupportedFormatError
from stepnx.importers.andamiro import AndamiroImportResult, load_andamiro
from stepnx.importers.ksf import load as load_ksf
from stepnx.importers.legacy import LegacyChart, LegacyContainer
from stepnx.importers.see import SEEImportResult, load as load_see
from stepnx.importers.ssc import load as load_ssc
from stepnx.importers.ucs import parse_ucs


LEGACY_IMPORT_SUFFIXES = frozenset(
    {".stf", ".st2", ".not", ".not5", ".stx", ".see", ".ksf", ".ucs", ".ssc"}
)
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
    if suffix == ".ssc":
        return load_ssc(source, profile=profile)
    if suffix == ".ucs":
        return parse_ucs(source.read_bytes(), source=str(source))
    if suffix == ".see":
        return load_see(source, profile=profile)
    if suffix == ".ksf":
        return load_ksf(source, profile=profile)
    raise UnsupportedFormatError(
        0,
        "import source",
        f"unsupported chart-source extension {source.suffix or '<none>'!r}",
        str(source),
    )
