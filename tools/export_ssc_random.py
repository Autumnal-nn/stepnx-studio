from __future__ import annotations

import argparse
import json
from pathlib import Path

from stepnx.authoring.random_state import RandomPoolPolicy
from stepnx.codecs.nx20 import load
from stepnx.exporters import SscSongInfo, compile_ssc_export, render_compiled_simfile


def _write_text(target: Path, text: str, *, force: bool) -> None:
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists; pass --force to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".stepnx-tmp")
    temporary.write_bytes(text.encode("utf-8"))
    temporary.replace(target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Developer probe for the semantic NX -> XSanity random compiler. "
            "The default profile now requests exact marginal random probabilities "
            "up to the known 2520-helper corpus outliers."
        )
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--output", "-o", type=Path)
    parser.add_argument("--profile", default="nxa-native")
    parser.add_argument("--description")
    parser.add_argument("--title")
    parser.add_argument("--artist", default="")
    parser.add_argument("--music", default="")
    parser.add_argument("--max-helpers", type=int, default=2520)
    parser.add_argument("--max-probability-error-pp", type=float, default=0.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = RandomPoolPolicy(
        max_probability_error=args.max_probability_error_pp / 100.0,
        max_helpers=args.max_helpers,
    )
    document = load(args.path, profile=args.profile)
    report = compile_ssc_export(
        document,
        description=args.description or args.path.name,
        policy=policy,
    )
    song = SscSongInfo(
        title=args.title or args.path.stem,
        artist=args.artist,
        music=args.music,
    )
    target = args.output or args.path.with_suffix(".ssc")
    text = render_compiled_simfile(report, song)
    _write_text(target, text, force=args.force)

    analysis = report.program.analysis
    pool = report.program.pool
    size_bytes = len(text.encode("utf-8"))
    result = {
        "source": str(args.path),
        "written": str(target),
        "output_bytes": size_bytes,
        "random_decisions": len(analysis.random_split_indices),
        "random_windows": report.window_count,
        "bank_episodes": len(analysis.bank_episodes),
        "max_live_banks": analysis.max_live_banks,
        "helper_count": report.helper_count,
        "exact_helper_count": pool.exact_helper_count,
        "exact_probabilities": report.exact_probabilities,
        "max_probability_error_pp": report.max_probability_error * 100.0,
        "diagnostics": [
            {
                "code": item.code,
                "message": item.message,
                "occurrences": item.occurrences,
                "split_index": item.split_index,
            }
            for item in report.diagnostics
        ],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        exact = "exact marginals" if report.exact_probabilities else "approximate"
        print(
            f"wrote {target}: {report.helper_count} helper(s), "
            f"{report.window_count} window(s), "
            f"{len(analysis.random_split_indices)} random decision(s), "
            f"{exact}, {size_bytes / (1024 * 1024):.2f} MiB"
        )
        if not report.exact_probabilities:
            print(
                f"  exact helpers={pool.exact_helper_count}; "
                f"maximum error={report.max_probability_error * 100:.3f} pp"
            )
        for diagnostic in report.diagnostics:
            suffix = f" (x{diagnostic.occurrences})" if diagnostic.occurrences > 1 else ""
            print(f"  {diagnostic.code}: {diagnostic.message}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
