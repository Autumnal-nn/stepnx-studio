from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Iterable, Sequence

from stepnx.codecs.nx20 import load, save_atomic, serialize
from stepnx.core.errors import StepNXError, UnsupportedFormatError


SUPPORTED_SUFFIXES = {".NX", ".NFO"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _summary(document) -> dict:
    rebuilt = serialize(document)
    result = {
        "source": document.source_name,
        "profile": document.profile,
        "role": document.role.value,
        "size": document.source_size,
        "body_size": document.body_span.size,
        "columns": int(document.columns.value),
        "start_column": int(document.start_column.value),
        "lightmap_flag": int(document.lightmap_flag.value),
        "effective_lightmap": document.effective_lightmap,
        "envelope": document.envelope.kind.value,
        "envelope_size": len(document.envelope.raw),
        "source_sha256": _sha256(document.source_bytes),
        "roundtrip_sha256": _sha256(rebuilt),
        "byte_exact_roundtrip": rebuilt == document.source_bytes,
    }
    result.update(document.statistics())
    return result


def _print_summary(summary: dict) -> None:
    print(f"source: {summary['source']}")
    print(f"profile / role: {summary['profile']} / {summary['role']}")
    print(
        "layout: "
        f"columns={summary['columns']} start={summary['start_column']} "
        f"lightmap={summary['lightmap_flag']} effective={summary['effective_lightmap']}"
    )
    print(
        "structure: "
        f"metadata={summary['header_metadata']} splits={summary['splits']} "
        f"blocks={summary['blocks']} rows={summary['rows']} notes={summary['note_cells']}"
    )
    print(f"envelope: {summary['envelope']} ({summary['envelope_size']} bytes)")
    print(f"round-trip: {'BYTE-EXACT' if summary['byte_exact_roundtrip'] else 'DIFFERS'}")


def _candidate_files(paths: Sequence[str]) -> Iterable[Path]:
    seen: set[Path] = set()
    for raw in paths:
        path = Path(raw)
        candidates = [path] if path.is_file() else path.rglob("*") if path.is_dir() else []
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.upper() in SUPPORTED_SUFFIXES:
                resolved = candidate.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    yield candidate


def _inspect(args: argparse.Namespace) -> int:
    document = load(args.path, profile=args.profile)
    summary = _summary(document)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        _print_summary(summary)
    return 0 if summary["byte_exact_roundtrip"] else 2


def _roundtrip(args: argparse.Namespace) -> int:
    document = load(args.path, profile=args.profile)
    rebuilt = serialize(document)
    exact = rebuilt == document.source_bytes
    if args.output:
        save_atomic(document, args.output, overwrite=args.force, backup=args.backup)
    result = {
        "source": str(args.path),
        "output": str(args.output) if args.output else None,
        "size": len(rebuilt),
        "byte_exact": exact,
        "sha256": _sha256(rebuilt),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        suffix = f" -> {args.output}" if args.output else ""
        print(f"{'BYTE-EXACT' if exact else 'DIFFERS'}: {args.path}{suffix} ({len(rebuilt)} bytes)")
    return 0 if exact else 2


def _verify(args: argparse.Namespace) -> int:
    totals = {"files": 0, "exact": 0, "unsupported": 0, "errors": 0}
    details = []
    for path in _candidate_files(args.paths):
        totals["files"] += 1
        try:
            document = load(path, profile=args.profile)
            rebuilt = serialize(document)
            exact = rebuilt == document.source_bytes
            totals["exact" if exact else "errors"] += 1
            if not exact:
                details.append({"path": str(path), "status": "roundtrip-differs"})
        except UnsupportedFormatError as exc:
            totals["unsupported"] += 1
            if args.strict_formats:
                totals["errors"] += 1
            details.append({"path": str(path), "status": "unsupported", "error": str(exc)})
        except (OSError, StepNXError) as exc:
            totals["errors"] += 1
            details.append({"path": str(path), "status": "error", "error": str(exc)})

    if args.json:
        print(json.dumps({"totals": totals, "details": details}, ensure_ascii=False, indent=2))
    else:
        print(
            f"verified={totals['exact']} unsupported={totals['unsupported']} "
            f"errors={totals['errors']} total={totals['files']}"
        )
        for detail in details[: args.max_errors]:
            print(f"{detail['status'].upper()}: {detail['path']}: {detail.get('error', '')}")
        if len(details) > args.max_errors:
            print(f"... {len(details) - args.max_errors} additional diagnostic(s) omitted")
    if totals["files"] == 0:
        return 3
    return 1 if totals["errors"] else 0


def _diff(args: argparse.Namespace) -> int:
    left = Path(args.left).read_bytes()
    right = Path(args.right).read_bytes()
    common = min(len(left), len(right))
    mismatch = next((index for index in range(common) if left[index] != right[index]), None)
    if mismatch is None and len(left) != len(right):
        mismatch = common
    identical = mismatch is None
    result = {
        "left": str(args.left),
        "right": str(args.right),
        "identical": identical,
        "left_size": len(left),
        "right_size": len(right),
        "first_mismatch": mismatch,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif identical:
        print(f"IDENTICAL: {args.left} == {args.right} ({len(left)} bytes)")
    else:
        print(
            f"DIFFERENT: first mismatch at 0x{mismatch:X}; "
            f"sizes {len(left)} vs {len(right)}"
        )
    return 0 if identical else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stepnx", description="StepNX Studio lossless NX20 tools")
    parser.add_argument("--version", action="version", version="StepNX Studio core 0.1.0.dev0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="inspect an NX20/NFO document")
    inspect_parser.add_argument("path", type=Path)
    inspect_parser.add_argument("--profile", default="nxa-native")
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.set_defaults(handler=_inspect)

    roundtrip_parser = subparsers.add_parser("roundtrip", help="rebuild and compare an NX20/NFO document")
    roundtrip_parser.add_argument("path", type=Path)
    roundtrip_parser.add_argument("--output", "-o", type=Path)
    roundtrip_parser.add_argument("--profile", default="nxa-native")
    roundtrip_parser.add_argument("--force", action="store_true")
    roundtrip_parser.add_argument("--backup", action="store_true")
    roundtrip_parser.add_argument("--json", action="store_true")
    roundtrip_parser.set_defaults(handler=_roundtrip)

    verify_parser = subparsers.add_parser("verify", help="verify byte-exact round-trip for files or folders")
    verify_parser.add_argument("paths", nargs="+")
    verify_parser.add_argument("--profile", default="nxa-native")
    verify_parser.add_argument("--strict-formats", action="store_true")
    verify_parser.add_argument("--max-errors", type=int, default=20)
    verify_parser.add_argument("--json", action="store_true")
    verify_parser.set_defaults(handler=_verify)

    diff_parser = subparsers.add_parser("diff", help="report the first binary difference")
    diff_parser.add_argument("left", type=Path)
    diff_parser.add_argument("right", type=Path)
    diff_parser.add_argument("--json", action="store_true")
    diff_parser.set_defaults(handler=_diff)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, StepNXError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

