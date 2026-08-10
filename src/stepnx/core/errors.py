from __future__ import annotations


class StepNXError(Exception):
    """Base class for errors intended to reach a caller or CLI."""


class ParseError(StepNXError):
    def __init__(self, offset: int, label: str, detail: str, source: str | None = None):
        self.offset = offset
        self.label = label
        self.detail = detail
        self.source = source
        location = f"{source}:" if source else ""
        super().__init__(f"{location}0x{offset:X} [{label}] {detail}")


class UnsupportedFormatError(ParseError):
    """The input is recognized but is not handled by this codec."""


class ModelInvariantError(StepNXError):
    """A model mutation cannot be represented as a structurally valid NX20."""


class OutputExistsError(StepNXError):
    """An atomic save refused to replace an existing target."""

