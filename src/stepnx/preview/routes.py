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
    policy = RoutePolicy(policy)
    if policy is RoutePolicy.SEEDED and seed is None:
        raise ValueError("seeded route resolution requires an explicit seed")
    rng = random.Random(seed)
    choices = {} if manual is None else dict(manual)
    decisions: list[RouteDecision] = []
    diagnostics: list[RouteDiagnostic] = []
    metrics = PreviewMetrics()
    random_bank_indices: dict[int, int] = {}

    def random_bank_choice(split) -> PreviewBlock | None:
        """Reuse one Block index for every Split in the same random bank."""

        bank = split.group
        if bank == 0:
            # Zero lower bits mean there is no persistent bank. Every 0x80
            # occurrence is a fresh random event, and 0x40 does not inherit a
            # preceding 0x80 choice either.
            return rng.choice(split.blocks)
        if bank not in random_bank_indices:
            random_bank_indices[bank] = rng.randrange(len(split.blocks))
        index = random_bank_indices[bank]
        if index >= len(split.blocks):
            diagnostics.append(
                RouteDiagnostic(
                    "route.random-bank-shape",
                    split.stable_id,
                    f"Random bank {bank} selected Block index {index}, but this "
                    f"Split contains only {len(split.blocks)} Blocks",
                )
            )
            return None
        return split.blocks[index]

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

        if policy is RoutePolicy.MANUAL:
            selected = choices.get(split.stable_id)
            if selected is None and len(split.blocks) == 1:
                selected = split.blocks[0].stable_id
                reason = "only Block"
            if selected is None:
                diagnostics.append(
                    RouteDiagnostic(
                        "route.manual-choice-required",
                        split.stable_id,
                        "Manual preview requires a Block choice for this Split",
                    )
                )
            else:
                try:
                    chosen = split.block(selected)
                    reason = reason or "manual choice"
                except KeyError:
                    diagnostics.append(
                        RouteDiagnostic(
                            "route.invalid-manual-choice",
                            split.stable_id,
                            f"Block {selected} does not belong to this Split",
                        )
                    )
        elif policy is RoutePolicy.SEEDED:
            if split.random_at_start or split.random_at_trigger:
                chosen = random_bank_choice(split)
                reason = (
                    "independent random event"
                    if split.group == 0
                    else f"random bank {split.group} engine choice"
                )
            else:
                selected = choices.get(split.stable_id)
                if selected is None and len(split.blocks) == 1:
                    selected = split.blocks[0].stable_id
                    reason = "only Block"
                if selected is None:
                    diagnostics.append(
                        RouteDiagnostic(
                            "route.manual-choice-required",
                            split.stable_id,
                            "Non-random Split requires the active Block choice",
                        )
                    )
                else:
                    try:
                        chosen = split.block(selected)
                        reason = reason or "active non-random Block"
                    except KeyError:
                        diagnostics.append(
                            RouteDiagnostic(
                                "route.invalid-manual-choice",
                                split.stable_id,
                                f"Block {selected} does not belong to this Split",
                            )
                        )
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
            elif len(eligible) == 1:
                chosen = eligible[0]
                reason = "all-perfect conditions"
            elif len(eligible) > 1 and (
                split.random_at_start or split.random_at_trigger
            ):
                if seed is None:
                    diagnostics.append(
                        RouteDiagnostic(
                            "route.seed-required",
                            split.stable_id,
                            "Random all-perfect resolution requires an explicit seed",
                        )
                    )
                else:
                    eligible_indices = {
                        block.index: block for block in eligible
                    }
                    bank_choice = random_bank_choice(split)
                    if (
                        bank_choice is not None
                        and bank_choice.index in eligible_indices
                    ):
                        chosen = eligible_indices[bank_choice.index]
                        random_label = (
                            "independent random event"
                            if split.group == 0
                            else f"random bank {split.group}"
                        )
                        reason = (
                            f"all-perfect {random_label} seeded choice ({seed})"
                        )
                    elif bank_choice is not None:
                        diagnostics.append(
                            RouteDiagnostic(
                                "route.random-bank-ineligible",
                                split.stable_id,
                                f"Random bank {split.group} selected Block "
                                f"index {bank_choice.index}, which does not match "
                                "the simulated state",
                            )
                        )
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
