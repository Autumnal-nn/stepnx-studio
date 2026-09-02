from __future__ import annotations

from dataclasses import dataclass, replace

from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import NX20Document
from stepnx.core.scalars import RawU8


@dataclass(frozen=True, slots=True)
class SplitSelectionByte:
    """Typed projection of the first NX20 Split header byte.

    The selector byte is stateful rather than two variants of random selection:

    - ``0x80`` performs a random selection when the Split is entered;
    - ``0x40`` is a follower flag: for a non-zero bank it reuses the most recent
      Block index selected for that bank;
    - the lower five bits identify the selection bank/group;
    - ``0x20`` retains the independently observed force/select behavior.

    A bank may therefore be meaningful even when neither ``0x80`` nor ``0x40``
    is set on the current Split. A conditioned/manual selector such as ``0x01``
    records its chosen Block index for bank 1, and a following ``0x41`` reuses
    that selection. The raw byte remains authoritative so every value, including
    historical combinations such as ``0xC0``, still round-trips exactly.

    ``random_at_trigger`` is retained as the internal field name for API
    compatibility with existing snapshot/tests, but its semantic projection is
    exposed as :attr:`follower` and it must not be presented as a random mode.
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
    def follower(self) -> bool:
        """Whether this Split follows the latest selection for its bank."""

        return bool(self.random_at_trigger)

    @property
    def raw(self) -> int:
        if not 0 <= self.bank <= 0x1F:
            raise ValueError("Split selection bank must be between 0 and 31")
        return (
            (0x80 if self.random_at_start else 0)
            | (0x40 if self.follower else 0)
            | (0x20 if self.force_select else 0)
            | self.bank
        )

    @property
    def mode_label(self) -> str:
        modes: list[str] = []
        if self.random_at_start:
            modes.append("random at start")
            if self.follower:
                modes.append("follower flag also set (0x80 precedence)")
        elif self.follower:
            modes.append("follower block")
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
        # A non-zero bank without 0x80/0x40 is valid and meaningful. Conditions
        # or an explicit active candidate may make the selection, and later
        # follower Splits reuse that Block index for the same bank.
        if self.random_at_start and self.follower:
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
