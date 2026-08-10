from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from stepnx.core.errors import ParseError
from stepnx.core.scalars import RawScalar, RawU32, SourceSpan


ScalarT = TypeVar("ScalarT", bound=RawScalar)


@dataclass(frozen=True, slots=True)
class ParseLimits:
    max_columns: int = 64
    max_count: int = 10_000_000


class BinaryReader:
    def __init__(self, data: bytes, source: str | None = None):
        self.data = data
        self.source = source
        self.position = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.position

    def read_exact(self, size: int, label: str) -> tuple[bytes, SourceSpan]:
        start = self.position
        if size < 0 or start + size > len(self.data):
            raise ParseError(start, label, f"truncated: need {size} byte(s), have {self.remaining}", self.source)
        self.position += size
        return self.data[start : self.position], SourceSpan(start, self.position)

    def scalar(self, scalar_type: type[ScalarT], label: str) -> ScalarT:
        raw, span = self.read_exact(scalar_type._size, label)
        return scalar_type(raw, span)

    def count(self, label: str, limits: ParseLimits, minimum_item_size: int = 0) -> RawU32:
        count = self.scalar(RawU32, label)
        value = int(count.value)
        if value > limits.max_count:
            raise ParseError(count.span.start, label, f"unreasonable count {value}", self.source)
        if minimum_item_size and value > self.remaining // minimum_item_size:
            raise ParseError(
                count.span.start,
                label,
                f"{value} item(s) cannot fit in {self.remaining} remaining byte(s)",
                self.source,
            )
        return count
