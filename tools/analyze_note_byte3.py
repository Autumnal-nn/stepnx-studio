from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from stepnx.codecs.nx20 import parse_bytes
from stepnx.core.model import NoteRow, PackedNoteRow


TYPE_NAMES = {
    0x1: "item",
    0x2: "division",
    0x3: "tap",
    0x7: "hold-head",
    0xB: "hold-body",
    0xF: "hold-tail",
}


def iter_files(root: Path):
    if root.is_file():
        yield root
        return
    for suffix in ("*.NX", "*.nx", "*.NFO", "*.nfo"):
        yield from root.rglob(suffix)


def scan(roots: list[Path]):
    value_counts = Counter()
    detail_counts = Counter()
    examples = defaultdict(list)
    files = parsed = nx10 = failed = 0

    seen: set[Path] = set()
    for root in roots:
        for path in iter_files(root):
            path = path.resolve()
            if path in seen:
                continue
            seen.add(path)
            files += 1
            try:
                payload = path.read_bytes()
            except OSError:
                failed += 1
                continue
            if payload[:4] != b"NX20":
                if payload[:4] == b"NX10":
                    nx10 += 1
                continue
            try:
                document = parse_bytes(payload, source=str(path), row_storage="compact")
            except Exception:
                failed += 1
                continue
            parsed += 1
            for split_index, split in enumerate(document.splits):
                for block_index, block in enumerate(split.blocks):
                    for row_index, row in enumerate(block.rows):
                        if not isinstance(row, (NoteRow, PackedNoteRow)):
                            continue
                        for lane in range(row.cell_count):
                            cell = row.cell(lane) if isinstance(row, PackedNoteRow) else row.cells[lane]
                            raw = cell.raw
                            note_type = raw[0] & 0x0F
                            if note_type == 0:
                                continue
                            low6 = raw[3] & 0x3F
                            slot = raw[3] >> 6
                            subtype = raw[2]
                            value_counts[low6] += 1
                            detail_counts[(low6, note_type, subtype, slot)] += 1
                            if len(examples[low6]) < 12:
                                examples[low6].append(
                                    (
                                        str(path),
                                        split_index,
                                        block_index,
                                        row_index,
                                        lane,
                                        raw.hex(" ").upper(),
                                    )
                                )
    return files, parsed, nx10, failed, value_counts, detail_counts, examples


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inventory NX20 raw[3] low-six-bit values and player-slot bits. "
            "For Division cells, low6 may be part of the 14-bit Division ID; "
            "the report therefore calls it low6 rather than assuming Brain semantics."
        )
    )
    parser.add_argument("roots", nargs="+", type=Path, help="NX20 file or corpus directory")
    parser.add_argument("--csv", type=Path, help="write detailed counts as CSV")
    args = parser.parse_args(argv)

    files, parsed, nx10, failed, values, details, examples = scan(args.roots)
    print(f"files={files} nx20_parsed={parsed} nx10_skipped={nx10} failed={failed}")
    print("\nraw[3] low6 distribution 0..63:")
    for value in range(64):
        count = values[value]
        if count or value <= 7:
            label = {
                0: "none/normal",
                1: "renderer/context",
                2: "unidentified",
                3: "unidentified",
                4: "unidentified",
                5: "unidentified",
                6: "incorrect/X",
                7: "correct/O",
            }.get(value, "raw")
            print(f"  {value:02d}: {count:10d}  {label}")

    for value in range(2, 6):
        print(f"\nExamples for low6={value:02d} ({values[value]} total):")
        if not examples[value]:
            print("  (none)")
        for path, split, block, row, lane, raw in examples[value]:
            print(
                f"  {raw}  split={split} block={block} row={row} lane={lane}  {path}"
            )

    if args.csv is not None:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["low6", "note_type", "type_name", "subtype", "player_slot", "count"]
            )
            for (low6, note_type, subtype, slot), count in sorted(details.items()):
                writer.writerow(
                    [low6, note_type, TYPE_NAMES.get(note_type, "unknown"), subtype, slot, count]
                )
        print(f"\nDetailed CSV: {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
