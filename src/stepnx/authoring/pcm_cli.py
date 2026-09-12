from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from stepnx.authoring.pcm import load_nxa_pcm


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Decode and fingerprint the exact PCM used for NXA offset analysis.")
    parser.add_argument("source", type=Path)
    parser.add_argument("--wav", type=Path, help="Export source-frame PCM; chart origin is recorded in the JSON report")
    parser.add_argument("--report", type=Path, help="Write the reproducibility report (default: stdout)")
    parser.add_argument("--verify-repeat", action="store_true", help="Decode again with fresh state and require identical PCM and reports")
    args = parser.parse_args(argv)
    try:
        source = args.source.resolve()
        destinations = [p.resolve() for p in (args.wav, args.report) if p is not None]
        if source in destinations or len(destinations) != len(set(destinations)):
            raise ValueError("source and output paths must be distinct")
        if any(p.exists() for p in destinations):
            raise ValueError("output already exists; choose a new path")
        pcm = load_nxa_pcm(source)
        report = pcm.report()
        if args.verify_repeat:
            repeated = load_nxa_pcm(source)
            if repeated.samples != pcm.samples or repeated.report() != report:
                raise ValueError("independent decode did not reproduce PCM and sample ledger")
            report["repeat_verified"] = True
        serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.wav is not None:
            pcm.write_wav(args.wav)
        if args.report is not None:
            with args.report.open("x", encoding="utf-8") as output:
                output.write(serialized)
        else:
            sys.stdout.write(serialized)
    except (OSError, ValueError) as exc:
        print(f"PCM analysis failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
