#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.errors import ParseError
from stepnx.core.validation import validate
from stepnx.importers.see import import_bytes


KNOWN_ORPHANS = frozenset({"A022.SEE"})
MAX_NESTED_ZIP_DEPTH = 3
MAX_MEMBER_SIZE = 32 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Source:
    name: str
    payload: bytes


def _zip_sources(payload: bytes, label: str, depth: int = 0) -> Iterable[Source]:
    if depth > MAX_NESTED_ZIP_DEPTH:
        raise ValueError(f"nested ZIP depth exceeds {MAX_NESTED_ZIP_DEPTH}: {label}")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            member = f"{label}!{info.filename}"
            suffix = Path(info.filename).suffix.casefold()
            if suffix not in {".see", ".zip"}:
                continue
            if info.file_size > MAX_MEMBER_SIZE:
                raise ValueError(
                    f"archive member exceeds {MAX_MEMBER_SIZE} bytes: {member}"
                )
            data = archive.read(info)
            if suffix == ".see":
                yield Source(member, data)
            else:
                yield from _zip_sources(data, member, depth + 1)


def _sources(path: Path) -> Iterable[Source]:
    if path.is_dir():
        for candidate in sorted(path.rglob("*")):
            if not candidate.is_file():
                continue
            if candidate.suffix.casefold() == ".see":
                yield Source(str(candidate), candidate.read_bytes())
            elif candidate.suffix.casefold() == ".zip":
                yield from _zip_sources(candidate.read_bytes(), str(candidate))
        return
    if path.suffix.casefold() == ".see":
        yield Source(str(path), path.read_bytes())
        return
    if path.suffix.casefold() == ".zip":
        yield from _zip_sources(path.read_bytes(), str(path))
        return
    raise ValueError("SEE corpus input must be a .SEE file, ZIP, or directory")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify StepEdit 5.63 SEE decoding and NX10/NX20 projection"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--strict-orphans",
        action="store_true",
        help="treat known unreferenced malformed SEE files as failures",
    )
    args = parser.parse_args(argv)

    seen = decoded = charts = orphaned = 0
    failures: list[str] = []
    for source in _sources(args.source):
        seen += 1
        basename = Path(source.name.split("!")[-1]).name.upper()
        known_orphan = basename in KNOWN_ORPHANS
        try:
            imported = import_bytes(source.payload, source=source.name)
            if known_orphan:
                failures.append(
                    f"{source.name}: known orphan unexpectedly decoded successfully"
                )
                continue
            for chart in imported.charts:
                native = serialize(chart.document)
                structural = validate(chart.document)
                reparsed = parse_bytes(native, source=f"{source.name} [{chart.mode.key}]")
                if not structural.is_valid:
                    failures.append(
                        f"{source.name}/{chart.mode.key}: "
                        f"{len(structural.errors)} NX20 validation error(s)"
                    )
                    continue
                if serialize(reparsed) != native:
                    failures.append(
                        f"{source.name}/{chart.mode.key}: NX20 projection is not stable"
                    )
                    continue
                charts += 1
            decoded += 1
        except (ParseError, ValueError, OSError, zipfile.BadZipFile) as error:
            if known_orphan and not args.strict_orphans:
                orphaned += 1
                print(f"ORPHAN: {source.name}: {error}")
            else:
                failures.append(f"{source.name}: {error}")

    print(
        f"see-corpus: decoded={decoded} orphaned={orphaned} "
        f"charts={charts} failures={len(failures)} total={seen}"
    )
    for failure in failures:
        print(f"ERROR: {failure}")
    if seen == 0:
        return 3
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
