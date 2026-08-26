from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TrailerEvidence(str, Enum):
    RUNTIME_CONFIRMED = "runtime-confirmed"
    OFFICIAL_CORPUS = "official-corpus"


@dataclass(frozen=True, slots=True)
class TrailerFieldDefinition:
    base_id: int
    label: str
    evidence: TrailerEvidence
    localized: bool = False


# These definitions are deliberately profile-specific. NXA metadata ID 20,
# for example, has different semantics and NXA has no later-generation sized
# trailer at all.
_FIESTA2_FIELDS = (
    TrailerFieldDefinition(
        20,
        "V resource override",
        TrailerEvidence.RUNTIME_CONFIRMED,
    ),
    TrailerFieldDefinition(
        1003,
        "Resource/reference string",
        TrailerEvidence.RUNTIME_CONFIRMED,
    ),
    TrailerFieldDefinition(1100, "Trailer string field 1100", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1102, "Trailer string field 1102", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(
        1103,
        "Localized mission text",
        TrailerEvidence.RUNTIME_CONFIRMED,
        localized=True,
    ),
    TrailerFieldDefinition(1150, "Mission condition string", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1151, "Trailer string field 1151", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1199, "Trailer string field 1199", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(
        1203,
        "Localized mission text",
        TrailerEvidence.RUNTIME_CONFIRMED,
        localized=True,
    ),
    TrailerFieldDefinition(1250, "Mission condition string", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1299, "Trailer string field 1299", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(
        1303,
        "Localized mission text",
        TrailerEvidence.RUNTIME_CONFIRMED,
        localized=True,
    ),
    TrailerFieldDefinition(1350, "Mission condition string", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1399, "Trailer string field 1399", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(
        1403,
        "Localized mission text",
        TrailerEvidence.RUNTIME_CONFIRMED,
        localized=True,
    ),
    TrailerFieldDefinition(1450, "Mission condition string", TrailerEvidence.OFFICIAL_CORPUS),
)

# Header 1008 first appears in the XX-and-later branch. R!SE names the runtime
# field mpStepArtist, and official R!SE charts store a trailer-relative offset
# to a NUL-terminated UTF-8 Step Artist string. Keep it in the existing modern
# profile instead of adding a one-off R!SE profile.
_MODERN_FIELDS = (
    *_FIESTA2_FIELDS,
    TrailerFieldDefinition(
        1008,
        "Step Artist (XX and beyond)",
        TrailerEvidence.RUNTIME_CONFIRMED,
    ),
)


_BY_PROFILE = {
    "fiesta2": {item.base_id: item for item in _FIESTA2_FIELDS},
    "prime2": {item.base_id: item for item in _MODERN_FIELDS},
}


def trailer_field_definition(
    profile: str, base_id: int
) -> TrailerFieldDefinition | None:
    return _BY_PROFILE.get(profile, {}).get(base_id)


def trailer_field_definitions(profile: str) -> tuple[TrailerFieldDefinition, ...]:
    fields = _BY_PROFILE.get(profile, {})
    return tuple(fields[key] for key in sorted(fields))
