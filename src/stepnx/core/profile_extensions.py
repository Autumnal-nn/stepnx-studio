from __future__ import annotations

from dataclasses import replace

from stepnx.core.profiles import (
    Evidence,
    MetadataDefinition,
    MetadataScope,
    PROFILES,
    ValueChoice,
    ValueKind,
    profile_capabilities,
    profile_metadata,
)


_HEADER = frozenset((MetadataScope.HEADER,))


def _flag_definition(
    meta_id: int,
    label: str,
    description: str,
    *,
    evidence: Evidence = Evidence.RUNTIME_CONFIRMED,
    authorable: bool = True,
) -> MetadataDefinition:
    return MetadataDefinition(
        meta_id,
        label,
        _HEADER,
        ValueKind.ENUM,
        evidence,
        description=description,
        minimum=1,
        maximum=1,
        choices=(ValueChoice(1, "On"),),
        authorable=authorable,
    )


def install_profile_extensions() -> None:
    """Apply evidence-backed family labels and finalized Fiesta+ Header semantics.

    Internal profile keys remain stable for projects/CLI compatibility:
    ``nxa-native``, ``fiesta2`` and ``prime2``.  The public Fiesta and Prime+
    profiles are engine families, so historical version ranges are documented on
    the individual metadata definitions rather than encoded as extra profile keys.

    Header IDs 1000+ are a Fiesta-and-later namespace.  NXA does not use these
    Header fields; same-number Division/Split metadata remains a separate scope.
    """

    labels = {
        "nxa-native": "NXA",
        "fiesta2": "Fiesta",
        "prime2": "Prime+",
        "nxa-step5-patched": "NXA-patched",
    }
    for key, label in labels.items():
        profile = PROFILES.get(key)
        if profile is not None and profile.label != label:
            PROFILES[key] = replace(profile, label=label)

    fiesta = PROFILES.get("fiesta2")
    if fiesta is not None:
        canonical_headers = (
            MetadataDefinition(
                1000,
                "Section",
                _HEADER,
                evidence=Evidence.RUNTIME_CONFIRMED,
                description=(
                    "Fiesta+ chart-section selector. Value 1 is Arcade. Values above "
                    "1 are version-dependent and must be preserved unless their "
                    "target engine meaning is known. This Header namespace is not "
                    "used by NXA."
                ),
                minimum=1,
            ),
            MetadataDefinition(
                1001,
                "Difficulty",
                _HEADER,
                evidence=Evidence.RUNTIME_CONFIRMED,
                description=(
                    "Fiesta+ chart level. Normal chart values use 1..50; level 50 is "
                    "the special ?? display value in supported arcade versions. "
                    "Fiesta/Fiesta EX/Fiesta 2 Quest Zone floor difficulty uses the "
                    "separate 1..8 mission scale."
                ),
                minimum=1,
                maximum=50,
            ),
            MetadataDefinition(
                1002,
                "Players",
                _HEADER,
                evidence=Evidence.RUNTIME_CONFIRMED,
                description=(
                    "Expected player count for the chart. Prime through R!SE expose "
                    "Arcade charts with values above 1 as Co-Op content when Section "
                    "is 1. R!SE names this field mpPlayers."
                ),
                minimum=1,
                maximum=5,
            ),
            MetadataDefinition(
                1003,
                "Paired Chart",
                _HEADER,
                ValueKind.TRAILER_OFFSET,
                Evidence.RUNTIME_CONFIRMED,
                description=(
                    "Fiesta through Fiesta 2 reference to the additional chart loaded "
                    "for Player 2 in the original Co-Op implementation. Later engines "
                    "retain parser support. The payload is a trailer-relative chart "
                    "reference and is preserved byte-for-byte."
                ),
                authorable=False,
            ),
            _flag_definition(
                1004,
                "New Chart",
                "Fiesta+ chart classification that displays the NEW marker on the Select Screen.",
            ),
            _flag_definition(
                1005,
                "Lock",
                (
                    "Fiesta+ chart classification for content restricted to a special "
                    "selection path such as Quest or Music Train. The Header mirrors "
                    "the catalog classification; it is not a speed-control field."
                ),
            ),
            _flag_definition(
                1006,
                "Another",
                (
                    "Fiesta through Fiesta 2 chart classification that displays the "
                    "Another marker on the Select Screen. The classification is "
                    "retired after Fiesta 2."
                ),
            ),
        )
        PROFILES["fiesta2"] = replace(
            fiesta,
            metadata=(*fiesta.metadata, *canonical_headers),
            capabilities=(
                fiesta.capabilities
                - frozenset({"header-reset-options"})
                | frozenset(
                    {
                        "header-new-chart",
                        "header-lock",
                        "header-another",
                        "header-players",
                        "paired-chart",
                    }
                )
            ),
        )

    prime = PROFILES.get("prime2")
    if prime is not None:
        prime_overrides = (
            _flag_definition(
                1005,
                "Lock",
                (
                    "Fiesta+ lock classification. In Prime-era content this marks "
                    "charts restricted to special selection paths rather than a "
                    "speed-control target."
                ),
            ),
            _flag_definition(
                1006,
                "Another",
                (
                    "Legacy Fiesta/Fiesta 2 Another flag. Prime+ keeps this definition "
                    "only for lossless recognition of older data; official Prime 2 "
                    "corpus does not use Header 1006."
                ),
                evidence=Evidence.REFERENCE_ONLY,
                authorable=False,
            ),
            _flag_definition(
                1007,
                "AM.PASS",
                (
                    "Prime through XX chart classification for AM.PASS-exclusive "
                    "content. Official Prime 2 Header 1007 instances are boolean and "
                    "correlate with the AM.PASS-only chart population."
                ),
                evidence=Evidence.OFFICIAL_CORPUS,
            ),
            MetadataDefinition(
                1008,
                "Step Artist",
                _HEADER,
                ValueKind.TRAILER_OFFSET,
                Evidence.RUNTIME_CONFIRMED,
                description=(
                    "XX through R!SE Step Artist trailer string. R!SE names the field "
                    "mpStepArtist; official modern NX20 charts store a trailer-relative "
                    "offset to a NUL-terminated UTF-8 Step Artist string."
                ),
                authorable=False,
            ),
        )
        PROFILES["prime2"] = replace(
            prime,
            metadata=(*prime.metadata, *prime_overrides),
            capabilities=(
                prime.capabilities
                - frozenset({"auto-velocity"})
                | frozenset({"header-lock", "ampass-card-only", "step-artist-trailer"})
            ),
        )

    # Profile resolution is cached and may already have been touched by an
    # import before this installer runs.
    profile_metadata.cache_clear()
    profile_capabilities.cache_clear()
