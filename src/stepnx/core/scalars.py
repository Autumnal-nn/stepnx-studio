from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import ClassVar, Self


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid source span {self.start}:{self.end}")

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class RawScalar:
    """A scalar whose original byte representation remains authoritative."""

    raw: bytes
    span: SourceSpan | None = None

    _format: ClassVar[str]
    _size: ClassVar[int]

    def __post_init__(self) -> None:
        if len(self.raw) != self._size:
            raise ValueError(f"{type(self).__name__} needs {self._size} bytes, got {len(self.raw)}")
        if self.span is not None and self.span.size != self._size:
            raise ValueError(f"{type(self).__name__} span has size {self.span.size}, expected {self._size}")

    @property
    def value(self) -> int | float:
        return struct.unpack(self._format, self.raw)[0]

    @classmethod
    def from_value(cls, value: int | float) -> Self:
        return cls(struct.pack(cls._format, value), None)

    def with_value(self, value: int | float) -> Self:
        return type(self).from_value(value)

    @property
    def hex(self) -> str:
        return self.raw.hex().upper()


class RawU8(RawScalar):
    _format = "<B"
    _size = 1


class RawU16(RawScalar):
    _format = "<H"
    _size = 2


class RawU32(RawScalar):
    _format = "<I"
    _size = 4


class RawF32(RawScalar):
    _format = "<f"
    _size = 4

    @property
    def bits(self) -> int:
        return struct.unpack("<I", self.raw)[0]

    @classmethod
    def from_bits(cls, bits: int) -> Self:
        return cls(struct.pack("<I", bits), None)

    def with_bits(self, bits: int) -> Self:
        return type(self).from_bits(bits)

