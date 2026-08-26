from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from stepnx.authoring.audio import AudDecodeError, decode_aud


def _magic(source: bytes) -> str:
    raw = source[:16]
    text = "".join(chr(value) if 32 <= value < 127 else "." for value in raw)
    return f"{raw.hex()}  {text}"


def _is_intro_preview(path: Path, root: Path) -> bool:
    """Return whether *path* belongs to the non-authoring INTRO preview tree."""

    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0].casefold() == "intro"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit StepNX AUD decoder coverage across ENC1 and ENC2 files."
    )
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--include-intro",
        action="store_true",
        help="include /INTRO song-preview cuts in decoder coverage",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    discovered = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".aud", ".a"}
    )
    ignored_intro = (
        []
        if args.include_intro
        else [path for path in discovered if _is_intro_preview(path, root)]
    )
    paths = (
        discovered
        if args.include_intro
        else [path for path in discovered if not _is_intro_preview(path, root)]
    )

    ok = Counter()
    failed: dict[str, list[tuple[str, str]]] = defaultdict(list)
    enc1_headers: dict[str, list[str]] = defaultdict(list)

    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            source = path.read_bytes()
        except OSError as exc:
            failed["READ"].append((relative, str(exc)))
            continue

        magic = source[:4].upper().decode("ascii", errors="replace")
        if magic == "ENC1":
            enc1_headers[_magic(source)].append(relative)
        elif magic not in {"ENC2"}:
            magic = "OTHER"

        try:
            decode_aud(path)
        except AudDecodeError as exc:
            failed[magic].append((relative, str(exc)))
        else:
            ok[magic] += 1

    print(f"DISCOVERED: {len(discovered)}")
    if not args.include_intro:
        print(f"IGNORED_INTRO: {len(ignored_intro)}")
    print(f"TOTAL: {len(paths)}")
    print(f"ENC1_OK: {ok['ENC1']}")
    print(f"ENC1_FAIL: {len(failed['ENC1'])}")
    print(f"ENC2_OK: {ok['ENC2']}")
    print(f"ENC2_FAIL: {len(failed['ENC2'])}")
    print(f"OTHER_OK: {ok['OTHER']}")
    print(f"OTHER_FAIL: {len(failed['OTHER'])}")
    if failed["READ"]:
        print(f"READ_FAIL: {len(failed['READ'])}")

    for kind in ("ENC1", "ENC2", "OTHER", "READ"):
        entries = failed[kind]
        if not entries:
            continue
        print(f"{kind}_FAILURES:")
        for relative, message in entries:
            print(f"  {relative}: {message}")

    if enc1_headers:
        print(f"ENC1_HEADER_GROUPS: {len(enc1_headers)}")
        for magic_text, members in sorted(
            enc1_headers.items(), key=lambda item: (-len(item[1]), item[0])
        ):
            examples = "; ".join(members[:4])
            suffix = " ..." if len(members) > 4 else ""
            print(f"  {len(members):4d}  {magic_text}  {examples}{suffix}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
