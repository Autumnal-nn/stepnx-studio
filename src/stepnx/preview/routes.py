from __future__ import annotations

import random
from dataclasses import dataclass, replace
from enum import Enum

from stepnx.core.model import NoteRow, PackedNoteRow
from stepnx.preview.snapshot import PreviewBlock, PreviewSnapshot


class RoutePolicy(str, Enum):
    MANUAL = "manual"
    SEEDED = "seeded"
    ALL_PERFECT = "all-perfect"


_ALL_PERFECT_PROFILES = frozenset(("nxa-native", "nxa-step5-patched"))


@dataclass(frozen=True, slots=True)
class PreviewMetrics:
    perfect: int = 0
    great: int = 0
    good: int = 0
    bad: int = 0
    miss: int = 0
    step_g: int = 0
    step_w: int = 0
    step_a: int = 0
    step_b: int = 0
    step_c: int = 0
    correct: int = 0
    wrong: int = 0

    def value(self, metadata_id: int) -> int | None:
        names = (
            "perfect",
            "great",
            "good",
            "bad",
            "miss",
            "step_g",
            "step_w",
            "step_a",
            "step_b",
            "step_c",
        )
        if 0 <= metadata_id < len(names):
            return int(getattr(self, names[metadata_id]))
        if metadata_id == 11:
            return self.correct
        if metadata_id == 12:
            return self.wrong
        return None


@dataclass(frozen=True, slots=True)
class RouteDecision:
    split_id: int
    block_id: int
    policy: RoutePolicy
    reason: str
    candidates: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RouteDiagnostic:
    code: str
    split_id: int
    message: str


@dataclass(frozen=True, slots=True)
class ResolvedRoute:
    policy: RoutePolicy
    seed: int | None
    decisions: tuple[RouteDecision, ...]
    final_metrics: PreviewMetrics
    diagnostics: tuple[RouteDiagnostic, ...]

    @property
    def is_executable(self) -> bool:
        return not self.diagnostics

    def block_id(self, split_id: int) -> int:
        for decision in self.decisions:
            if decision.split_id == split_id:
                return decision.block_id
        raise KeyError(split_id)


def _judged_notes(block: PreviewBlock) -> int:
    total = 0
    for row in block.rows:
        if not isinstance(row, (NoteRow, PackedNoteRow)):
            continue
        if any(
            cell.note_type in (0x3, 0x7, 0xB, 0xF)
            and (cell.raw[0] & 0x60) != 0x20
            for cell in row.cells
        ):
            total += 1
    return total


def _advance_all_perfect(
    metrics: PreviewMetrics, block: PreviewBlock
) -> PreviewMetrics:
    return replace(
        metrics,
        perfect=metrics.perfect + _judged_notes(block),
        correct=metrics.correct + block.brain_question_count,
    )


def _matches(block: PreviewBlock, metrics: PreviewMetrics) -> tuple[bool, str | None]:
    for clause in block.conditions:
        value = metrics.value(clause.metadata_id)
        if value is None:
            return False, f"{clause.metric} has no proven all-perfect simulation"
        if value < clause.minimum:
            return False, None
        if clause.maximum and value > clause.maximum:
            return False, None
    return True, None


def resolve_route(
    snapshot: PreviewSnapshot,
    policy: RoutePolicy | str,
    *,
    seed: int | None = None,
    manual: dict[int, int] | None = None,
) -> ResolvedRoute:
    """Resolve one Block per Split while preserving selector-bank state.

    ``0x80`` is the only random selector bit. A successful selection on a Split
    with a non-zero lower-five-bit bank records the selected Block *index* for
    that bank. ``0x40`` is a follower: when that bank already has a selection,
    the same Block index is reused. The remembered selection may originate from
    ``0x81`` random selection or from conditions/manual choice on a banked Split
    such as ``0x01``.

    A follower encountered before its bank has any remembered selection is not
    itself treated as random. It falls back to the ordinary local candidate
    resolution for that Split; the resulting choice then establishes the bank
    state. This keeps malformed/synthetic leading followers usable without
    inventing a second random-selection mode.

    The internal snapshot field is still named ``random_at_trigger`` for API
    compatibility. It is interpreted here exclusively as the 0x40 follower bit.
    """

    policy = RoutePolicy(policy)
    if policy is RoutePolicy.SEEDED and seed is None:
        raise ValueError("seeded route resolution requires an explicit seed")
    rng = random.Random(seed)
    choices = {} if manual is None else dict(manual)
    decisions: list[RouteDecision] = []
    diagnostics: list[RouteDiagnostic] = []
    metrics = PreviewMetrics()
    bank_indices: dict[int, int] = {}

    def remember_bank_selection(split, block: PreviewBlock) -> None:
        bank = int(split.group)
        if bank:
            bank_indices[bank] = int(block.index)

    def random_selector_choice(split) -> PreviewBlock:
        return rng.choice(split.blocks)

    def follower_choice(split) -> tuple[PreviewBlock | None, bool]:
        """Return (choice, has_prior_state).

        ``has_prior_state`` distinguishes a follower that has nothing to follow
        yet from one whose remembered index is structurally incompatible with
        the current Split.
        """

        bank = int(split.group)
        if bank == 0:
            # No bank identity exists to remember. Preserve the historical
            # unbanked compatibility behavior without exposing 0x40 as a random
            # selector mode in the authoring UI.
            return rng.choice(split.blocks), True
        if bank not in bank_indices:
            return None, False
        index = bank_indices[bank]
        if index >= len(split.blocks):
            diagnostics.append(
                RouteDiagnostic(
                    "route.follower-bank-shape",
                    split.stable_id,
                    f"Follower bank {bank} reuses Block index {index}, but this "
                    f"Split contains only {len(split.blocks)} Blocks",
                )
            )
            return None, True
        return split.blocks[index], True

    def local_manual_choice(split, *, seeded: bool) -> tuple[PreviewBlock | None, str]:
        selected = choices.get(split.stable_id)
        if selected is None and len(split.blocks) == 1:
            return split.blocks[0], "only Block"
        if selected is None:
            diagnostics.append(
                RouteDiagnostic(
                    "route.manual-choice-required",
                    split.stable_id,
                    (
                        "Non-random Split requires the active Block choice"
                        if seeded
                        else "Manual preview requires a Block choice for this Split"
                    ),
                )
            )
            return None, ""
        try:
            return split.block(selected), "active non-random Block" if seeded else "manual choice"
        except KeyError:
            diagnostics.append(
                RouteDiagnostic(
                    "route.invalid-manual-choice",
                    split.stable_id,
                    f"Block {selected} does not belong to this Split",
                )
            )
            return None, ""

    if (
        policy is RoutePolicy.ALL_PERFECT
        and snapshot.profile not in _ALL_PERFECT_PROFILES
    ):
        return ResolvedRoute(
            policy,
            seed,
            (),
            metrics,
            (
                RouteDiagnostic(
                    "route.unsupported-profile",
                    0,
                    f"All-perfect simulation is not defined for profile {snapshot.profile!r}",
                ),
            ),
        )

    for split in snapshot.splits:
        if not split.blocks:
            diagnostics.append(
                RouteDiagnostic(
                    "route.empty-split", split.stable_id, "Split has no Blocks"
                )
            )
            continue

        candidates = tuple(block.stable_id for block in split.blocks)
        chosen: PreviewBlock | None = None
        reason = ""
        follower = bool(split.random_at_trigger) and not bool(split.random_at_start)
        follower_had_state = False

        if follower:
            chosen, follower_had_state = follower_choice(split)
            if chosen is not None:
                reason = (
                    "unbanked follower compatibility choice"
                    if int(split.group) == 0
                    else f"follower bank {split.group} -> Block index {chosen.index}"
                )

        if policy is RoutePolicy.MANUAL:
            if chosen is None and not follower_had_state:
                chosen, reason = local_manual_choice(split, seeded=False)

        elif policy is RoutePolicy.SEEDED:
            if split.random_at_start:
                chosen = random_selector_choice(split)
                follower_had_state = False
                reason = (
                    "independent random event"
                    if split.group == 0
                    else f"random bank {split.group} selector choice"
                )
            elif chosen is None and not follower_had_state:
                chosen, reason = local_manual_choice(split, seeded=True)

        else:
            eligible: list[PreviewBlock] = []
            unsupported: list[str] = []
            for block in split.blocks:
                matches, error = _matches(block, metrics)
                if error is not None:
                    unsupported.append(f"Block {block.index}: {error}")
                elif matches:
                    eligible.append(block)

            if unsupported:
                diagnostics.append(
                    RouteDiagnostic(
                        "route.unsupported-condition",
                        split.stable_id,
                        "; ".join(unsupported),
                    )
                )
                chosen = None
            elif follower_had_state:
                if chosen is not None:
                    eligible_by_index = {block.index: block for block in eligible}
                    remembered_index = chosen.index
                    chosen = eligible_by_index.get(remembered_index)
                    if chosen is None:
                        diagnostics.append(
                            RouteDiagnostic(
                                "route.follower-bank-ineligible",
                                split.stable_id,
                                f"Follower bank {split.group} reuses Block index "
                                f"{remembered_index}, which does not match the simulated state",
                            )
                        )
                    elif int(split.group) != 0:
                        reason = f"all-perfect follower bank {split.group} -> Block index {chosen.index}"
            elif len(eligible) == 1:
                chosen = eligible[0]
                reason = "all-perfect conditions"
            elif len(eligible) > 1 and split.random_at_start:
                if seed is None:
                    diagnostics.append(
                        RouteDiagnostic(
                            "route.seed-required",
                            split.stable_id,
                            "Random all-perfect resolution requires an explicit seed",
                        )
                    )
                else:
                    eligible_indices = {block.index: block for block in eligible}
                    random_choice = random_selector_choice(split)
                    chosen = eligible_indices.get(random_choice.index)
                    if chosen is None:
                        diagnostics.append(
                            RouteDiagnostic(
                                "route.random-bank-ineligible",
                                split.stable_id,
                                f"Random bank {split.group} selected Block "
                                f"index {random_choice.index}, which does not match "
                                "the simulated state",
                            )
                        )
                    else:
                        random_label = (
                            "independent random event"
                            if split.group == 0
                            else f"random bank {split.group}"
                        )
                        reason = f"all-perfect {random_label} seeded choice ({seed})"
            elif len(eligible) > 1:
                diagnostics.append(
                    RouteDiagnostic(
                        "route.ambiguous",
                        split.stable_id,
                        "Multiple Blocks match all-perfect state; choose manually",
                    )
                )
            else:
                diagnostics.append(
                    RouteDiagnostic(
                        "route.no-match",
                        split.stable_id,
                        "No Block matches the simulated all-perfect state",
                    )
                )

        if chosen is not None:
            remember_bank_selection(split, chosen)
            decisions.append(
                RouteDecision(
                    split.stable_id,
                    chosen.stable_id,
                    policy,
                    reason,
                    candidates,
                )
            )
            if policy is RoutePolicy.ALL_PERFECT:
                metrics = _advance_all_perfect(metrics, chosen)

    return ResolvedRoute(policy, seed, tuple(decisions), metrics, tuple(diagnostics))
