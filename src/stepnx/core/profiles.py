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


_HEADER_SPLIT = frozenset((MetadataScope.HEADER, MetadataScope.SPLIT))
_DIVISION = frozenset((MetadataScope.DIVISION,))


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
    MetadataDefinition(900, "Default noteskin", _HEADER_SPLIT, minimum=0, maximum=5),
    *(
        MetadataDefinition(
            900 + player, f"P{player} noteskin", _HEADER_SPLIT, minimum=0, maximum=5
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
    return matches[-1] if matches else None


def authorable_metadata(
    profile_name: str,
    scope: MetadataScope,
) -> tuple[MetadataDefinition, ...]:
    resolved: dict[int, MetadataDefinition] = {}
    for definition in profile_metadata(profile_name):
        if definition.authorable and definition.supports(scope):
            resolved[definition.meta_id] = definition
    return tuple(sorted(resolved.values(), key=lambda item: item.meta_id))
