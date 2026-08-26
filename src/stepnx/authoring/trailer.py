from __future__ import annotations

import struct
from dataclasses import dataclass, replace

from stepnx.authoring.trailer_registry import trailer_field_definition
from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import EnvelopeKind, NX20Document
from stepnx.core.scalars import RawU32

# Phase 7 accepted these corpus-proven offset families before the engine-profile
# registry existed.  Keep them readable for older/synthetic documents while
# profile-specific additions such as Fiesta 2 GM20 and GM1003 are resolved by
# trailer_registry.
TRAILER_STRING_BASE_IDS = frozenset(
    {1100, 1102, 1103, 1150, 1151, 1199, 1203, 1250, 1299, 1303, 1350, 1399, 1403, 1450}
)


@dataclass(frozen=True, slots=True)
class TrailerString:
    metadata_stable_id: int
    metadata_id: int
    base_field_id: int
    variant_index: int
    offset: int
    raw: bytes
    text: str | None

    @property
    def authorable(self) -> bool:
        return self.text is not None


@dataclass(frozen=True, slots=True)
class TrailerDiagnostic:
    metadata_stable_id: int
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class TrailerProjection:
    strings: tuple[TrailerString, ...]
    diagnostics: tuple[TrailerDiagnostic, ...]


def _is_trailer_string_field(document: NX20Document, metadata_id: int) -> bool:
    base_id = metadata_id & 0xFFFF
    return (
        base_id in TRAILER_STRING_BASE_IDS
        or trailer_field_definition(document.profile, base_id) is not None
    )


def project_trailer_strings(document: NX20Document) -> TrailerProjection:
    if document.envelope.kind is not EnvelopeKind.SIZED_TRAILER:
        return TrailerProjection((), ())
    payload = document.envelope.payload
    strings: list[TrailerString] = []
    diagnostics: list[TrailerDiagnostic] = []
    for entry in document.header_metadata:
        metadata_id = int(entry.meta_id.value)
        base_id = metadata_id & 0xFFFF
        if not _is_trailer_string_field(document, metadata_id):
            continue
        offset = int(entry.value.value)
        if not 0 <= offset < len(payload):
            diagnostics.append(
                TrailerDiagnostic(
                    entry.stable_id,
                    "trailer.offset-outside",
                    f"metadata 0x{metadata_id:08X} points to {offset}, outside {len(payload)}-byte payload",
                )
            )
            continue
        end = payload.find(b"\x00", offset)
        if end < 0:
            diagnostics.append(
                TrailerDiagnostic(
                    entry.stable_id,
                    "trailer.unterminated-string",
                    f"metadata 0x{metadata_id:08X} has no NUL terminator before the size marker",
                )
            )
            continue
        raw = payload[offset:end]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = None
            diagnostics.append(
                TrailerDiagnostic(
                    entry.stable_id,
                    "trailer.encoding-unknown",
                    f"metadata 0x{metadata_id:08X} target is not valid UTF-8 and remains raw-only",
                )
            )
        strings.append(
            TrailerString(
                entry.stable_id,
                metadata_id,
                base_id,
                metadata_id >> 16,
                offset,
                raw,
                text,
            )
        )
    return TrailerProjection(tuple(strings), tuple(diagnostics))


def _target_string(document: NX20Document, metadata_stable_id: int) -> TrailerString:
    projection = project_trailer_strings(document)
    matches = [
        item
        for item in projection.strings
        if item.metadata_stable_id == metadata_stable_id
    ]
    if len(matches) != 1:
        raise ModelInvariantError(
            f"expected one safe trailer string for metadata stable ID {metadata_stable_id}, found {len(matches)}"
        )
    target = matches[0]
    if not target.authorable:
        raise ModelInvariantError(
            "trailer string encoding is unknown and cannot be edited safely"
        )
    return target


@dataclass(frozen=True, slots=True)
class SetTrailerStringSameSize:
    metadata_stable_id: int
    text: str

    def apply(self, document: NX20Document) -> NX20Document:
        target = _target_string(document, self.metadata_stable_id)
        encoded = self.text.encode("utf-8")
        if len(encoded) != len(target.raw):
            raise ModelInvariantError(
                "trailer string edit must preserve encoded byte length; use relocation for a length-changing edit"
            )
        payload = bytearray(document.envelope.payload)
        payload[target.offset : target.offset + len(encoded)] = encoded
        raw = bytes(payload) + document.envelope.raw[-4:]
        return replace(
            document, envelope=replace(document.envelope, raw=raw, span=None)
        )


def _aligned_storage_end(payload: bytes, target: TrailerString) -> int:
    """Return the end of an official aligned string slot or reject relocation.

    Later-generation corpus trailers store UTF-8/NUL strings with zero padding
    to a four-byte boundary.  Same-size edits do not need this invariant, but a
    length-changing edit does: preserving a multiple-of-four displacement keeps
    every later official string boundary aligned.
    """

    if target.offset % 4:
        raise ModelInvariantError(
            "length-changing trailer edit requires a four-byte-aligned official string offset"
        )
    terminator = target.offset + len(target.raw)
    if terminator >= len(payload) or payload[terminator] != 0:
        raise ModelInvariantError("trailer string lost its NUL terminator")
    storage_end = (terminator + 1 + 3) & ~3
    if storage_end > len(payload):
        raise ModelInvariantError("trailer string padding extends outside the payload")
    if any(payload[terminator + 1 : storage_end]):
        raise ModelInvariantError(
            "length-changing trailer edit requires zero alignment padding"
        )
    return storage_end


def _looks_like_unknown_pointer(payload: bytes, value: int) -> bool:
    if value < 0 or value >= len(payload) or value % 4:
        return False
    end = payload.find(b"\x00", value)
    if end < 0:
        return False
    try:
        payload[value:end].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class SetTrailerString:
    """Edit a UTF-8 trailer string, relocating later proven offsets if needed.

    Relocation is intentionally conservative.  It is enabled only for the
    aligned UTF-8/NUL pool shape observed throughout the supplied Fiesta 2 and
    Prime 2 corpora.  A header metadata value from an untyped field that looks
    like a downstream string pointer blocks the edit instead of being guessed.
    """

    metadata_stable_id: int
    text: str

    def apply(self, document: NX20Document) -> NX20Document:
        if document.envelope.kind is not EnvelopeKind.SIZED_TRAILER:
            raise ModelInvariantError("length-changing trailer edits require a sized trailer")
        target = _target_string(document, self.metadata_stable_id)
        encoded = self.text.encode("utf-8")
        if len(encoded) == len(target.raw):
            return SetTrailerStringSameSize(self.metadata_stable_id, self.text).apply(document)

        payload = document.envelope.payload
        old_storage_end = _aligned_storage_end(payload, target)
        old_storage_size = old_storage_end - target.offset
        new_storage_size = (len(encoded) + 1 + 3) & ~3
        replacement = encoded + b"\x00" + b"\x00" * (new_storage_size - len(encoded) - 1)
        delta = new_storage_size - old_storage_size

        # Refuse relocation when an untyped header field plausibly points into
        # the region that would move.  This is conservative by design: a false
        # positive costs one edit; a false negative silently corrupts a chart.
        for entry in document.header_metadata:
            metadata_id = int(entry.meta_id.value)
            value = int(entry.value.value)
            if _is_trailer_string_field(document, metadata_id):
                continue
            if value >= old_storage_end and _looks_like_unknown_pointer(payload, value):
                raise ModelInvariantError(
                    f"untyped header metadata 0x{metadata_id:08X} may point to trailer offset {value}; relocation is blocked"
                )

        new_payload = payload[: target.offset] + replacement + payload[old_storage_end:]
        new_metadata = []
        for entry in document.header_metadata:
            metadata_id = int(entry.meta_id.value)
            if not _is_trailer_string_field(document, metadata_id):
                new_metadata.append(entry)
                continue
            value = int(entry.value.value)
            if not 0 <= value < len(payload):
                raise ModelInvariantError(
                    f"metadata 0x{metadata_id:08X} has an invalid trailer offset {value}; relocation is blocked"
                )
            if target.offset < value < old_storage_end:
                raise ModelInvariantError(
                    f"metadata 0x{metadata_id:08X} points inside the edited trailer string slot"
                )
            if value >= old_storage_end:
                entry = replace(entry, value=RawU32.from_value(value + delta), span=None)
            new_metadata.append(entry)

        marker = struct.pack("<I", len(new_payload) + 4)
        return replace(
            document,
            header_metadata=tuple(new_metadata),
            envelope=replace(document.envelope, raw=new_payload + marker, span=None),
        )
