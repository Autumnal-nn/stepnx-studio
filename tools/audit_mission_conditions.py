from __future__ import annotations

import argparse
import re
from pathlib import Path

from stepnx.authoring.conditions import analyze_condition

CONDITION_LINE = re.compile(r'^\s*CONDITION_[1-4]\s+"(.*)"\s*$', re.MULTILINE)


def audit(paths: list[Path], profile: str) -> int:
    failures: list[str] = []
    total = 0
    unique: set[str] = set()
    for path in paths:
        conditions = CONDITION_LINE.findall(path.read_text(errors="replace"))
        total += len(conditions)
        unique.update(conditions)
        for condition in conditions:
            analysis = analyze_condition(condition, profile)
            if not analysis.is_valid:
                failures.append(f"{path}: {condition!r}: {analysis.error}")
    print(f"conditions={total} unique={len(unique)} syntax_failures={len(failures)}")
    for failure in failures:
        print(failure)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit CONDITION_1..4 expressions in NX-era mission text files"
    )
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--profile", default="nxa-native")
    args = parser.parse_args(argv)
    return audit(args.paths, args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
