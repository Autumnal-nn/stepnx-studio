from __future__ import annotations

from math import trunc


# PUMPPlayer.GetScore's compiler-generated int[6] table. The backing-field
# bytes in GameAssembly.dll match this sequence exactly.
_SCORE_TABLE = (1000, 1000, 500, 100, -200, -500)


def native_base_score(
    grade: int,
    *,
    combo: int,
    note_count: int,
    ordinary_note_miss: bool = False,
) -> int:
    """Port PUMPPlayer.GetScore RVA 0x748A40.

    ``combo`` is the per-bank combo *after* Perfect/Great increment, matching
    JudgeStep_PostProcess. ``note_count`` is the JudgeUnit total count used for
    the 3-note and 4+-note chord multipliers. The native caller's special Miss
    boolean is ``ordinary note_count != 0`` rather than the total long count.
    """

    if grade < 0 or grade > 4:
        return 0
    if grade == 4 and ordinary_note_miss:
        value = -300
    else:
        value = _SCORE_TABLE[grade]

    if grade <= 1 and combo >= 51:
        value += 1000

    if note_count == 3:
        value = trunc(value * 1.5)
    elif note_count > 3:
        value *= 2
    return value


def native_score_delta(
    grade: int,
    *,
    combo: int,
    note_count: int,
    ordinary_note_miss: bool,
    alt_skin_factor: float,
) -> int:
    """Return JudgeStep_PostProcess's final AddCount score delta."""

    base = native_base_score(
        grade,
        combo=combo,
        note_count=note_count,
        ordinary_note_miss=ordinary_note_miss,
    )
    return trunc(float(base) * float(alt_skin_factor))


def add_score_floor_zero(score: int, delta: int) -> int:
    """Port AddCount's non-negative clamp for negative score additions."""

    return max(0, int(score) + int(delta))
