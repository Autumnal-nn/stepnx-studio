from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

TILE_SIZE = 96
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_BANK_NAME = re.compile(r"^[0-9]{2}$")
_STEP_EFFECT = re.compile(r"^(STEPFX[0-9]+)_([0-4])\.png$")


class NoteskinPackError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class HoldAtlasPlan:
    """Select terminal artwork or the repeatable shaft for a hold cell."""

    terminal_row: int | None
    shaft_above_terminal: bool
    shaft_below_terminal: bool
    repeat_shaft: bool


def hold_atlas_plan(note_type: int) -> HoldAtlasPlan:
    """Return the atlas composition for an NX hold cell.

    Terminal shaft fragments are clipped per source column so they meet the
    terminal silhouette without leaking behind its transparent pixels. Only a
    body cell stretches the shaft across its complete target.
    """

    if note_type == 0x7:
        return HoldAtlasPlan(
            terminal_row=1,
            shaft_above_terminal=False,
            shaft_below_terminal=True,
            repeat_shaft=False,
        )
    if note_type == 0xB:
        return HoldAtlasPlan(
            terminal_row=None,
            shaft_above_terminal=False,
            shaft_below_terminal=False,
            repeat_shaft=True,
        )
    if note_type == 0xF:
        return HoldAtlasPlan(
            terminal_row=0,
            shaft_above_terminal=True,
            shaft_below_terminal=False,
            repeat_shaft=False,
        )
    raise ValueError(f"unsupported hold note type: 0x{note_type:X}")


@dataclass(frozen=True, slots=True)
class PngAtlas:
    path: Path
    columns: int
    rows: int

    def tile(self, column: int, row: int) -> tuple[int, int, int, int]:
        if not 0 <= column < self.columns or not 0 <= row < self.rows:
            raise IndexError((column, row))
        return column * TILE_SIZE, row * TILE_SIZE, TILE_SIZE, TILE_SIZE


@dataclass(frozen=True, slots=True)
class NoteskinBank:
    bank_id: int
    animation: tuple[PngAtlas, ...]
    press_overlay: PngAtlas | None
    base: PngAtlas | None
    half_double_left: PngAtlas | None
    half_double_right: PngAtlas | None
    step_effects: tuple[Path, ...]

    @property
    def has_gameplay_feedback(self) -> bool:
        return all(
            item is not None
            for item in (
                self.press_overlay,
                self.base,
                self.half_double_left,
                self.half_double_right,
            )
        ) and len(self.step_effects) == 5


@dataclass(frozen=True, slots=True)
class LocalNoteskinPack:
    """Validated references to a private, user-supplied noteskin directory.

    Paths are retained in place.  The loader never copies or embeds the
    selected artwork in a workspace, recovery snapshot, or distribution.
    """

    root: Path
    banks: tuple[NoteskinBank, ...]
    division: PngAtlas | None
    item_animation: tuple[PngAtlas, ...]
    special_items: PngAtlas | None

    def bank(self, bank_id: int) -> NoteskinBank | None:
        return next((bank for bank in self.banks if bank.bank_id == bank_id), None)


def _png_size(path: Path) -> tuple[int, int]:
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError as exc:
        raise NoteskinPackError(f"cannot read noteskin image {path}: {exc}") from exc
    if len(header) < 24 or header[:8] != _PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise NoteskinPackError(f"noteskin image is not a valid PNG header: {path}")
    return struct.unpack(">II", header[16:24])


def _atlas(path: Path, columns: int, rows: int) -> PngAtlas:
    expected = columns * TILE_SIZE, rows * TILE_SIZE
    actual = _png_size(path)
    if actual != expected:
        raise NoteskinPackError(
            f"noteskin atlas {path} is {actual[0]}x{actual[1]}; "
            f"expected {expected[0]}x{expected[1]}"
        )
    return PngAtlas(path.resolve(), columns, rows)


def _optional_atlas(root: Path, name: str, columns: int, rows: int) -> PngAtlas | None:
    path = root / name
    return _atlas(path, columns, rows) if path.is_file() else None


def _load_step_effects(root: Path) -> tuple[Path, ...]:
    grouped: dict[str, dict[int, Path]] = {}
    for path in root.iterdir():
        if not path.is_file():
            continue
        match = _STEP_EFFECT.match(path.name)
        if match is not None:
            grouped.setdefault(match.group(1), {})[int(match.group(2))] = path
    if not grouped:
        return ()
    if len(grouped) != 1:
        raise NoteskinPackError(f"bank {root.name} contains multiple STEPFX sequences")
    prefix, frames = next(iter(grouped.items()))
    if set(frames) != set(range(5)):
        raise NoteskinPackError(f"{root.name}/{prefix} must contain frames 0 through 4")
    result = tuple(frames[index].resolve() for index in range(5))
    for path in result:
        size = _png_size(path)
        if size != (512, 512):
            raise NoteskinPackError(
                f"step effect {path} is {size[0]}x{size[1]}; expected 512x512"
            )
    return result


def _load_bank(root: Path) -> NoteskinBank:
    animation = _animation_sequence(root, 6, 5, 3)
    return NoteskinBank(
        bank_id=int(root.name),
        animation=animation,
        press_overlay=_optional_atlas(root, "6.png", 5, 2),
        base=_optional_atlas(root, "BASE.png", 5, 2),
        half_double_left=_optional_atlas(root, "HD1.png", 5, 2),
        half_double_right=_optional_atlas(root, "HD2.png", 5, 2),
        step_effects=_load_step_effects(root),
    )


def _animation_sequence(
    root: Path, frames: int, columns: int, rows: int
) -> tuple[PngAtlas, ...]:
    """Load either one static atlas or a complete numbered animation."""

    existing = [root / f"{frame}.png" for frame in range(frames)]
    present = [path.is_file() for path in existing]
    if present[0] and not any(present[1:]):
        return (_atlas(existing[0], columns, rows),)
    if not all(present):
        missing = ", ".join(
            path.name for path, exists in zip(existing, present) if not exists
        )
        raise NoteskinPackError(
            f"{root.name} animation must contain only 0.png or frames 0 through "
            f"{frames - 1}; missing {missing}"
        )
    return tuple(_atlas(path, columns, rows) for path in existing)


def load_noteskin_pack(path: str | Path) -> LocalNoteskinPack:
    root = Path(path).resolve()
    if not root.is_dir():
        raise NoteskinPackError(f"noteskin root is not a directory: {root}")
    bank_roots = sorted(
        (
            item
            for item in root.iterdir()
            if item.is_dir() and _BANK_NAME.match(item.name)
        ),
        key=lambda item: int(item.name),
    )
    if not bank_roots:
        raise NoteskinPackError("noteskin pack has no two-digit bank directories")
    banks = tuple(_load_bank(bank_root) for bank_root in bank_roots)

    division_root = root / "DIVISION"
    division = (
        _optional_atlas(division_root, "0.png", 5, 1)
        if division_root.is_dir()
        else None
    )
    item_root = root / "ITEM"
    item_animation = ()
    if item_root.is_dir() and (item_root / "0.png").is_file():
        item_animation = _animation_sequence(item_root, 6, 32, 2)
    special_items = (
        _optional_atlas(item_root, "SPECIAL.png", 32, 3)
        if item_root.is_dir()
        else None
    )
    return LocalNoteskinPack(
        root=root,
        banks=banks,
        division=division,
        item_animation=item_animation,
        special_items=special_items,
    )
