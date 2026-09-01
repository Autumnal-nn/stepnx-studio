from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TrailerEvidence(str, Enum):
    RUNTIME_CONFIRMED = "runtime-confirmed"
    OFFICIAL_CORPUS = "official-corpus"
    STRONGLY_INFERRED = "strongly-inferred"


@dataclass(frozen=True, slots=True)
class TrailerFieldDefinition:
    base_id: int
    label: str
    evidence: TrailerEvidence
    localized: bool = False


# Fiesta 2 labels below are intentionally more specific than Prime 2.  They are
# backed by repeated placement/content patterns in the supplied official corpus;
# the three *99 failure/break predicates are strong structural inferences rather
# than runtime-confirmed names.
_FIESTA2_FIELDS = (
    TrailerFieldDefinition(20, "V resource override", TrailerEvidence.RUNTIME_CONFIRMED),
    TrailerFieldDefinition(
        1003,
        "Co-op companion chart reference",
        TrailerEvidence.OFFICIAL_CORPUS,
    ),
    TrailerFieldDefinition(
        1100,
        "Mission name",
        TrailerEvidence.OFFICIAL_CORPUS,
        localized=True,
    ),
    TrailerFieldDefinition(
        1102,
        "Mission short description / banner",
        TrailerEvidence.OFFICIAL_CORPUS,
    ),
    TrailerFieldDefinition(
        1103,
        "Mission objective / full description",
        TrailerEvidence.RUNTIME_CONFIRMED,
        localized=True,
    ),
    TrailerFieldDefinition(1150, "Floor 1 condition", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1151, "Condition 2", TrailerEvidence.STRONGLY_INFERRED),
    TrailerFieldDefinition(
        1199,
        "Floor 1 failure / break predicate",
        TrailerEvidence.STRONGLY_INFERRED,
    ),
    TrailerFieldDefinition(
        1203,
        "Floor 2 objective",
        TrailerEvidence.OFFICIAL_CORPUS,
        localized=True,
    ),
    TrailerFieldDefinition(1250, "Floor 2 condition", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(
        1299,
        "Floor 2 failure / break predicate",
        TrailerEvidence.STRONGLY_INFERRED,
    ),
    TrailerFieldDefinition(
        1303,
        "Floor 3 objective",
        TrailerEvidence.OFFICIAL_CORPUS,
        localized=True,
    ),
    TrailerFieldDefinition(1350, "Floor 3 condition", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(
        1399,
        "Floor 3 failure / break predicate",
        TrailerEvidence.STRONGLY_INFERRED,
    ),
    TrailerFieldDefinition(
        1403,
        "Floor 4 objective",
        TrailerEvidence.OFFICIAL_CORPUS,
        localized=True,
    ),
    TrailerFieldDefinition(1450, "Floor 4 condition", TrailerEvidence.OFFICIAL_CORPUS),
)

# Prime 2 reuses the storage family, but not every Fiesta 2 label carries over.
# In particular, 1100/1103 can duplicate objective strings. Keep conservative
# names here instead of smuggling Fiesta 2 semantics into the modern profile.
_PRIME2_FIELDS = (
    TrailerFieldDefinition(20, "V resource override", TrailerEvidence.RUNTIME_CONFIRMED),
    TrailerFieldDefinition(1003, "Resource/reference string", TrailerEvidence.RUNTIME_CONFIRMED),
    TrailerFieldDefinition(1100, "Localized mission/objective text", TrailerEvidence.OFFICIAL_CORPUS, localized=True),
    TrailerFieldDefinition(1102, "Trailer string field 1102", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1103, "Localized mission/objective text", TrailerEvidence.RUNTIME_CONFIRMED, localized=True),
    TrailerFieldDefinition(1150, "Mission condition string", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1151, "Trailer string field 1151", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1199, "Trailer string field 1199", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1203, "Localized mission text", TrailerEvidence.RUNTIME_CONFIRMED, localized=True),
    TrailerFieldDefinition(1250, "Mission condition string", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1299, "Trailer string field 1299", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1303, "Localized mission text", TrailerEvidence.RUNTIME_CONFIRMED, localized=True),
    TrailerFieldDefinition(1350, "Mission condition string", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1399, "Trailer string field 1399", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(1403, "Localized mission text", TrailerEvidence.RUNTIME_CONFIRMED, localized=True),
    TrailerFieldDefinition(1450, "Mission condition string", TrailerEvidence.OFFICIAL_CORPUS),
    TrailerFieldDefinition(
        1008,
        "Step Artist (XX and beyond)",
        TrailerEvidence.RUNTIME_CONFIRMED,
    ),
)


_BY_PROFILE = {
    "fiesta2": {item.base_id: item for item in _FIESTA2_FIELDS},
    "prime2": {item.base_id: item for item in _PRIME2_FIELDS},
}


def trailer_field_definition(
    profile: str, base_id: int
) -> TrailerFieldDefinition | None:
    return _BY_PROFILE.get(profile, {}).get(base_id)


def trailer_field_definitions(profile: str) -> tuple[TrailerFieldDefinition, ...]:
    fields = _BY_PROFILE.get(profile, {})
    return tuple(fields[key] for key in sorted(fields))
