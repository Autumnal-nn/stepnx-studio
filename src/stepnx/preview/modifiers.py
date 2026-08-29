from __future__ import annotations

import struct
from dataclasses import dataclass, replace
from enum import IntEnum, IntFlag
from math import trunc


class SpeedMode(IntEnum):
    STATIC = 0
    EARTHWORM = 1
    RANDOM_VELOCITY = 2
    AUTO_VELOCITY = 3


class AccDecMode(IntEnum):
    LINEAR = 0
    ACCELERATION = 1
    DECELERATION = 2


class VisibilityMode(IntEnum):
    VISIBLE = 0
    VANISH = 1
    APPEAR = 2
    HIDDEN = 3


class SequenceZoneTransform(IntFlag):
    """Metadata 32 sequence-zone transform bits.

    NX2/NXA and the R!SE CommonModifier expose the native low two bits as
    independent transformations rather than a four-value direction enum:

    * bit0: Under Attack (180-degree playfield rotation)
    * bit1: Drop (vertical reflection)

    The NXA-patched profile extends the same bitfield with bit2 (Mid).  Higher
    bits are ignored by that patch.  R!SE/native decoding remains restricted to
    canonical values 0..3.
    """

    NORMAL = 0
    UNDER_ATTACK = 0x01
    DROP = 0x02
    MID = 0x04

    # Compatibility aliases for older callers. These names describe the old
    # Studio abstraction, not separate native enum values.
    ROTATE_180 = UNDER_ATTACK
    UPSIDE_DOWN = DROP
    MIRROR = UNDER_ATTACK | DROP


# Public compatibility alias retained while callers migrate to the bitmask name.
DirectionMode = SequenceZoneTransform


class ThrowMode(IntEnum):
    FLAT = 0
    SINK = 1
    RISE = 2


class ComboDisplay(IntEnum):
    SINGLE_BANK = 0
    ALL_BANK = 1
    ALL_PLAYER = 2


@dataclass(frozen=True, slots=True)
class StepParam:
    """One serialized NX20 StepParam pair, retaining source order and duplicates."""

    metadata_id: int
    raw_value: int

    @property
    def signed_value(self) -> int:
        value = self.raw_value & 0xFFFFFFFF
        return value - 0x100000000 if value & 0x80000000 else value

    @property
    def float_value(self) -> float:
        return struct.unpack("<f", struct.pack("<I", self.raw_value & 0xFFFFFFFF))[0]


@dataclass(frozen=True, slots=True)
class EffectiveModifier:
    """R!SE state after ApplyStepParamToMod has consumed Header StepParams.

    Field names mirror the recovered GameModifier/CommonModifier metadata where
    possible. State outside those two classes is retained only when the same
    dispatcher directly writes it. Merely declared PUMP.Param IDs are not
    treated as active Header modifiers unless the binary consumes them here.
    """

    # GameModifier.Clear() defaults recovered from GameAssembly.dll/dump.cs.
    skins: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)
    speed: float = 2.0
    speed_mode: SpeedMode = SpeedMode.STATIC
    acc_dec: AccDecMode = AccDecMode.LINEAR
    visibility: VisibilityMode = VisibilityMode.VISIBLE
    freedom: bool = False
    flash: bool = False
    random_skin: int = 0
    throw: ThrowMode = ThrowMode.FLAT
    snake: bool = False
    zigzag: bool = False
    mirror_turn: bool = False
    mirror_lr: bool = False
    random: bool = False
    runner: bool = False
    judge_bank: bool = False
    perfect_frame: float = 2.5
    interval_frame: float = 2.5
    judge_reverse: bool = False
    hide_judge: bool = False
    judge_by_note: bool = False
    combo_display: ComboDisplay | None = None
    combo_per_bank: bool = False
    free_performance: bool = False
    alt_skin_score_factor: float = 0.0
    alt_skin_gauge_factor: float = 0.0

    # CommonModifier.Clear() defaults.
    disable_bg: bool = False
    exceed: bool = False
    nx: bool = False
    sequence_transform: SequenceZoneTransform = SequenceZoneTransform.NORMAL
    merge_combo: bool = False
    gauge_link_factor: int = 0
    speed_boost: float = 0.0

    # Other state directly written by ApplyStepParamToMod.
    level: int | None = None
    gauge_max: int | None = None
    gauge_display_max: int | None = None
    gauge_initial_value: int | None = None
    stage_break: bool | None = None
    miss_combo_break: int | None = None

    @property
    def under_attack(self) -> bool:
        return bool(self.sequence_transform & SequenceZoneTransform.UNDER_ATTACK)

    @property
    def drop(self) -> bool:
        return bool(self.sequence_transform & SequenceZoneTransform.DROP)

    @property
    def mid(self) -> bool:
        return bool(self.sequence_transform & SequenceZoneTransform.MID)

    # Native field-name compatibility. R!SE calls the two low-bit consumers
    # bRotate180 and bUpsideDown, but the serialized Metadata 32 semantics are
    # Under Attack and Drop.
    @property
    def rotate_180(self) -> bool:
        return self.under_attack

    @property
    def upside_down(self) -> bool:
        return self.drop

    @property
    def direction(self) -> SequenceZoneTransform:
        return self.sequence_transform


def _first(params: tuple[StepParam, ...], metadata_id: int) -> StepParam | None:
    """Port R!SE's first-match StepParam lookup."""

    for param in params:
        if param.metadata_id == metadata_id:
            return param
    return None


def _present_signed(params: tuple[StepParam, ...], metadata_id: int) -> int | None:
    param = _first(params, metadata_id)
    if param is None or param.signed_value == -1:
        return None
    return param.signed_value


def _present_float(params: tuple[StepParam, ...], metadata_id: int) -> float | None:
    """Port Step.GetFloatParam's bit-preserving uint32 -> IEEE-754 conversion."""

    param = _first(params, metadata_id)
    if param is None:
        return None
    value = param.float_value
    return None if value == -1.0 else value


def _bool_value(params: tuple[StepParam, ...], metadata_id: int) -> bool | None:
    value = _present_signed(params, metadata_id)
    return None if value is None else value != 0


def _enum_value(
    params: tuple[StepParam, ...], metadata_id: int, enum_type: type[IntEnum]
) -> IntEnum | None:
    value = _present_signed(params, metadata_id)
    if value is None:
        return None
    try:
        return enum_type(value)
    except ValueError:
        return None


def _speed_parameter(value: float) -> float:
    """Port ApplyStepParamToMod's Header Speed normalization."""

    if 0.0 < value <= 255.0:
        return value * 0.25
    return value


def _judge_parameter(value: int) -> tuple[float, float]:
    """Port the R!SE decimal ID-65 decoder without consuming it in judgments yet."""

    x = value + 5
    quotient = trunc(x / 10)
    remainder = x - quotient * 10
    perfect_frame = (75 - quotient) / 10.0
    interval_frame = (10 - remainder) * 0.5
    return perfect_frame, interval_frame


def _apply_sequence_transform(
    result: EffectiveModifier,
    value: int,
    *,
    allow_mid: bool,
) -> EffectiveModifier:
    """Decode Metadata 32 without collapsing its independent bits.

    Native NX2/NXA/R!SE accepts canonical values 0..3. The NXA patch extends
    the same bitfield with Mid (bit2) and ignores bits above 0x04.
    """

    if allow_mid:
        transform = SequenceZoneTransform(int(value) & 0x07)
    elif value in (0, 1, 2, 3):
        transform = SequenceZoneTransform(value)
    else:
        return result
    return replace(result, sequence_transform=transform)


def _apply_combo_display(result: EffectiveModifier, value: int) -> EffectiveModifier:
    if value not in (0, 1, 2):
        return result
    mode = ComboDisplay(value)
    return replace(
        result,
        combo_display=mode,
        combo_per_bank=mode is ComboDisplay.SINGLE_BANK,
        merge_combo=mode is ComboDisplay.ALL_PLAYER,
    )


def _apply_skins(
    params: tuple[StepParam, ...], result: EffectiveModifier
) -> EffectiveModifier:
    skins = list(result.skins)
    for slot in range(6):
        value = _present_signed(params, 900 + slot)
        if value is not None:
            skins[slot] = value
        elif result.random_skin != 0:
            # Native fallback used by ApplyStepParamToMod for unspecified slots.
            skins[slot] = 254
    return replace(result, skins=tuple(skins))  # type: ignore[arg-type]


def apply_step_params(
    params: tuple[StepParam, ...],
    base: EffectiveModifier | None = None,
    *,
    allow_mid: bool = False,
) -> EffectiveModifier:
    """Port R!SE PlayBase.ApplyStepParamToMod (RVA 0x659F00).

    The native method reads the loaded Step's global Header StepParam array at
    Step+0x28. Split metadata is deliberately not merged here: no recovered
    source path applies Split+0x18 through this dispatcher.

    ``allow_mid`` is deliberately profile-gated. R!SE/native Metadata 32 uses
    only the low two canonical bits; NXA-patched extends that same field with
    bit2 Mid and ignores higher bits.

    PUMP.Param contains a few names that are *not* effective Header writes in
    this routine. mpRunner (51) has no branch here. mpForceBGA (20) calls
    GetStrParam but discards the result, and mpmSpeedBoost (1110) calls
    GetFloatParam but discards that result. They are therefore not fabricated
    as effective state by this projection.
    """

    result = EffectiveModifier() if base is None else base

    # mpLevel (1001) is consumed early by the dispatcher for stage/gauge setup.
    value_i = _present_signed(params, 1001)
    if value_i is not None:
        result = replace(result, level=value_i)

    value_f = _present_float(params, 0)
    if value_f is not None:
        result = replace(result, speed=_speed_parameter(value_f))

    # Although the enum declares AutoVelocity=3, this dispatcher only branches
    # for Static/Earthworm/RandomVelocity. Value 3 is handled elsewhere.
    value_i = _present_signed(params, 1)
    if value_i in (0, 1, 2):
        result = replace(result, speed_mode=SpeedMode(value_i))

    acc_dec = _enum_value(params, 2, AccDecMode)
    if acc_dec is not None:
        result = replace(result, acc_dec=AccDecMode(acc_dec))

    visibility = _enum_value(params, 16, VisibilityMode)
    if visibility is not None:
        result = replace(result, visibility=VisibilityMode(visibility))

    for metadata_id, field_name in (
        (17, "freedom"),
        (18, "flash"),
        (21, "exceed"),
        (22, "nx"),
        (34, "snake"),
        (35, "zigzag"),
        (48, "mirror_turn"),
        (49, "mirror_lr"),
        (50, "random"),
        (64, "judge_bank"),
        (66, "judge_reverse"),
        (67, "hide_judge"),
        (68, "judge_by_note"),
        (71, "free_performance"),
    ):
        enabled = _bool_value(params, metadata_id)
        if enabled is not None:
            result = replace(result, **{field_name: enabled})

    value_i = _present_signed(params, 19)
    if value_i is not None:
        result = replace(result, random_skin=value_i)
    result = _apply_skins(params, result)

    value_i = _present_signed(params, 32)
    if value_i is not None:
        result = _apply_sequence_transform(result, value_i, allow_mid=allow_mid)

    throw = _enum_value(params, 33, ThrowMode)
    if throw is not None:
        result = replace(result, throw=ThrowMode(throw))

    value_i = _present_signed(params, 65)
    if value_i is not None:
        perfect_frame, interval_frame = _judge_parameter(value_i)
        result = replace(
            result,
            perfect_frame=perfect_frame,
            interval_frame=interval_frame,
        )

    value_i = _present_signed(params, 69)
    if value_i is not None:
        result = _apply_combo_display(result, value_i)

    # Param 70 is deliberately declared twice in PUMP.Param. The dispatcher
    # reads it twice and writes the same (value - 1) delta to both factors.
    value_f = _present_float(params, 70)
    if value_f is not None:
        adjusted = value_f - 1.0
        result = replace(
            result,
            alt_skin_score_factor=adjusted,
            alt_skin_gauge_factor=adjusted,
        )

    for metadata_id, field_name in (
        (80, "gauge_max"),
        (81, "gauge_display_max"),
        (82, "gauge_initial_value"),
        (84, "miss_combo_break"),
        (85, "gauge_link_factor"),
    ):
        value_i = _present_signed(params, metadata_id)
        if value_i is not None:
            result = replace(result, **{field_name: value_i})

    enabled = _bool_value(params, 83)
    if enabled is not None:
        result = replace(result, stage_break=enabled)

    # mpmSpeedBoost (1110) is queried but its return value is discarded by this
    # routine. mpmSpeedX (1111), however, multiplies GameModifier.Speed.
    value_f = _present_float(params, 1111)
    if value_f is not None:
        result = replace(result, speed=result.speed * value_f)

    return result
