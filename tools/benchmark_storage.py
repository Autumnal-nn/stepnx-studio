#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from stepnx.codecs.nx20 import load, serialize


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure NX20 row storage in an isolated process")
    parser.add_argument("path", type=Path)
    parser.add_argument("--mode", choices=("rich", "compact"), required=True)
    args = parser.parse_args()

    started = time.perf_counter()
    document = load(args.path, row_storage=args.mode)
    parsed = time.perf_counter()
    rebuilt = serialize(document)
    finished = time.perf_counter()
    exact = rebuilt == document.source_bytes

    result = {
        "path": str(args.path),
        "mode": args.mode,
        "source_bytes": document.source_size,
        "parse_seconds": parsed - started,
        "serialize_seconds": finished - parsed,
        "total_seconds": finished - started,
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "byte_exact": exact,
        **document.statistics(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if exact else 2


if __name__ == "__main__":
    sys.exit(main())
