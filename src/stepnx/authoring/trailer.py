from __future__ import annotations

from dataclasses import dataclass, replace

from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import EnvelopeKind, NX20Document

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


def project_trailer_strings(document: NX20Document) -> TrailerProjection:
    if document.envelope.kind is not EnvelopeKind.SIZED_TRAILER:
        return TrailerProjection((), ())
    payload = document.envelope.payload
    strings: list[TrailerString] = []
    diagnostics: list[TrailerDiagnostic] = []
    for entry in document.header_metadata:
        metadata_id = int(entry.meta_id.value)
        base_id = metadata_id & 0xFFFF
        if base_id not in TRAILER_STRING_BASE_IDS:
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


@dataclass(frozen=True, slots=True)
class SetTrailerStringSameSize:
    metadata_stable_id: int
    text: str

    def apply(self, document: NX20Document) -> NX20Document:
        projection = project_trailer_strings(document)
        matches = [
            item
            for item in projection.strings
            if item.metadata_stable_id == self.metadata_stable_id
        ]
        if len(matches) != 1:
            raise ModelInvariantError(
                f"expected one safe trailer string for metadata stable ID {self.metadata_stable_id}, found {len(matches)}"
            )
        target = matches[0]
        if not target.authorable:
            raise ModelInvariantError(
                "trailer string encoding is unknown and cannot be edited safely"
            )
        encoded = self.text.encode("utf-8")
        if len(encoded) != len(target.raw):
            raise ModelInvariantError(
                "trailer string edit must preserve encoded byte length; relocation is not proven safe"
            )
        payload = bytearray(document.envelope.payload)
        payload[target.offset : target.offset + len(encoded)] = encoded
        raw = bytes(payload) + document.envelope.raw[-4:]
        return replace(
            document, envelope=replace(document.envelope, raw=raw, span=None)
        )
