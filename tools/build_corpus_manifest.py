#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def describe(path: Path, root: Path) -> dict:
    data = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "magic": data[:4].decode("ascii", errors="replace"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a private local corpus manifest")
    parser.add_argument(
        "--corpus",
        action="append",
        nargs=3,
        metavar=("LABEL", "PROFILE", "ROOT"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    corpora = []
    for label, profile, raw_root in args.corpus:
        root = Path(raw_root).resolve()
        files = sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.upper() in {".NX", ".NFO"}
            ),
            key=lambda path: path.as_posix().lower(),
        )
        corpora.append(
            {
                "label": label,
                "profile": profile,
                "root": str(root),
                "files": [describe(path, root) for path in files],
            }
        )

    manifest = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpora": corpora,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

