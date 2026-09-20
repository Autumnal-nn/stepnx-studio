from __future__ import annotations

import argparse
import struct
from collections import Counter
from pathlib import Path


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError(f"u32 outside file at 0x{offset:X}")
    return struct.unpack_from("<I", data, offset)[0]


def inspect(path: Path) -> tuple[str, str] | None:
    data = path.read_bytes()
    if len(data) < 24 or data[:4] != b"NX20":
        return None

    trailer_size = _u32(data, len(data) - 4)
    if trailer_size < 4 or trailer_size > len(data):
        return ("other", "no valid sized trailer")
    trailer_start = len(data) - trailer_size

    columns = _u32(data, 8)
    lightmap = bool(_u32(data, 12) or columns == 3)
    header_count = _u32(data, 16)
    pos = 20
    metadata = []
    for _ in range(header_count):
        metadata.append((_u32(data, pos), _u32(data, pos + 4)))
        pos += 8
    if (20, 0) not in metadata:
        return None

    split_count = _u32(data, pos)
    pos += 4
    for split_index in range(split_count):
        pos += 4
        meta_count = _u32(data, pos)
        pos += 4 + meta_count * 8
        block_count = _u32(data, pos)
        pos += 4

        for block_index in range(block_count):
            pos += 24
            division_count = _u32(data, pos)
            pos += 4 + division_count * 8
            row_count = _u32(data, pos)
            pos += 4

            for row_index in range(row_count):
                is_final = (
                    split_index == split_count - 1
                    and block_index == block_count - 1
                    and row_index == row_count - 1
                )
                if is_final and pos == trailer_start:
                    repair = "00 00 00 00" if lightmap else "80 00 00 00"
                    return (
                        "recoverable",
                        f"final row {row_index}/{row_count} omitted at 0x{pos:X}; "
                        f"trailer={data[trailer_start:].hex(' ')}; repair={repair}",
                    )

                if pos + 4 > len(data):
                    return ("other", f"truncated row header at 0x{pos:X}")
                first = data[pos : pos + 4]
                pos += 4
                if first[0] & 0x80 or lightmap:
                    continue
                remaining = (columns - 1) * 4
                if pos + remaining > len(data):
                    return (
                        "other",
                        f"row payload overruns file at 0x{pos:X}; "
                        f"need {remaining}, have {len(data) - pos}",
                    )
                pos += remaining

    if pos == trailer_start:
        return ("well-formed", f"body ends at sized trailer 0x{trailer_start:X}")
    if pos > trailer_start:
        return (
            "other",
            f"parsed body crosses trailer start by {pos - trailer_start} byte(s)",
        )
    return (
        "other",
        f"{trailer_start - pos} unexplained byte(s) between body and trailer",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit Prime 1/Omnimix NX20 files for the legacy omitted-terminal-row defect."
    )
    parser.add_argument("root", type=Path)
    args = parser.parse_args()

    paths = [args.root] if args.root.is_file() else sorted(args.root.rglob("*.NX"))
    counts: Counter[str] = Counter()
    for path in paths:
        try:
            result = inspect(path)
        except (OSError, ValueError, struct.error) as exc:
            counts["error"] += 1
            print(f"ERROR       {path}: {exc}")
            continue
        if result is None:
            continue
        kind, detail = result
        counts[kind] += 1
        print(f"{kind.upper():11} {path}: {detail}")

    print()
    for kind in ("recoverable", "well-formed", "other", "error"):
        if counts[kind]:
            print(f"{kind:11}: {counts[kind]}")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
