#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Sequence

from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.validation import validate
from stepnx.importers.nx10 import load


DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "tests/corpus/nxa-nx10-reference.json"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the NXA-embedded NX10 reference projections"
    )
    parser.add_argument("root", type=Path, help="root containing the manifest's relative paths")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise SystemExit(f"unsupported reference manifest schema: {manifest.get('schema')!r}")

    failures: list[str] = []
    exact = 0
    for entry in manifest["files"]:
        relative = entry["path"]
        path = args.root / relative
        try:
            source = path.read_bytes()
        except OSError as error:
            failures.append(f"{relative}: {error}")
            continue
        if len(source) != entry["source_size"] or _sha256(source) != entry["source_sha256"]:
            failures.append(f"{relative}: source size/hash differs from the reference")
            continue

        imported = load(path, profile=manifest["profile"])
        native = serialize(imported.document)
        structural = validate(imported.document)
        reparsed = parse_bytes(native, source=f"{path} [reference projection]")
        problems = []
        if not imported.report.is_semantically_lossless:
            problems.append("import report contains approximation or unsupported diagnostics")
        if not structural.is_valid:
            problems.append(f"canonical document has {len(structural.errors)} validation error(s)")
        if serialize(reparsed) != native:
            problems.append("native NX20 projection is not stable after reparse")
        if len(native) != entry["nx20_size"] or _sha256(native) != entry["nx20_sha256"]:
            problems.append("native NX20 size/hash differs from the reference")
        if problems:
            failures.append(f"{relative}: {'; '.join(problems)}")
        else:
            exact += 1

    print(f"nx10-reference: {exact}/{len(manifest['files'])} exact")
    for failure in failures:
        print(f"ERROR: {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
