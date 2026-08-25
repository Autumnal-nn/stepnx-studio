from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum
from functools import cache


class MetadataScope(str, Enum):
    HEADER = "header"
    SPLIT = "split"
    DIVISION = "division"


class ValueKind(str, Enum):
    UINT32 = "uint32"
    FLOAT32_BITS = "float32-bits"
    BITMASK = "bitmask"
    PACKED_U16_RANGE = "packed-u16-range"
    PACKED_DM120 = "packed-dm120"
    ENUM = "enum"
    TRAILER_OFFSET = "trailer-offset"


class Evidence(str, Enum):
    RUNTIME_CONFIRMED = "runtime-confirmed"
    EXECUTABLE = "executable"
    OFFICIAL_CORPUS = "official-corpus"
    REFERENCE_ONLY = "reference-only"
    UNIDENTIFIED = "unidentified"


@dataclass(frozen=True, slots=True)
class ValueChoice:
    value: int
    label: str


@dataclass(frozen=True, slots=True)
class BitChoice:
    mask: int
    label: str


@dataclass(frozen=True, slots=True)
class MetadataDefinition:
    meta_id: int
    label: str
    scopes: frozenset[MetadataScope]
    kind: ValueKind = ValueKind.UINT32
    evidence: Evidence = Evidence.EXECUTABLE
    description: str = ""
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[ValueChoice, ...] = ()
    bits: tuple[BitChoice, ...] = ()
    authorable: bool = True
    brain_shower: bool = False
    condition: bool = False
    repeatable: bool = False

    def supports(self, scope: MetadataScope) -> bool:
        return scope in self.scopes

    def display_value(self, raw_value: int) -> str:
        if self.kind is ValueKind.FLOAT32_BITS:
            value = struct.unpack("<f", struct.pack("<I", raw_value))[0]
            return f"{value:g} (0x{raw_value:08X})"
        if self.kind is ValueKind.PACKED_U16_RANGE:
            minimum, maximum = unpack_u16_range(raw_value)
            return f"{minimum}..{maximum}"
        if self.kind is ValueKind.PACKED_DM120:
            mode, weight = unpack_dm120(raw_value)
            mode_label = {0: "Perfect additions", 1: "Same judgment"}.get(
                mode, f"Invalid mode {mode}"
            )
            return f"{mode}/{weight} ({mode_label})"
        if self.kind is ValueKind.BITMASK:
            labels = [bit.label for bit in self.bits if raw_value & bit.mask]
            known = sum(bit.mask for bit in self.bits)
            unknown = raw_value & ~known
            if unknown:
                labels.append(f"unknown 0x{unknown:X}")
            return " + ".join(labels) if labels else "none"
        if self.kind is ValueKind.ENUM:
            label = next(
                (choice.label for choice in self.choices if choice.value == raw_value),
                None,
            )
            return label if label is not None else f"Unknown ({raw_value})"
        return str(raw_value)


@dataclass(frozen=True, slots=True)
class EngineProfile:
    name: str
    label: str
    parent: str | None
    metadata: tuple[MetadataDefinition, ...]
    capabilities: frozenset[str]


def unpack_u16_range(value: int) -> tuple[int, int]:
    return value & 0xFFFF, (value >> 16) & 0xFFFF


def pack_u16_range(minimum: int, maximum: int) -> int:
    if not 0 <= minimum <= 0xFFFF or not 0 <= maximum <= 0xFFFF:
        raise ValueError("packed metadata bounds must fit unsigned 16-bit values")
    return minimum | (maximum << 16)


def unpack_dm120(value: int) -> tuple[int, int]:
    mode = value & 0xFFFF
    weight = (value >> 16) & 0xFFFF
    if weight & 0x8000:
        weight -= 0x10000
    return mode, weight


def pack_dm120(mode: int, weight: int) -> int:
    if mode not in (0, 1):
        raise ValueError("DM120 mode must be 0 or 1")
    minimum = -1 if mode == 0 else -2
    if not minimum <= weight <= 255:
        raise ValueError(f"DM120 mode {mode} weight must be {minimum}..255")
    return mode | ((weight & 0xFFFF) << 16)


_HEADER = frozenset((MetadataScope.HEADER,))
_HEADER_SPLIT = frozenset((MetadataScope.HEADER, MetadataScope.SPLIT))
_SPLIT = frozenset((MetadataScope.SPLIT,))
_DIVISION = frozenset((MetadataScope.DIVISION,))


def _direct_noteskin_metadata(
    maximum: int, engine_label: str
) -> tuple[MetadataDefinition, ...]:
    choices = tuple(ValueChoice(value, f"{value:02d}") for value in range(maximum + 1)) + (
        ValueChoice(254, "Random"),
    )
    description = (
        f"{engine_label} uses direct noteskin IDs 00..{maximum:02d}; "
        "254 is the Random noteskin value used by official charts. Unknown raw "
        "values remain preservable even though the typed editor exposes only the "
        "proven choices."
    )
    return (
        MetadataDefinition(
            900,
            "Default noteskin",
            _HEADER_SPLIT,
            ValueKind.ENUM,
            Evidence.RUNTIME_CONFIRMED,
            description=description,
            choices=choices,
        ),
        *(
            MetadataDefinition(
                900 + player,
                f"P{player} noteskin",
                _HEADER_SPLIT,
                ValueKind.ENUM,
                Evidence.RUNTIME_CONFIRMED,
                description=description,
                choices=choices,
            )
            for player in range(1, 6)
        ),
    )


def _unidentified_metadata(
    meta_ids: tuple[int, ...],
    scopes: frozenset[MetadataScope],
    family: str,
) -> tuple[MetadataDefinition, ...]:
    scope_label = "/".join(scope.value for scope in sorted(scopes, key=lambda item: item.value))
    return tuple(
        MetadataDefinition(
            meta_id,
            f"Unidentified {family} {scope_label} field {meta_id}",
            scopes,
            evidence=Evidence.UNIDENTIFIED,
            description=(
                "Observed in the supplied official corpus but not assigned a safe "
                "authoring meaning. The raw value is preserved without normalization."
            ),
            authorable=False,
        )
        for meta_id in meta_ids
    )


def _later_trailer_metadata() -> tuple[MetadataDefinition, ...]:
    fields = (
        (20, "V resource override", Evidence.RUNTIME_CONFIRMED),
        (1003, "Resource/reference string", Evidence.RUNTIME_CONFIRMED),
        (1100, "Trailer string field 1100", Evidence.OFFICIAL_CORPUS),
        (1102, "Trailer string field 1102", Evidence.OFFICIAL_CORPUS),
        (1103, "Localized mission text", Evidence.RUNTIME_CONFIRMED),
        (1150, "Mission condition string", Evidence.OFFICIAL_CORPUS),
        (1151, "Trailer string field 1151", Evidence.OFFICIAL_CORPUS),
        (1199, "Trailer string field 1199", Evidence.OFFICIAL_CORPUS),
        (1203, "Localized mission text", Evidence.RUNTIME_CONFIRMED),
        (1250, "Mission condition string", Evidence.OFFICIAL_CORPUS),
        (1299, "Trailer string field 1299", Evidence.OFFICIAL_CORPUS),
        (1303, "Localized mission text", Evidence.RUNTIME_CONFIRMED),
        (1350, "Mission condition string", Evidence.OFFICIAL_CORPUS),
        (1399, "Trailer string field 1399", Evidence.OFFICIAL_CORPUS),
        (1403, "Localized mission text", Evidence.RUNTIME_CONFIRMED),
        (1450, "Mission condition string", Evidence.OFFICIAL_CORPUS),
    )
    return tuple(
        MetadataDefinition(
            meta_id,
            label,
            _HEADER,
            ValueKind.TRAILER_OFFSET,
            evidence,
            description=(
                "Offset relative to the later-generation sized trailer. Typed string "
                "editing is handled by the guarded trailer editor rather than the "
                "generic metadata-value editor."
            ),
            authorable=False,
        )
        for meta_id, label, evidence in fields
    )


_NXA_NOTESKIN_REFERENCE = (
    "NXA metadata IDs 900..905 select the six noteskin slots, but their payload "
    "is an external skin reference/index rather than the slot number itself. "
    "Official NXA charts use payload values above 5, so the authoring registry "
    "must preserve the full unsigned value instead of clamping it to 0..5."
)


NATIVE_METADATA = (
    MetadataDefinition(0, "Speed", _HEADER_SPLIT, ValueKind.FLOAT32_BITS),
    MetadataDefinition(
        1,
        "Earthworm / Random Velocity",
        _HEADER_SPLIT,
        ValueKind.BITMASK,
        bits=(BitChoice(0x01, "Earthworm"), BitChoice(0x02, "Random Velocity")),
    ),
    MetadataDefinition(
        2,
        "Acceleration / Deceleration",
        _HEADER_SPLIT,
        ValueKind.BITMASK,
        bits=(BitChoice(0x01, "Acceleration"), BitChoice(0x02, "Deceleration")),
    ),
    MetadataDefinition(
        16,
        "Vanish / Appear",
        _HEADER_SPLIT,
        ValueKind.BITMASK,
        bits=(BitChoice(0x01, "Vanish"), BitChoice(0x02, "Appear")),
    ),
    MetadataDefinition(
        17, "Freedom", _HEADER_SPLIT, ValueKind.BITMASK, bits=(BitChoice(1, "Freedom"),)
    ),
    MetadataDefinition(
        18, "Flash", _HEADER_SPLIT, ValueKind.BITMASK, bits=(BitChoice(1, "Flash"),)
    ),
    MetadataDefinition(
        32,
        "Under Attack / Drop",
        _HEADER_SPLIT,
        ValueKind.BITMASK,
        bits=(BitChoice(0x01, "Under Attack"), BitChoice(0x02, "Drop")),
    ),
    MetadataDefinition(
        33,
        "Sink / Rise",
        _HEADER_SPLIT,
        ValueKind.BITMASK,
        bits=(BitChoice(0x01, "Sink"), BitChoice(0x02, "Rise")),
    ),
    MetadataDefinition(
        34, "Snake", _HEADER_SPLIT, ValueKind.BITMASK, bits=(BitChoice(1, "Snake"),)
    ),
    MetadataDefinition(
        35, "Zigzag", _HEADER_SPLIT, ValueKind.BITMASK, bits=(BitChoice(1, "Zigzag"),)
    ),
    *_unidentified_metadata((49, 64), _HEADER, "NXA"),
    MetadataDefinition(
        900, "Default noteskin", _HEADER_SPLIT, description=_NXA_NOTESKIN_REFERENCE
    ),
    *(
        MetadataDefinition(
            900 + player,
            f"P{player} noteskin",
            _HEADER_SPLIT,
            description=_NXA_NOTESKIN_REFERENCE,
        )
        for player in range(1, 6)
    ),
    MetadataDefinition(1000, "Section", _HEADER_SPLIT),
    MetadataDefinition(1001, "Difficulty", _HEADER_SPLIT),
    MetadataDefinition(1002, "Co-op players", _HEADER_SPLIT, minimum=1, maximum=5),
    *(
        MetadataDefinition(
            meta_id,
            f"Float parameter {meta_id}",
            _HEADER_SPLIT,
            ValueKind.FLOAT32_BITS,
            Evidence.REFERENCE_ONLY,
        )
        for meta_id in (1210, 1211, 1310, 1311, 1410, 1411)
    ),
    *(
        MetadataDefinition(
            meta_id,
            label,
            _DIVISION,
            ValueKind.PACKED_U16_RANGE,
            Evidence.RUNTIME_CONFIRMED,
            condition=True,
            repeatable=True,
        )
        for meta_id, label in enumerate(
            (
                "Perfect count",
                "Great count",
                "Good count",
                "Bad count",
                "Miss count",
                "Step G count",
                "Step W count",
                "Step A count",
                "Step B count",
                "Step C count",
            )
        )
    ),
    MetadataDefinition(
        10,
        "Cheer / applause level",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.EXECUTABLE,
        condition=True,
        repeatable=True,
    ),
    MetadataDefinition(
        11,
        "Brain Shower correct count",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.RUNTIME_CONFIRMED,
        brain_shower=True,
        condition=True,
        repeatable=True,
    ),
    MetadataDefinition(
        12,
        "Brain Shower wrong / timeout count",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.RUNTIME_CONFIRMED,
        brain_shower=True,
        condition=True,
        repeatable=True,
    ),
    MetadataDefinition(
        16,
        "Visual mode override",
        _DIVISION,
        evidence=Evidence.REFERENCE_ONLY,
        authorable=False,
    ),
    MetadataDefinition(
        21,
        "Question opcode / type",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        brain_shower=True,
    ),
    MetadataDefinition(
        22,
        "Instruction sprite index",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        brain_shower=True,
    ),
    MetadataDefinition(
        23,
        "Question count / repeats",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        minimum=0,
        brain_shower=True,
    ),
    MetadataDefinition(
        24,
        "Puzzle delay",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        minimum=0,
        brain_shower=True,
    ),
    MetadataDefinition(
        25,
        "O/X result hold time",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        minimum=0,
        brain_shower=True,
    ),
    MetadataDefinition(
        26,
        "Answer count",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        minimum=1,
        maximum=10,
        brain_shower=True,
    ),
    MetadataDefinition(
        31,
        "Size / difficulty / BrainQuest variant",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        minimum=0,
        brain_shower=True,
    ),
    MetadataDefinition(
        32,
        "Brain Shower context A / speed",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.RUNTIME_CONFIRMED,
        brain_shower=True,
    ),
    MetadataDefinition(
        33,
        "Brain Shower context B / interval",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.RUNTIME_CONFIRMED,
        brain_shower=True,
    ),
    MetadataDefinition(
        34,
        "Preset / hard-coded table index",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        minimum=0,
        brain_shower=True,
    ),
    *(
        MetadataDefinition(
            meta_id,
            f"Unidentified Brain Shower parameter {meta_id}",
            _DIVISION,
            evidence=Evidence.UNIDENTIFIED,
            authorable=False,
            brain_shower=True,
        )
        for meta_id in range(43, 50)
    ),
    MetadataDefinition(
        200,
        "Style override",
        _DIVISION,
        ValueKind.ENUM,
        Evidence.RUNTIME_CONFIRMED,
        choices=tuple(
            ValueChoice(value, label)
            for value, label in enumerate(
                ("Default", "Versus", "Double", "Single (collapsed)")
            )
        ),
    ),
    MetadataDefinition(
        221,
        "Snake path segment length",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.RUNTIME_CONFIRMED,
    ),
    MetadataDefinition(
        222,
        "Snake path straight-zone limit",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.RUNTIME_CONFIRMED,
    ),
    MetadataDefinition(
        900, "Cheer update", _DIVISION, evidence=Evidence.RUNTIME_CONFIRMED
    ),
    MetadataDefinition(999, "Auto judge", _DIVISION, evidence=Evidence.EXECUTABLE),
    MetadataDefinition(
        1001,
        "Difficulty filter",
        _DIVISION,
        evidence=Evidence.REFERENCE_ONLY,
        authorable=False,
    ),
)


FIESTA2_METADATA = (
    *_direct_noteskin_metadata(31, "Fiesta 2"),
    *_later_trailer_metadata(),
    *_unidentified_metadata(
        (19, 21, 22, 48, 50, 65, 66, 67, 68, 80, 81, 82, 83, 84),
        _HEADER,
        "Fiesta 2",
    ),
    *_unidentified_metadata(
        (1101, 1110, 1111, 1201, 1301, 1401),
        _HEADER,
        "Fiesta 2",
    ),
    *_unidentified_metadata((11, 12), _SPLIT, "Fiesta 2"),
    *_unidentified_metadata((1000,), _DIVISION, "Fiesta 2"),
    MetadataDefinition(
        1004,
        "Reset gameplay options",
        _HEADER,
        ValueKind.ENUM,
        Evidence.RUNTIME_CONFIRMED,
        description=(
            "Presence resets the proven option state to the Fiesta-era baseline: "
            "Rush off, speed x2, noteskin 0, local modifier bits cleared, and the "
            "propagated Under Attack/BGA Off/Exceed/NX/Drop/Runner bits cleared. "
            "Official charts encode the flag as value 1."
        ),
        minimum=1,
        maximum=1,
        choices=(ValueChoice(1, "Reset"),),
    ),
    MetadataDefinition(
        1005,
        "Unidentified Fiesta 2 header flag 1005",
        _HEADER,
        evidence=Evidence.UNIDENTIFIED,
        description=(
            "Observed in the official Fiesta 2 corpus with value 1. The supplied "
            "Fiesta 2 executable has no dedicated Header-1005 handler; Prime 2 "
            "reuses this ID with proven Auto Velocity semantics."
        ),
        authorable=False,
    ),
    MetadataDefinition(
        1006,
        "Unidentified Fiesta 2 header flag 1006",
        _HEADER,
        evidence=Evidence.UNIDENTIFIED,
        description=(
            "Observed in the official Fiesta 2 corpus with value 1, without a "
            "dedicated handler in the supplied executable. Preserved raw."
        ),
        authorable=False,
    ),
    MetadataDefinition(
        1006,
        "Unidentified Fiesta 2 Division field 1006",
        _DIVISION,
        evidence=Evidence.UNIDENTIFIED,
        description=(
            "Rare official-corpus Division field. The observed Fiesta 2 instance "
            "duplicates the value of Division 6; no dedicated runtime meaning is "
            "proven, so it remains raw-only."
        ),
        authorable=False,
    ),
)


PRIME2_METADATA = (
    *_direct_noteskin_metadata(32, "Prime 2"),
    *_unidentified_metadata((3, 4), _SPLIT, "Prime 2"),
    MetadataDefinition(
        1005,
        "Auto Velocity",
        _HEADER,
        ValueKind.ENUM,
        Evidence.RUNTIME_CONFIRMED,
        description=(
            "Enables Prime-era Auto Velocity semantics: scroll velocity targets an "
            "absolute final speed rather than selecting a BPM multiplier. Official "
            "Prime 2 charts encode the flag as value 1."
        ),
        minimum=1,
        maximum=1,
        choices=(ValueChoice(1, "Enabled"),),
    ),
    MetadataDefinition(
        1007,
        "Card-only (AM.PASS)",
        _HEADER,
        ValueKind.ENUM,
        Evidence.OFFICIAL_CORPUS,
        description=(
            "Marks Prime 2 charts that were card-exclusive through AM.PASS rather "
            "than ordinary AM.PASS item-shop unlocks. The 83 official NX instances "
            "correlate 1:1 with LIST chart-record bit 0x00000100; official update "
            "history independently identifies the same charts as card-only."
        ),
        minimum=1,
        maximum=1,
        choices=(ValueChoice(1, "Card-only"),),
    ),
    *(
        MetadataDefinition(
            meta_id,
            f"Unidentified discarded-mission Division field {meta_id}",
            _DIVISION,
            evidence=Evidence.UNIDENTIFIED,
            description=(
                "Observed only in discarded EF2166_D18_MINAMI.NFO content that is "
                "absent from the published Prime 2 Quest Zone/LIST. This Division "
                "field is deliberately not assigned the semantics of a same-number "
                "Header field."
            ),
            authorable=False,
        )
        for meta_id in (1005, 1006, 1007)
    ),
)


PATCHED_METADATA = (
    MetadataDefinition(
        65,
        "VJ timing-window parameter",
        frozenset((MetadataScope.HEADER,)),
        evidence=Evidence.RUNTIME_CONFIRMED,
        description="Step5 patched NXA formula input for VJ/XJ/UJ timing windows.",
    ),
    MetadataDefinition(
        111,
        "Cheer control",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description="Patched full-range Division metadata; values are not collapsed to boolean.",
    ),
    MetadataDefinition(
        120,
        "Judgment effect weight",
        _DIVISION,
        ValueKind.PACKED_DM120,
        Evidence.EXECUTABLE,
        description=(
            "low16 mode (0=non-Miss adds Perfect, 1=repeats the same judgment); "
            "signed high16 y. Mode 0 accepts -1..255 and mode 1 accepts -2..255."
        ),
    ),
    MetadataDefinition(900, "Default noteskin", _HEADER_SPLIT, minimum=0, maximum=31),
    *(
        MetadataDefinition(
            900 + player,
            f"P{player} noteskin",
            _HEADER_SPLIT,
            minimum=0,
            maximum=31,
        )
        for player in range(1, 6)
    ),
)


PROFILES = {
    "nxa-native": EngineProfile(
        "nxa-native",
        "Pump It Up NXA (native)",
        None,
        NATIVE_METADATA,
        frozenset(
            {
                "nx20",
                "brain-shower",
                "conditional-divisions",
                "mission-nfo",
                "items-0-20",
                "commands-native",
                "noteskins-0-5",
            }
        ),
    ),
    "fiesta2": EngineProfile(
        "fiesta2",
        "Pump It Up Fiesta 2",
        "nxa-native",
        FIESTA2_METADATA,
        frozenset(
            {
                "later-nx20-trailer",
                "items-21-23",
                "direct-noteskin-index",
                "header-reset-options",
            }
        ),
    ),
    "prime2": EngineProfile(
        "prime2",
        "Pump It Up Prime 2",
        "fiesta2",
        PRIME2_METADATA,
        frozenset(
            {
                "auto-velocity",
                "ampass-card-only",
            }
        ),
    ),
    "nxa-step5-patched": EngineProfile(
        "nxa-step5-patched",
        "NXA Step5 patched engine",
        "nxa-native",
        PATCHED_METADATA,
        frozenset(
            {
                "condition-correct",
                "condition-miss",
                "condition-score",
                "condition-gauge",
                "condition-accuracy",
                "condition-minlife",
                "gm65-vj-window",
                "division-111-cheer",
                "division-120-judgment-weight",
                "items-21-23",
                "noteskins-0-31",
                "command-jh",
                "command-jn",
                "command-free-performance",
                "assist-beat-wav",
            }
        ),
    ),
}


def get_profile(name: str) -> EngineProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise KeyError(f"unknown engine profile {name!r}") from exc


@cache
def profile_metadata(name: str) -> tuple[MetadataDefinition, ...]:
    profile = get_profile(name)
    inherited = profile_metadata(profile.parent) if profile.parent else ()
    return inherited + profile.metadata


@cache
def profile_capabilities(name: str) -> frozenset[str]:
    profile = get_profile(name)
    inherited = profile_capabilities(profile.parent) if profile.parent else frozenset()
    return inherited | profile.capabilities


def metadata_definition(
    profile_name: str,
    scope: MetadataScope,
    meta_id: int,
) -> MetadataDefinition | None:
    if profile_name not in PROFILES:
        return None
    matches = [
        definition
        for definition in profile_metadata(profile_name)
        if definition.meta_id == meta_id and definition.supports(scope)
    ]
    if matches:
        return matches[-1]
    if scope is MetadataScope.HEADER and meta_id > 0xFFFF:
        base_id = meta_id & 0xFFFF
        base_matches = [
            definition
            for definition in profile_metadata(profile_name)
            if definition.meta_id == base_id
            and definition.supports(scope)
            and definition.kind is ValueKind.TRAILER_OFFSET
        ]
        if base_matches:
            return base_matches[-1]
    return None


def authorable_metadata(
    profile_name: str,
    scope: MetadataScope,
) -> tuple[MetadataDefinition, ...]:
    resolved: dict[int, MetadataDefinition] = {}
    for definition in profile_metadata(profile_name):
        if definition.authorable and definition.supports(scope):
            resolved[definition.meta_id] = definition
    return tuple(sorted(resolved.values(), key=lambda item: item.meta_id))
