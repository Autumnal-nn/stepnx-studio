from __future__ import annotations

from dataclasses import dataclass, replace

from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import NX20Document
from stepnx.core.scalars import RawU8


@dataclass(frozen=True, slots=True)
class SplitSelectionByte:
    """Typed projection of the first NX20 Split header byte.

    Runtime validation on official NXA charts shows that 0x80 and 0x40 are
    selector modes with precedence rather than two composable behaviors:
    whenever both bits are present, 0x80 wins. The lower five bits are a
    selection bank/group. The raw byte remains authoritative so malformed or
    historical combinations such as 0xC0 still round-trip exactly.
    """

    random_at_start: bool = False
    random_at_trigger: bool = False
    force_select: bool = False
    bank: int = 0

    @classmethod
    def from_raw(cls, value: int) -> "SplitSelectionByte":
        if not 0 <= value <= 0xFF:
            raise ValueError("Split selection byte must fit in one byte")
        return cls(
            random_at_start=bool(value & 0x80),
            random_at_trigger=bool(value & 0x40),
            force_select=bool(value & 0x20),
            bank=value & 0x1F,
        )

    @property
    def raw(self) -> int:
        if not 0 <= self.bank <= 0x1F:
            raise ValueError("Split random bank must be between 0 and 31")
        return (
            (0x80 if self.random_at_start else 0)
            | (0x40 if self.random_at_trigger else 0)
            | (0x20 if self.force_select else 0)
            | self.bank
        )

    @property
    def mode_label(self) -> str:
        modes: list[str] = []
        if self.random_at_start:
            modes.append("random at start")
            if self.random_at_trigger:
                modes.append("0x40 also set (overridden)")
        elif self.random_at_trigger:
            modes.append("random at trigger")
        if self.force_select:
            modes.append("force select")
        if not modes:
            modes.append("ordered")
        suffix = "" if self.bank == 0 else f", bank {self.bank}"
        return " + ".join(modes) + suffix

    def warnings(self, *, block_count: int) -> tuple[str, ...]:
        warnings: list[str] = []
        if block_count <= 1 and self.raw != 0:
            warnings.append(
                "This Split has only one Block, so selector flags/banking are normally redundant."
            )
        if self.bank and not (self.random_at_start or self.random_at_trigger):
            warnings.append(
                "A non-zero selection bank without either selector mode is unusual in the audited corpus."
            )
        if self.random_at_start and self.random_at_trigger:
            warnings.append(
                "Both 0x80 and 0x40 are encoded. Runtime validation shows that 0x80 overrides 0x40; "
                "official charts containing this combination include known broken implementations."
            )
        return tuple(warnings)


@dataclass(frozen=True, slots=True)
class SetSplitSelectionByte:
    split_id: int
    value: int

    def apply(self, document: NX20Document) -> NX20Document:
        if not 0 <= self.value <= 0xFF:
            raise ModelInvariantError("Split selection byte must be between 0x00 and 0xFF")
        changed = False
        splits = []
        for split in document.splits:
            if split.stable_id != self.split_id:
                splits.append(split)
                continue
            if changed:
                raise ModelInvariantError(f"duplicate Split stable ID {self.split_id}")
            changed = True
            splits.append(
                replace(split, raw_select=RawU8.from_value(self.value), span=None)
            )
        if not changed:
            raise ModelInvariantError(f"Split {self.split_id} does not exist")
        return replace(document, splits=tuple(splits))
