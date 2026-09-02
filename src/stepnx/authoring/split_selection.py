from __future__ import annotations

from dataclasses import dataclass, replace

from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import NX20Document
from stepnx.core.scalars import RawU8


@dataclass(frozen=True, slots=True)
class SplitSelectionByte:
    """Typed projection of the first NX20 Split header byte.

    Selector timing and bank semantics are distinct:

    - ``0x80`` preselects a random Block when the chart is loaded;
    - ``0x40`` attempts to reuse the latest Block index stored for the encoded
      bank;
    - banks are ``1..31``. Lower bits ``0`` mean *no bank*, not "bank 0";
    - therefore raw ``0x40`` has no bank to follow and falls back to a fresh
      random selection when that Split is reached;
    - ``0x41..0x5F`` are genuine followers for banks ``1..31``;
    - a banked Split such as ``0x01`` may establish its bank state through a
      condition/active candidate, which a later ``0x41`` then reuses;
    - ``0x20`` requests a block-condition recalculation at Split start. G/W/A/B/C
      Division arrows already force their own block verification; other Division
      Metadata requires this bit for Split-start runtime re-evaluation.

    The raw byte remains authoritative, including combinations such as ``0xC0``.
    ``random_at_trigger`` is retained as the internal field name for API
    compatibility, but user-facing terminology distinguishes the unbanked
    block-start random fallback from banked follower behavior.
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
    def has_bank(self) -> bool:
        return self.bank != 0

    @property
    def follower(self) -> bool:
        """Whether 0x40 can follow an actual bank (1..31)."""

        return bool(self.random_at_trigger and self.has_bank)

    @property
    def random_at_block_start(self) -> bool:
        """Whether 0x40 has no bank and therefore uses its random fallback."""

        return bool(self.random_at_trigger and not self.has_bank)

    @property
    def raw(self) -> int:
        if not 0 <= self.bank <= 0x1F:
            raise ValueError("Split selection bank must be between 0 and 31")
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
            modes.append("random at chart load")
            if self.random_at_trigger:
                extra = "follower flag" if self.has_bank else "block-start random flag"
                modes.append(f"{extra} also set (0x80 precedence)")
        elif self.random_at_block_start:
            modes.append("random at block start")
        elif self.follower:
            modes.append("follower block")
        if self.force_select:
            modes.append("force select")
        if not modes:
            modes.append("ordered")
        suffix = "" if not self.has_bank else f", bank {self.bank}"
        return " + ".join(modes) + suffix

    def warnings(self, *, block_count: int) -> tuple[str, ...]:
        warnings: list[str] = []
        if block_count <= 1 and self.raw != 0:
            warnings.append(
                "This Split has only one Block, so selector flags/banking are normally redundant."
            )
        # A non-zero bank without 0x80/0x40 is valid. Conditions or an explicit
        # active candidate can establish the bank state for a later follower.
        if self.random_at_trigger and not self.has_bank and not self.random_at_start:
            warnings.append(
                "Follower block without a set bank defaults to random at split start"
            )
        if self.random_at_start and self.random_at_trigger:
            warnings.append(
                "Both 0x80 and 0x40 are encoded. Runtime validation shows that 0x80 takes precedence; "
                "the raw combination is preserved without normalization."
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
