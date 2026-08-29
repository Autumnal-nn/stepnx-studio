from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum
from math import trunc


class SpeedMode(IntEnum):
    STATIC = 0
    EARTHWORM = 1
    RANDOM_VELOCITY = 2


class AccDecMode(IntEnum):
    LINEAR = 0
    ACCELERATION = 1
    DECELERATION = 2


class VisibilityMode(IntEnum):
    VISIBLE = 0
    VANISH = 1
    APPEAR = 2
    VANISH_APPEAR = 3


class ThrowMode(IntEnum):
    FLAT = 0
    SINK = 1
    RISE = 2


@dataclass(frozen=True, slots=True)
class StepParam:
    """One serialized NX20 StepParam pair, retaining source order and duplicates."""

    metadata_id: int
    raw_value: int

    @property
    def signed_value(self) -> int:
        value = self.raw_value & 0xFFFFFFFF
        return value - 0x100000000 if value & 0x80000000 else value


@dataclass(frozen=True, slots=True)
class EffectiveModifier:
    """R!SE state after applying Header StepParams to runtime defaults.

    This is intentionally broader than the fields currently rendered by the
    Studio.  ApplyStepParamToMod mutates GameModifier, player/gauge state and a
    small global option object in one pass.  Keeping those effects together
    gives later preview work one source-derived state instead of rediscovering
    the same Header parameters independently.
    """

    # GameModifier.Clear() defaults recovered from GameAssembly.dll.
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
    mirror: bool = False
    alternate_random: bool = False
    runner: bool = False
    legacy_judge_by_note: bool = False
    perfect_frame: float = 2.5
    interval_frame: float = 2.5
    reverse_grade: bool = False
    judge_hide: bool = False
    judge_by_note: bool = False
    mode_69: int | None = None
    mode_69_local: bool = False
    mode_69_global: bool = False
    parameter_70_a: float = 0.0
    parameter_70_b: float = 0.0
    flag_71: bool = False

    # Proven side effects outside GameModifier.
    exceed_mode: bool = False
    nx_mode: bool = False
    under_attack: bool = False
    drop: bool = False
    maximum_lifebar: int | None = None
    lifebar_display: int | None = None
    starting_lifebar: int | None = None
    stage_break: bool | None = None
    forced_stage_break_miss_combo: int | None = None
    global_parameter_85: int | None = None


def _first_signed(params: tuple[StepParam, ...], metadata_id: int) -> int | None:
    """Port R!SE's first-match StepParam lookup.

    The native lookup walks the serialized int array from the beginning in
    (id, value) pairs.  Duplicate metadata is therefore first-wins, not the
    last-wins behavior a dict conversion would accidentally introduce.
    """

    for param in params:
        if param.metadata_id == metadata_id:
            return param.signed_value
    return None


def _present(params: tuple[StepParam, ...], metadata_id: int) -> int | None:
    value = _first_signed(params, metadata_id)
    return None if value is None or value == -1 else value


def _bool_value(params: tuple[StepParam, ...], metadata_id: int) -> bool | None:
    value = _present(params, metadata_id)
    return None if value is None else value != 0


def _enum_value(
    params: tuple[StepParam, ...], metadata_id: int, enum_type: type[IntEnum]
) -> IntEnum | None:
    value = _present(params, metadata_id)
    if value is None:
        return None
    try:
        return enum_type(value)
    except ValueError:
        return None


def _speed_parameter(value: int) -> float:
    """Port ApplyStepParamToMod's unusual Header speed conversion.

    Positive values through 255 use the historical quarter-speed encoding.
    Zero, negatives other than the -1 sentinel, and values above 255 are stored
    as their direct numeric float value by the R!SE runtime.
    """

    if 0 < value <= 255:
        return value * 0.25
    return float(value)


def _judge_parameter(value: int) -> tuple[float, float]:
    """Port the decimal ID-65 decoder without yet changing preview judgments."""

    x = value + 5
    quotient = trunc(x / 10)
    remainder = x - quotient * 10
    perfect_frame = (75 - quotient) / 10.0
    interval_frame = (10 - remainder) * 0.5
    return perfect_frame, interval_frame


def apply_step_params(
    params: tuple[StepParam, ...],
    base: EffectiveModifier | None = None,
) -> EffectiveModifier:
    """Port the scalar effects of R!SE ApplyStepParamToMod (RVA 0x659F00).

    GameAssembly.dll shows this method reading only the loaded Step's global
    Header StepParam array at Step+0x28.  Split metadata is deliberately not
    merged here: no source path applying Split+0x18 through this dispatcher has
    been recovered.
    """

    result = EffectiveModifier() if base is None else base

    value = _present(params, 0)
    if value is not None:
        result = replace(result, speed=_speed_parameter(value))

    speed_mode = _enum_value(params, 1, SpeedMode)
    if speed_mode is not None:
        result = replace(result, speed_mode=SpeedMode(speed_mode))

    acc_dec = _enum_value(params, 2, AccDecMode)
    if acc_dec is not None:
        result = replace(result, acc_dec=AccDecMode(acc_dec))

    visibility = _enum_value(params, 16, VisibilityMode)
    if visibility is not None:
        result = replace(result, visibility=VisibilityMode(visibility))

    for metadata_id, field_name in (
        (17, "freedom"),
        (18, "flash"),
        (34, "snake"),
        (35, "zigzag"),
        (48, "mirror"),
        (49, "alternate_random"),
        (50, "runner"),
        (64, "legacy_judge_by_note"),
        (66, "reverse_grade"),
        (67, "judge_hide"),
        (68, "judge_by_note"),
        (71, "flag_71"),
    ):
        enabled = _bool_value(params, metadata_id)
        if enabled is not None:
            result = replace(result, **{field_name: enabled})

    value = _present(params, 19)
    if value is not None:
        result = replace(result, random_skin=value)

    throw = _enum_value(params, 33, ThrowMode)
    if throw is not None:
        result = replace(result, throw=ThrowMode(throw))

    value = _present(params, 65)
    if value is not None:
        perfect_frame, interval_frame = _judge_parameter(value)
        result = replace(
            result,
            perfect_frame=perfect_frame,
            interval_frame=interval_frame,
        )

    value = _present(params, 69)
    if value in (0, 1, 2):
        # The binary exposes the state transition but, without dump.cs, the
        # field's public enum name is not safely recoverable.  Preserve it
        # neutrally instead of inventing a label.
        result = replace(
            result,
            mode_69=value,
            mode_69_local=value == 0,
            mode_69_global=value == 2,
        )

    value = _present(params, 70)
    if value is not None:
        adjusted = float(value) - 1.0
        result = replace(result, parameter_70_a=adjusted, parameter_70_b=adjusted)

    for metadata_id, field_name in (
        (21, "exceed_mode"),
        (22, "nx_mode"),
    ):
        enabled = _bool_value(params, metadata_id)
        if enabled is not None:
            result = replace(result, **{field_name: enabled})

    value = _present(params, 32)
    if value in (0, 1, 2, 3):
        result = replace(
            result,
            under_attack=bool(value & 0x01),
            drop=bool(value & 0x02),
        )

    for metadata_id, field_name in (
        (80, "maximum_lifebar"),
        (81, "lifebar_display"),
        (82, "starting_lifebar"),
        (84, "forced_stage_break_miss_combo"),
        (85, "global_parameter_85"),
    ):
        value = _present(params, metadata_id)
        if value is not None:
            result = replace(result, **{field_name: value})

    enabled = _bool_value(params, 83)
    if enabled is not None:
        result = replace(result, stage_break=enabled)

    # R!SE looks up 1110 but does not store its scalar result in this method.
    # ID 1111, however, directly multiplies the already-effective Speed.
    value = _present(params, 1111)
    if value is not None:
        result = replace(result, speed=result.speed * float(value))

    return result
