#!/usr/bin/env python3
"""Deterministic false-header probes against an external, local NXA oracle."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import subprocess
import tempfile
from pathlib import Path

from stepnx.authoring.nxa_startup import NxaStartupError, analyze_nxa_mp3_startup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path("tests/fixtures/audio/generated.mp3"))
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--cases", type=int, default=1000)
    args = parser.parse_args()
    fixture = args.fixture.read_bytes()
    rng = random.Random(args.seed)
    rows = []
    with tempfile.TemporaryDirectory(prefix="stepnx-startup-") as directory:
        source, raw, log = (Path(directory) / name for name in ("probe.mp3", "reference.raw", "trace.csv"))
        for index in range(args.cases):
            prefix = bytearray(rng.randbytes(rng.randrange(4, 2048)))
            for _ in range(rng.randrange(4)):
                at = rng.randrange(0, len(prefix) - 3)
                prefix[at:at + 2] = b"\xff\xff"
            payload = bytes(prefix) + fixture
            row = {"case": index, "payload_sha256": hashlib.sha256(payload).hexdigest()}
            source.write_bytes(payload)
            subprocess.run([str(args.oracle.resolve()), str(source), str(raw), str(log)], check=True, timeout=10)
            with log.open() as file:
                trace = list(csv.DictReader(file))
            first = next((i for i, item in enumerate(trace) if item["error"] == "0"), None)
            row["first_decoded_offset"] = int(trace[first]["offset"]) if first is not None else None
            row["recoveries"] = [[int(item["offset"]), int(item["length"])] for item in trace[:first]]
            try:
                result = analyze_nxa_mp3_startup(payload)
                predicted = [[item.offset, item.synthesized_samples] for item in result.recoveries]
                row["status"] = "matched" if (result.first_decoded_offset == row["first_decoded_offset"] and
                                               predicted == row["recoveries"]) else "mismatch"
                if row["status"] == "mismatch":
                    row["predicted"] = {"first": result.first_decoded_offset, "recoveries": predicted}
            except NxaStartupError as exc:
                row.update(status="rejected", reason=str(exc))
            rows.append(row)
    report = {"seed": args.seed, "cases": args.cases,
              "fixture_sha256": hashlib.sha256(fixture).hexdigest(), "results": rows}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    counts = {status: sum(row["status"] == status for row in rows) for status in ("matched", "rejected", "mismatch")}
    print(json.dumps(counts))
    return int(not rows or counts["mismatch"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
