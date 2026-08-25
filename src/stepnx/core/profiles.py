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
    INT32 = "int32"
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
    STRONGLY_INFERRED = "strongly-inferred"
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
        if self.kind is ValueKind.INT32:
            value = struct.unpack("<i", struct.pack("<I", raw_value))[0]
            return f"{value} (0x{raw_value:08X})"
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

_TRAILER_VARIANT_LABELS = {
    1: "Korean",
    2: "Spanish",
    3: "Portuguese",
    4: "Chinese",
    5: "Japanese",
}


def metadata_variant_label(meta_id: int) -> str | None:
    """Return the historical localization label for a composite Header ID.

    Later engines retain the full 32-bit metadata ID. The low word selects the
    semantic field and the high word selects a variant/localization slot. Slot 3
    is intentionally called Portuguese because that is the historical Setup
    label even where supplied content is not actually Portuguese.
    """

    if meta_id <= 0xFFFF:
        return None
    variant = meta_id >> 16
    return _TRAILER_VARIANT_LABELS.get(variant, f"Variant {variant}")


def _bool_metadata(
    meta_id: int,
    label: str,
    scopes: frozenset[MetadataScope] = _HEADER,
    *,
    evidence: Evidence = Evidence.RUNTIME_CONFIRMED,
    description: str = "",
) -> MetadataDefinition:
    suffix = " Runtime treats zero as off and any nonzero payload as on."
    return MetadataDefinition(
        meta_id,
        label,
        scopes,
        evidence=evidence,
        description=(description + suffix).strip(),
    )


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
        (20, "BGA video resource (.V)", Evidence.RUNTIME_CONFIRMED),
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
                "Offset relative to the later-generation sized trailer. Composite IDs "
                "retain the full 32-bit ID; low16 is this base field and high16 is a "
                "localization/variant slot. Typed string editing is handled by the "
                "guarded trailer editor rather than the generic metadata-value editor."
            ),
            authorable=False,
        )
        for meta_id, label, evidence in fields
    )


def _fiesta_mission_difficulty_metadata() -> tuple[MetadataDefinition, ...]:
    return tuple(
        MetadataDefinition(
            1000 + floor * 100 + 1,
            f"Mission difficulty — floor {floor}",
            _HEADER,
            evidence=Evidence.RUNTIME_CONFIRMED,
            description=(
                "Fiesta/Fiesta EX/Fiesta 2 mission difficulty uses the native 1..8 "
                "mission scale. The x in 1x01 identifies the mission Step/Floor; "
                "the number of floors is variable in this generation."
            ),
            minimum=1,
            maximum=8,
        )
        for floor in range(1, 5)
    )


def _prime_mission_difficulty_metadata() -> tuple[MetadataDefinition, ...]:
    return tuple(
        MetadataDefinition(
            1000 + floor * 100 + 1,
            f"Mission difficulty — floor {floor}",
            _HEADER,
            evidence=Evidence.RUNTIME_CONFIRMED,
            description=(
                "Prime-era mission difficulty uses Arcade-comparable chart levels. "
                "Prime/Prime 2 missions use four Step/Floor slots, represented by "
                "1101, 1201, 1301 and 1401."
            ),
            minimum=1,
        )
        for floor in range(1, 5)
    )


def _fiesta_floor_runtime_metadata() -> tuple[MetadataDefinition, ...]:
    fields: list[MetadataDefinition] = []
    for floor in range(1, 5):
        prefix = 1000 + floor * 100
        fields.extend(
            (
                MetadataDefinition(
                    prefix + 10,
                    f"Rush / playback-rate scalar — floor {floor}",
                    _HEADER,
                    ValueKind.FLOAT32_BITS,
                    Evidence.STRONGLY_INFERRED,
                    description=(
                        "Fiesta 2 mission runtime selects x110 by floor. The consumer "
                        "scales the runtime timing state and official missions use "
                        "values matching the Rush option family (for example 0.8, "
                        "1.2 and 1.5)."
                    ),
                ),
                MetadataDefinition(
                    prefix + 11,
                    f"Scroll-speed multiplier — floor {floor}",
                    _HEADER,
                    ValueKind.FLOAT32_BITS,
                    Evidence.RUNTIME_CONFIRMED,
                    description=(
                        "Fiesta 2 mission runtime selects x111 by floor and multiplies "
                        "the player's scroll-speed scalar by this IEEE-754 value."
                    ),
                ),
            )
        )
    return tuple(fields)


def _style_override_metadata(
    evidence: Evidence,
    description: str,
) -> MetadataDefinition:
    return MetadataDefinition(
        200,
        "Style override",
        _DIVISION,
        ValueKind.ENUM,
        evidence,
        choices=tuple(
            ValueChoice(value, label)
            for value, label in enumerate(
                ("Default", "Versus", "Double", "Single (collapsed)")
            )
        ),
        description=description,
    )


def _other_player_condition_metadata() -> tuple[MetadataDefinition, ...]:
    labels = (
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
    return tuple(
        MetadataDefinition(
            1000 + index,
            f"Other-player {label}",
            _DIVISION,
            ValueKind.PACKED_U16_RANGE,
            Evidence.STRONGLY_INFERRED,
            description=(
                "Fiesta 2 co-op family inferred as Division 1000+n = the other "
                "player's counterpart of Division n. Division 1000 is supported by "
                "Winter S_CO1 targets 40/125 while S_CO2 performs rolls; Division "
                "1006 has one official Chimera occurrence duplicating Division 6 "
                "with the same range and is likely an accidental authoring duplicate."
            ),
            condition=True,
            repeatable=True,
        )
        for index, label in enumerate(labels)
    )


_NXA_NOTESKIN_REFERENCE = (
    "NXA metadata IDs 900..905 select the six noteskin slots, but their payload "
    "is an external skin reference/index rather than the slot number itself. "
    "Official NXA charts use payload values above 5, so the authoring registry "
    "must preserve the full unsigned value instead of clamping it to 0..5."
)


NATIVE_METADATA = (
    MetadataDefinition(
        0,
        "Speed",
        _HEADER_SPLIT,
        ValueKind.INT32,
        description=(
            "Native NXA Global Metadata consumes this as an integer scalar and "
            "computes value / 4.0. It is not an IEEE-754 float bit pattern."
        ),
    ),
    MetadataDefinition(
        1,
        "Earthworm / Random Velocity",
        _HEADER_SPLIT,
        ValueKind.ENUM,
        choices=(
            ValueChoice(1, "Earthworm"),
            ValueChoice(2, "Random Velocity"),
        ),
        description="Native NXA uses exact values 1 and 2; value 3 is not a composition.",
    ),
    MetadataDefinition(
        2,
        "Acceleration / Deceleration",
        _HEADER_SPLIT,
        ValueKind.ENUM,
        choices=(
            ValueChoice(1, "Acceleration"),
            ValueChoice(2, "Deceleration"),
        ),
        description="Native NXA uses exact values 1 and 2.",
    ),
    MetadataDefinition(
        16,
        "Vanish / Appear",
        _HEADER_SPLIT,
        ValueKind.ENUM,
        choices=(
            ValueChoice(1, "Vanish"),
            ValueChoice(2, "Appear"),
            ValueChoice(3, "Vanish + Appear"),
        ),
    ),
    _bool_metadata(17, "Freedom", _HEADER_SPLIT),
    _bool_metadata(18, "Flash", _HEADER_SPLIT),
    _bool_metadata(
        19,
        "Random Skin",
        description="World Max COMMAND equivalent: i.",
    ),
    _bool_metadata(
        20,
        "BGA OFF / COSMOS",
        description="World Max COMMAND equivalent: *.",
    ),
    _bool_metadata(
        21,
        "X Mode / EXCEED",
        description="World Max COMMAND equivalent: x.",
    ),
    _bool_metadata(
        22,
        "NX Mode",
        description="World Max COMMAND equivalent: ^.",
    ),
    MetadataDefinition(
        32,
        "Under Attack / Drop",
        _HEADER_SPLIT,
        ValueKind.BITMASK,
        bits=(BitChoice(0x01, "Under Attack"), BitChoice(0x02, "Drop")),
        description="Native NXA consumes bits 0..1; the patched profile additionally defines bit 2 as Mid.",
    ),
    MetadataDefinition(
        33,
        "Sink / Rise",
        _HEADER_SPLIT,
        ValueKind.ENUM,
        choices=(ValueChoice(1, "Sink"), ValueChoice(2, "Rise")),
        description="Native NXA uses exact values 1 and 2.",
    ),
    _bool_metadata(34, "Snake", _HEADER_SPLIT),
    _bool_metadata(
        48,
        "Decalcomanie",
        description="Native NXA deterministic lane permutation.",
    ),
    _bool_metadata(
        49,
        "Mirror",
        description=(
            "Native NXA mirror permutation. Fiesta 2 reuses this ID with different "
            "Alternate Random semantics."
        ),
    ),
    _bool_metadata(
        50,
        "Runner",
        description=(
            "Native NXA persistent randomized lane map; hold body/tail rows do not "
            "reshuffle the carried mapping."
        ),
    ),
    _bool_metadata(
        64,
        "Judge by Note",
        description=(
            "World Max COMMAND equivalent: b. Native processing derives bank/slot "
            "from the note payload (low14 % 3), matching per-bank conditions."
        ),
    ),
    MetadataDefinition(
        65,
        "Judgment-window parameter",
        _HEADER,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description=(
            "Native NXA uses its simplified decoder A=(750-value)/100.0. This is the "
            "native EJ/NJ/HJ-family behavior and is deliberately distinct from the "
            "Fiesta-style decimal decoder copied by the Step5 patched profile."
        ),
    ),
    _bool_metadata(
        66,
        "Reverse Grade",
        description="World Max COMMAND equivalent: j.",
    ),
    MetadataDefinition(
        80,
        "Maximum Lifebar",
        _HEADER,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description="World Max COMMAND equivalent: #.",
    ),
    MetadataDefinition(
        81,
        "Lifebar Display",
        _HEADER,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description=(
            "World Max COMMAND equivalent: %. A native display consumer divides "
            "by this value, so typed authoring rejects zero."
        ),
        minimum=1,
    ),
    MetadataDefinition(
        82,
        "Starting Lifebar",
        _HEADER,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description="World Max COMMAND equivalent: @.",
    ),
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
        "Cheer Level / performance state",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.RUNTIME_CONFIRMED,
        description=(
            "Conditional range against the same native performance state written by "
            "Division 16 and maintained by Split 900."
        ),
        condition=True,
        repeatable=True,
    ),
    MetadataDefinition(
        16,
        "Cheer Level / performance state override",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description=(
            "Native NXA writes the performance/Cheer Level state directly. The state "
            "starts at 3; canonical authored values are 1..5 and Division 10 tests "
            "the same state."
        ),
        minimum=1,
        maximum=5,
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
        900,
        "Cheer update",
        _SPLIT,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description=(
            "Performance-driven split activation updater. This is a scope collision: "
            "Global 900 is the default noteskin, Split 900 is Cheer update."
        ),
    ),
    MetadataDefinition(
        999,
        "Auto judgment",
        _DIVISION,
        evidence=Evidence.EXECUTABLE,
        description=(
            "Native 1-based auto-judgment target. Payload zero underflows the runtime "
            "selection and is therefore rejected by typed authoring."
        ),
        minimum=1,
    ),
)


FIESTA2_METADATA = (
    MetadataDefinition(
        0,
        "Speed multiplier",
        _HEADER_SPLIT,
        ValueKind.FLOAT32_BITS,
        Evidence.RUNTIME_CONFIRMED,
        description=(
            "Fiesta-era Header/Split speed is stored as IEEE-754 float bits. This "
            "overrides NXA's integer value/4 interpretation."
        ),
    ),
    *_direct_noteskin_metadata(31, "Fiesta 2"),
    *_later_trailer_metadata(),
    MetadataDefinition(
        19,
        "Random Skin selector",
        _HEADER,
        evidence=Evidence.EXECUTABLE,
        description=(
            "Fiesta 2 stores this state separately from GM900..905. When active, the "
            "noteskin loader fills unspecified slots with 254/Random. The runtime "
            "distinguishes values 1..6; the supplied Fiesta 2 and Prime 2 corpora use "
            "value 6. Exact per-number naming is intentionally not guessed."
        ),
        minimum=1,
        maximum=6,
    ),
    *_unidentified_metadata((11, 12), _SPLIT, "Fiesta 2 Brain"),
    _bool_metadata(
        35,
        "Zigzag",
        description="Fiesta-era runtime consumer for the Zigzag path modifier.",
    ),
    _bool_metadata(
        48,
        "Mirror",
        description="Fiesta-era ID 48; this overrides NXA ID 48 Decalcomanie.",
    ),
    _bool_metadata(
        49,
        "Alternate Random",
        description="Fiesta-era ID 49; this overrides NXA ID 49 Mirror.",
    ),
    MetadataDefinition(
        65,
        "Judgment-window / VJ parameter",
        _HEADER,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description=(
            "Fiesta-style decimal decoder: x=value+5; q=x//10; r=x%10; "
            "A=(75-q)/10.0 and B=(10-r)*0.5. This is not the native NXA GM65 "
            "decoder."
        ),
    ),
    _bool_metadata(
        67,
        "Judge Hide",
        description="Fiesta 2 Header ID 67 maps to the runtime Judge Hide option state.",
    ),
    _bool_metadata(
        68,
        "Judge by Note",
        description=(
            "Fiesta 2 Header ID 68 enables the later-engine note bank/slot rewrite "
            "path. Executable/corpus evidence overrides the conflicting legacy note "
            "that called this Judge Hide."
        ),
    ),
    MetadataDefinition(
        83,
        "Stage Break",
        _HEADER,
        ValueKind.ENUM,
        Evidence.RUNTIME_CONFIRMED,
        description="Boolean Break ON/OFF override stored beside the forced-break threshold.",
        choices=(ValueChoice(0, "Off"), ValueChoice(1, "On")),
    ),
    MetadataDefinition(
        84,
        "Forced Stage Break MissCombo threshold",
        _HEADER,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description=(
            "Overrides the forced Stage Break MissCombo threshold. Runtime initializes "
            "this field to 51; official Fiesta 2 content also uses raw overrides such "
            "as 0, 50, 500 and 30000. No artificial maximum is imposed."
        ),
    ),
    MetadataDefinition(
        1000,
        "Section",
        _HEADER_SPLIT,
        evidence=Evidence.OFFICIAL_CORPUS,
        description="Later-generation section field; not part of native NXA metadata.",
    ),
    MetadataDefinition(
        1001,
        "Difficulty",
        _HEADER_SPLIT,
        evidence=Evidence.OFFICIAL_CORPUS,
        description="Later-generation chart/mission difficulty field; not native NXA.",
    ),
    MetadataDefinition(
        1002,
        "Co-op players",
        _HEADER_SPLIT,
        evidence=Evidence.OFFICIAL_CORPUS,
        description=(
            "Later-generation co-op player count. Official Fiesta 2/Prime 2 values "
            "use the multiplayer range; this field is not native NXA."
        ),
        minimum=1,
        maximum=5,
    ),
    *_fiesta_mission_difficulty_metadata(),
    *_fiesta_floor_runtime_metadata(),
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
        "Auto Velocity flag (Fiesta-era)",
        _HEADER,
        evidence=Evidence.STRONGLY_INFERRED,
        description=(
            "Official Fiesta 2 charts use value 1, almost mutually exclusive with an "
            "explicit Header 0 speed, and the runtime exposes speed_auto_velocity. "
            "This is treated as the Fiesta EX~Prime 1 style AV enable flag, but no "
            "direct Header-1005 dispatcher xref was recovered, so typed creation is "
            "kept disabled."
        ),
        minimum=1,
        maximum=1,
        authorable=False,
    ),
    MetadataDefinition(
        1006,
        "Unidentified Fiesta 2 header flag 1006",
        _HEADER,
        evidence=Evidence.UNIDENTIFIED,
        description="Observed with value 1 without a safe runtime meaning; preserved raw.",
        authorable=False,
    ),
    MetadataDefinition(
        11,
        "Brain Shower correct / O count",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.STRONGLY_INFERRED,
        description=(
            "Fiesta 2 Brain mission condition family. Division 11 occurs in the "
            "official Brain corpus and the NXA Step5 port intentionally copies this "
            "later-engine O/X condition numbering."
        ),
        brain_shower=True,
        condition=True,
        repeatable=True,
    ),
    MetadataDefinition(
        12,
        "Brain Shower wrong / timeout / X count",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.STRONGLY_INFERRED,
        description=(
            "Fiesta 2 counterpart to Division 11. No supplied Fiesta 2 chart happens "
            "to use Division 12, but the paired O/X family is the source copied by "
            "the NXA Step5 patch."
        ),
        brain_shower=True,
        condition=True,
        repeatable=True,
    ),
    _style_override_metadata(
        Evidence.RUNTIME_CONFIRMED,
        "Fiesta 2 style override. This later-engine behavior is the implementation copied by the NXA Step5 patched profile.",
    ),
    *_other_player_condition_metadata(),
)


PRIME2_METADATA = (
    *_direct_noteskin_metadata(32, "Prime 2"),
    *_unidentified_metadata((0, 1, 2, 3, 4), _SPLIT, "Prime 2 discarded-mission"),
    *_prime_mission_difficulty_metadata(),
    MetadataDefinition(
        1005,
        "Auto Velocity",
        _HEADER,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description=(
            "Prime-era Auto Velocity stores the absolute target scroll velocity rather "
            "than a BPM multiplier (for example a target such as 600). It overrides "
            "the Fiesta-era value-1 AV enable-flag interpretation."
        ),
        minimum=1,
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
    MetadataDefinition(
        11,
        "Legacy Fiesta Brain correct / O condition",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.UNIDENTIFIED,
        description=(
            "Fiesta 2 uses this O/X condition family, but no supplied Prime 2 Brain "
            "chart uses Division 11 and Prime 2 mission results omit the O/X counter. "
            "Preserved if encountered, not offered for Prime 2 authoring."
        ),
        authorable=False,
        brain_shower=True,
    ),
    MetadataDefinition(
        12,
        "Legacy Fiesta Brain wrong / X condition",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.UNIDENTIFIED,
        description=(
            "Fiesta 2 counterpart to Division 11; not demonstrated in Prime 2. "
            "Preserved if encountered, not offered for Prime 2 authoring."
        ),
        authorable=False,
        brain_shower=True,
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
        32,
        "Under Attack / Drop / Mid",
        _HEADER_SPLIT,
        ValueKind.BITMASK,
        Evidence.RUNTIME_CONFIRMED,
        description="Step5 extends native GM32 with bit 2 = Mid.",
        bits=(
            BitChoice(0x01, "Under Attack"),
            BitChoice(0x02, "Drop"),
            BitChoice(0x04, "Mid"),
        ),
    ),
    MetadataDefinition(
        65,
        "VJ timing-window parameter",
        _HEADER,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description=(
            "Step5 deliberately replaces native NXA GM65 with the Fiesta-style "
            "decimal decoder: x=value+5; q=x//10; r=x%10; A=(75-q)/10.0 and "
            "B=(10-r)*0.5 frames. This enables the extended VJ/XJ/UJ family."
        ),
    ),
    MetadataDefinition(
        70,
        "Score weighting",
        _HEADER,
        ValueKind.FLOAT32_BITS,
        Evidence.RUNTIME_CONFIRMED,
        description=(
            "Patch-only Fiesta2-style score-delta weighting. 1.0 is neutral; "
            "typical finite values include 0.5, 1.0, 1.5 and 2.0."
        ),
    ),
    _bool_metadata(
        71,
        "Free Performance / cross-pad input fusion",
        evidence=Evidence.RUNTIME_CONFIRMED,
        description=(
            "Patch-only. COMMAND q activates the same cross-pad input-mask fusion, "
            "allowing corresponding P1/P2 panel inputs to be used interchangeably."
        ),
    ),
    *(
        MetadataDefinition(
            meta_id,
            label,
            _HEADER,
            ValueKind.INT32,
            Evidence.RUNTIME_CONFIRMED,
            description=(
                f"Patch-only signed int32 lifebar base override. Native-equivalent "
                f"neutral value: {neutral}. Zero remains a valid explicit override."
            ),
        )
        for meta_id, label, neutral in (
            (86, "Perfect lifebar base override", 20),
            (87, "Great lifebar base override", 16),
            (88, "Good lifebar base override", 0),
            (89, "Bad lifebar base override", -50),
            (90, "Miss lifebar base override", -20),
        )
    ),
    MetadataDefinition(
        11,
        "Brain Shower correct / O count",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.RUNTIME_CONFIRMED,
        description="Patch-only port of the Fiesta 2 Brain O-count condition.",
        brain_shower=True,
        condition=True,
        repeatable=True,
    ),
    MetadataDefinition(
        12,
        "Brain Shower wrong / timeout / X count",
        _DIVISION,
        ValueKind.PACKED_U16_RANGE,
        Evidence.RUNTIME_CONFIRMED,
        description="Patch-only port of the Fiesta 2 Brain X-count condition.",
        brain_shower=True,
        condition=True,
        repeatable=True,
    ),
    *(
        MetadataDefinition(
            meta_id,
            label,
            _DIVISION,
            ValueKind.PACKED_U16_RANGE,
            Evidence.RUNTIME_CONFIRMED,
            description="Patch-only mission-condition range.",
            condition=True,
            repeatable=True,
        )
        for meta_id, label in (
            (101, "Current Combo"),
            (102, "Aggregate MaxCombo"),
            (103, "MissCombo"),
            (104, "Life / Gauge"),
            (105, "Item count"),
            (106, "Heart count"),
            (107, "Mine count"),
            (108, "Potion count"),
            (109, "Velocity count"),
        )
    ),
    MetadataDefinition(
        110,
        "Cheer2 event",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description="Patch-only Cheer2 event/control metadata copied from the later behavior.",
    ),
    MetadataDefinition(
        111,
        "End Song",
        _DIVISION,
        evidence=Evidence.RUNTIME_CONFIRMED,
        description=(
            "Patch-only end-song event: 0 = normal/no forced end, 1 = immediate, "
            "2..255 = fade duration in frames."
        ),
        minimum=0,
        maximum=255,
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
    _style_override_metadata(
        Evidence.RUNTIME_CONFIRMED,
        "Patch-only style override copied from Fiesta 2: 0 preserve, 1 Versus, 2 Double, 3 Single/collapsed.",
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
                "other-player-conditions",
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
                "division-110-cheer2",
                "division-111-end-song",
                "division-120-judgment-weight",
                "division-200-style-override",
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
        if definition.supports(scope):
            resolved[definition.meta_id] = definition
    return tuple(
        sorted(
            (item for item in resolved.values() if item.authorable),
            key=lambda item: item.meta_id,
        )
    )
