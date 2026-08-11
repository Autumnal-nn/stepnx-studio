from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Iterable, Sequence

from stepnx.codecs.nx20 import load, parse_bytes, save_atomic, serialize
from stepnx.core.diff import diff_documents
from stepnx.core.errors import StepNXError, UnsupportedFormatError
from stepnx.core.validation import validate
from stepnx.importers.nx10 import load as load_nx10


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
    document = load(args.path, profile=args.profile, row_storage=args.row_storage)
    summary = _summary(document)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        _print_summary(summary)
    return 0 if summary["byte_exact_roundtrip"] else 2


def _roundtrip(args: argparse.Namespace) -> int:
    document = load(args.path, profile=args.profile, row_storage=args.row_storage)
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
    totals = {
        "files": 0,
        "exact": 0,
        "imported": 0,
        "import_attention": 0,
        "unsupported": 0,
        "errors": 0,
    }
    details = []
    for path in _candidate_files(args.paths):
        totals["files"] += 1
        try:
            with path.open("rb") as handle:
                magic = handle.read(4)
            if magic == b"NX10":
                imported = load_nx10(path)
                native = serialize(imported.document)
                reparsed = parse_bytes(native, source=f"{path} [imported NX20]")
                structural = validate(imported.document)
                clean = (
                    imported.report.is_semantically_lossless
                    and structural.is_valid
                    and serialize(reparsed) == native
                )
                if clean:
                    totals["imported"] += 1
                else:
                    totals["import_attention"] += 1
                    totals["errors"] += 1
                    details.append(
                        {
                            "path": str(path),
                            "status": "nx10-import-attention",
                            "diagnostics": [
                                {
                                    "kind": diagnostic.kind.value,
                                    "code": diagnostic.code,
                                    "message": diagnostic.message,
                                }
                                for diagnostic in imported.report.diagnostics
                            ],
                            "validation_errors": len(structural.errors),
                        }
                    )
                continue
            document = load(path, profile=args.profile, row_storage=args.row_storage)
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
            f"verified={totals['exact']} imported={totals['imported']} "
            f"import_attention={totals['import_attention']} unsupported={totals['unsupported']} "
            f"errors={totals['errors']} total={totals['files']}"
        )
        for detail in details[: args.max_errors]:
            print(f"{detail['status'].upper()}: {detail['path']}: {detail.get('error', '')}")
        if len(details) > args.max_errors:
            print(f"... {len(details) - args.max_errors} additional diagnostic(s) omitted")
    if totals["files"] == 0:
        return 3
    return 1 if totals["errors"] else 0


def _validate(args: argparse.Namespace) -> int:
    document = load(args.path, profile=args.profile, row_storage=args.row_storage)
    report = validate(document)
    result = {
        "source": str(args.path),
        "valid": report.is_valid,
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "issues": [
            {
                "severity": issue.severity.value,
                "code": issue.code,
                "path": issue.path,
                "message": issue.message,
            }
            for issue in report.issues
        ],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "VALID" if report.is_valid else "INVALID"
        print(f"{status}: {args.path} ({len(report.errors)} error(s), {len(report.warnings)} warning(s))")
        for item in result["issues"][: args.max_issues]:
            print(
                f"{item['severity'].upper()} {item['code']} at {item['path']}: "
                f"{item['message']}"
            )
        if len(result["issues"]) > args.max_issues:
            print(f"... {len(result['issues']) - args.max_issues} additional issue(s) omitted")
    return 0 if report.is_valid else 1


def _diff(args: argparse.Namespace) -> int:
    left_bytes = Path(args.left).read_bytes()
    right_bytes = Path(args.right).read_bytes()
    common = min(len(left_bytes), len(right_bytes))
    mismatch = next(
        (index for index in range(common) if left_bytes[index] != right_bytes[index]), None
    )
    if mismatch is None and len(left_bytes) != len(right_bytes):
        mismatch = common
    binary_identical = mismatch is None

    left = load(args.left, profile=args.profile, row_storage=args.row_storage)
    right = load(args.right, profile=args.profile, row_storage=args.row_storage)
    changes = diff_documents(left, right, max_changes=args.max_changes)
    result = {
        "left": str(args.left),
        "right": str(args.right),
        "identical": binary_identical,
        "left_size": len(left_bytes),
        "right_size": len(right_bytes),
        "first_binary_mismatch": mismatch,
        "structural_changes": [
            {"path": change.path, "before": change.before, "after": change.after}
            for change in changes
        ],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif binary_identical:
        print(f"IDENTICAL: {args.left} == {args.right} ({len(left_bytes)} bytes)")
    else:
        print(
            f"DIFFERENT: first mismatch at 0x{mismatch:X}; "
            f"sizes {len(left_bytes)} vs {len(right_bytes)}"
        )
        for change in changes:
            print(f"CHANGE {change.path}: {change.before!r} -> {change.after!r}")
        if len(changes) == args.max_changes:
            print(f"... structural output limited to {args.max_changes} change(s)")
    return 0 if binary_identical else 1


def _import_nx10(args: argparse.Namespace) -> int:
    imported = load_nx10(args.path, profile=args.profile)
    document = imported.document
    report = imported.report
    native = serialize(document)
    if args.output:
        if args.output.resolve() == args.path.resolve():
            raise StepNXError("refusing to overwrite the NX10 import source")
        save_atomic(document, args.output, overwrite=args.force)

    result = {
        "source": str(args.path),
        "output": str(args.output) if args.output else None,
        "source_size": report.source_size,
        "output_size": len(native),
        "source_sha256": _sha256(imported.source_bytes),
        "output_sha256": _sha256(native),
        "semantically_lossless": report.is_semantically_lossless,
        "splits": report.splits,
        "blocks": report.blocks,
        "rows": report.rows,
        "note_cells": report.note_cells,
        "diagnostics": [
            {
                "kind": diagnostic.kind.value,
                "code": diagnostic.code,
                "message": diagnostic.message,
                "offset": diagnostic.offset,
                "path": diagnostic.path,
            }
            for diagnostic in report.diagnostics
        ],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "LOSSLESS" if report.is_semantically_lossless else "ATTENTION"
        suffix = f" -> {args.output}" if args.output else ""
        print(
            f"{status}: NX10 import {args.path}{suffix} "
            f"({report.splits} split(s), {report.blocks} block(s), {report.rows} row(s))"
        )
        for diagnostic in report.diagnostics:
            location = f" at 0x{diagnostic.offset:X}" if diagnostic.offset is not None else ""
            path = f" [{diagnostic.path}]" if diagnostic.path else ""
            print(
                f"{diagnostic.kind.value.upper()} {diagnostic.code}{location}{path}: "
                f"{diagnostic.message}"
            )
    return 0 if report.is_semantically_lossless else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stepnx", description="StepNX Studio lossless NX20 tools")
    parser.add_argument("--version", action="version", version="StepNX Studio core 0.1.0.dev0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="inspect an NX20/NFO document")
    inspect_parser.add_argument("path", type=Path)
    inspect_parser.add_argument("--profile", default="nxa-native")
    inspect_parser.add_argument("--row-storage", choices=("rich", "compact"), default="compact")
    inspect_parser.add_argument("--json", action="store_true")
    inspect_parser.set_defaults(handler=_inspect)

    roundtrip_parser = subparsers.add_parser("roundtrip", help="rebuild and compare an NX20/NFO document")
    roundtrip_parser.add_argument("path", type=Path)
    roundtrip_parser.add_argument("--output", "-o", type=Path)
    roundtrip_parser.add_argument("--profile", default="nxa-native")
    roundtrip_parser.add_argument("--row-storage", choices=("rich", "compact"), default="compact")
    roundtrip_parser.add_argument("--force", action="store_true")
    roundtrip_parser.add_argument("--backup", action="store_true")
    roundtrip_parser.add_argument("--json", action="store_true")
    roundtrip_parser.set_defaults(handler=_roundtrip)

    verify_parser = subparsers.add_parser("verify", help="verify byte-exact round-trip for files or folders")
    verify_parser.add_argument("paths", nargs="+")
    verify_parser.add_argument("--profile", default="nxa-native")
    verify_parser.add_argument("--row-storage", choices=("rich", "compact"), default="compact")
    verify_parser.add_argument("--strict-formats", action="store_true")
    verify_parser.add_argument("--max-errors", type=int, default=20)
    verify_parser.add_argument("--json", action="store_true")
    verify_parser.set_defaults(handler=_verify)

    validate_parser = subparsers.add_parser(
        "validate", help="validate the editable NX20/NFO model structure"
    )
    validate_parser.add_argument("path", type=Path)
    validate_parser.add_argument("--profile", default="nxa-native")
    validate_parser.add_argument("--row-storage", choices=("rich", "compact"), default="compact")
    validate_parser.add_argument("--max-issues", type=int, default=50)
    validate_parser.add_argument("--json", action="store_true")
    validate_parser.set_defaults(handler=_validate)

    diff_parser = subparsers.add_parser("diff", help="report binary and structural differences")
    diff_parser.add_argument("left", type=Path)
    diff_parser.add_argument("right", type=Path)
    diff_parser.add_argument("--profile", default="nxa-native")
    diff_parser.add_argument("--row-storage", choices=("rich", "compact"), default="compact")
    diff_parser.add_argument("--max-changes", type=int, default=100)
    diff_parser.add_argument("--json", action="store_true")
    diff_parser.set_defaults(handler=_diff)

    import_parser = subparsers.add_parser(
        "import-nx10",
        help="project an NX2/NX10 chart into a native NX20 document with diagnostics",
    )
    import_parser.add_argument("path", type=Path)
    import_parser.add_argument("--output", "-o", type=Path)
    import_parser.add_argument("--profile", default="nxa-native")
    import_parser.add_argument("--force", action="store_true")
    import_parser.add_argument("--json", action="store_true")
    import_parser.set_defaults(handler=_import_nx10)
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
