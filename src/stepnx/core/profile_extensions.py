from __future__ import annotations

from dataclasses import replace

from stepnx.core.profiles import (
    Evidence,
    MetadataDefinition,
    MetadataScope,
    PROFILES,
    ValueKind,
    profile_capabilities,
    profile_metadata,
)


_HEADER = frozenset((MetadataScope.HEADER,))


def install_profile_extensions() -> None:
    """Apply evidence-backed family labels and modern-only metadata.

    Internal profile keys remain stable for projects/CLI compatibility:
    ``nxa-native``, ``fiesta2`` and ``prime2``. The labels deliberately describe
    engine families rather than one executable revision.
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

    prime = PROFILES.get("prime2")
    if prime is not None and not any(
        item.meta_id == 1008 and item.supports(MetadataScope.HEADER)
        for item in prime.metadata
    ):
        step_artist = MetadataDefinition(
            1008,
            "Step Artist (XX and beyond)",
            _HEADER,
            ValueKind.TRAILER_OFFSET,
            Evidence.RUNTIME_CONFIRMED,
            description=(
                "Modern XX-and-later Step Artist trailer string. R!SE names this "
                "runtime field mpStepArtist; official R!SE NX20 charts store a "
                "trailer-relative offset to a NUL-terminated UTF-8 artist string. "
                "Prime and Prime 2 predate the player-visible Step Artist field, but "
                "the existing prime2 profile intentionally represents the whole "
                "compatible modern engine family."
            ),
            authorable=False,
        )
        PROFILES["prime2"] = replace(
            prime,
            metadata=(*prime.metadata, step_artist),
            capabilities=prime.capabilities | frozenset({"step-artist-trailer"}),
        )

    # Profile resolution is cached and may already have been touched by an
    # import before this installer runs.
    profile_metadata.cache_clear()
    profile_capabilities.cache_clear()
