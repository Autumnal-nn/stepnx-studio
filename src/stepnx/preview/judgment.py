from __future__ import annotations

from dataclasses import dataclass
from math import nan
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from stepnx.preview.events import PreviewEvent


ATTR_JUDGE_MASK = 0xE0
ATTR_NO_JUDGE = 0x20
ATTR_NO_MISS = 0x20
ATTR_NO_RUSH = 0x10
ATTR_LONG_MASK = 0x0C
ATTR_LONG_FLAGS = 0x1C
ATTR_TYPE_MASK = 0x03
TYPE_NORMAL = 0x03
EFFECT_YTABLE_MASK = 0x0F
EFFECT_VISIBLE_BIT = 0x01
PARAM_MASK = 0x3FFF
BANK_SHIFT = 14
EXTRA_JUDGE_BY_NOTE_CHECKED = 0x02
JUDGE_MISS = 4
JUDGE_GREAT = 1


@dataclass(frozen=True, slots=True)
class JudgeLineSummary:
    """Arguments assembled by PUMPPlayer.JudgeLine before JudgeUnit."""

    bank: int
    eligible: tuple[PreviewEvent, ...]
    rush_notes: tuple[PreviewEvent, ...]
    note_count: int
    long_note_count: int
    alt_skin_count: int
    visible: bool
    no_miss: bool
    play_sound: bool

    @property
    def has_judge_unit(self) -> bool:
        return self.note_count > 0 or self.long_note_count > 0


@dataclass(frozen=True, slots=True)
class JudgeNoteDecision:
    """Source-derived routing decision for PUMPPlayer.JudgeNote."""

    routed_to_judge_unit: bool
    judge_by_note_checked: bool
    forced_miss: bool
    note_count: int
    long_note_count: int
    alt_skin_count: int
    visible: bool
    no_miss: bool


@dataclass(frozen=True, slots=True)
class JudgeUnitProjection:
    """JudgeUnit state immediately before JudgeStep_PostProcess.

    Counter writes, sound/effect calls, score and gauge are deliberately left
    out. Those are consumers of this state and belong to the later scoring and
    gauge parity item.
    """

    bank: int
    input_grade: int
    judgment: int
    visible: bool
    no_miss: bool
    no_miss_invisible: bool
    note_count: int
    long_note_count: int
    total_note_count: int
    alt_skin_count: int
    alt_skin_factor: float
    play_sound: bool
    return_value: bool


def summarize_judge_line(
    events: Iterable[PreviewEvent],
    bank: int,
    *,
    judge_by_note_checked: frozenset[tuple[int, int, int, int]] = frozenset(),
) -> JudgeLineSummary:
    """Port PUMPPlayer.JudgeLine's note scan for one bank and encoded line.

    Exact source rules recovered from RVA 0x7474D0:
    - JudgeMask == NoJudge is skipped;
    - Type must be Normal and Bank must match;
    - Param >= 3 contributes one AltSkin count;
    - long+YTable without bNoRush is a rush/roll note and leaves JudgeLine;
    - bNoRush long notes contribute LongNoteCount;
    - ordinary notes already consumed by JudgeByNote do not increment NoteCount;
    - bVisible is OR(effect bit 0), bNoMiss is AND(attr bit 0x20);
    - any ordinary note forces playSound, while regular long components request
      it through the long-note path.
    """

    eligible: list[PreviewEvent] = []
    rush_notes: list[PreviewEvent] = []
    note_count = 0
    long_note_count = 0
    alt_skin_count = 0
    visible = False
    no_miss = True
    play_sound = False

    for event in events:
        if event.judge_mask == ATTR_NO_JUDGE:
            continue
        if event.base_note_type != TYPE_NORMAL:
            continue
        if event.bank != bank:
            continue

        eligible.append(event)
        if event.param >= 3:
            alt_skin_count += 1

        if event.long_flags and event.y_table:
            if not event.no_rush:
                rush_notes.append(event)
                continue
            long_note_count += 1
            if event.long_kind:
                play_sound = True
        else:
            key = (event.split_id, event.block_id, event.row_index, event.lane)
            if key not in judge_by_note_checked:
                note_count += 1

        visible = visible or event.visible_for_judge
        no_miss = no_miss and bool(event.attribute & ATTR_NO_MISS)

    if note_count > 0:
        play_sound = True

    return JudgeLineSummary(
        bank=bank,
        eligible=tuple(eligible),
        rush_notes=tuple(rush_notes),
        note_count=note_count,
        long_note_count=long_note_count,
        alt_skin_count=alt_skin_count,
        visible=visible,
        no_miss=no_miss,
        play_sound=play_sound,
    )


def judge_note_decision(
    event: PreviewEvent,
    grade: int,
    *,
    judge_by_note: bool,
) -> JudgeNoteDecision:
    """Port the routing part of PUMPPlayer.JudgeNote RVA 0x747320."""

    rush_long = bool(event.long_kind) and not event.no_rush
    if rush_long:
        return JudgeNoteDecision(
            routed_to_judge_unit=False,
            judge_by_note_checked=False,
            forced_miss=grade < 0,
            note_count=1 if grade < 0 else 0,
            long_note_count=1 if grade < 0 else 0,
            alt_skin_count=0,
            visible=event.visible_for_judge,
            no_miss=False,
        )

    if not judge_by_note:
        return JudgeNoteDecision(False, False, False, 0, 0, 0, False, False)

    has_long_flags = bool(event.long_flags)
    return JudgeNoteDecision(
        routed_to_judge_unit=True,
        judge_by_note_checked=True,
        forced_miss=False,
        note_count=0 if has_long_flags else 1,
        long_note_count=1 if has_long_flags else 0,
        alt_skin_count=event.param // 3,
        visible=event.visible_for_judge,
        no_miss=bool(event.attribute & 0x60),
    )


def project_judge_unit(
    *,
    bank: int,
    grade: int,
    visible: bool,
    no_miss: bool,
    note_count: int,
    long_note_count: int,
    alt_skin_count: int,
    alt_skin_score_factor: float,
    play_sound: bool = False,
) -> JudgeUnitProjection:
    """Port the source-stable pre-PostProcess core of JudgeUnit RVA 0x747A60.

    The native method maps a negative grade to Miss for the public Judgement
    state, keeps a distinct ``bNoMiss && !bVisible`` path, computes the AltSkin
    score factor from the proportion of alternate-skin notes, and returns
    ``grade <= Great``. Its later counter/effect writes and PostProcess call are
    intentionally outside this helper.
    """

    total_note_count = note_count + long_note_count
    if total_note_count:
        alt_skin_factor = 1.0 + (
            alt_skin_count / total_note_count
        ) * alt_skin_score_factor
    else:
        # divss 0/0 is NaN in the native float path. This should not occur for
        # a meaningful JudgeUnit, but retaining it avoids inventing a clamp.
        alt_skin_factor = nan

    return JudgeUnitProjection(
        bank=bank,
        input_grade=grade,
        judgment=grade if grade >= 0 else JUDGE_MISS,
        visible=visible,
        no_miss=no_miss,
        no_miss_invisible=no_miss and not visible,
        note_count=note_count,
        long_note_count=long_note_count,
        total_note_count=total_note_count,
        alt_skin_count=alt_skin_count,
        alt_skin_factor=alt_skin_factor,
        play_sound=play_sound,
        return_value=grade <= JUDGE_GREAT,
    )
