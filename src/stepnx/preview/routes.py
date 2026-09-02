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

    The two selector bits run at different phases:

    - ``0x80`` preselects a random Block while the chart is loaded. Seeded
      preview therefore consumes every 0x80 draw before route traversal begins.
    - ``0x40`` performs a bank lookup when its Split is reached. Lower bits 1..31
      are real banks and reuse the latest Block index selected for that bank.
    - lower bits 0 mean there is no bank. Raw ``0x40`` consequently cannot find
      a bank and falls back to a fresh random choice at Split entry.

    A banked non-random Split such as ``0x01`` can establish bank 1 through its
    condition/active candidate; a later ``0x41`` then reuses that Block index.
    The internal snapshot field remains named ``random_at_trigger`` for API
    compatibility, but it represents the raw 0x40 bit rather than one universal
    random mode.

    Route policies deliberately remain separate from runtime selector mechanics:
    MANUAL is an explicit preview override, while ALL_PERFECT accepts a uniquely
    matching branch before consulting selector state. SEEDED is the policy that
    reproduces automatic selector timing and bank following.
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

    # 0x80 is resolved at chart load, before any 0x40 block-start fallback can
    # consume RNG state. This distinction is observable when both forms appear
    # in one chart even though both ultimately select a Block index.
    load_random_choices: dict[int, PreviewBlock] = {}
    if policy is RoutePolicy.SEEDED or (
        policy is RoutePolicy.ALL_PERFECT and seed is not None
    ):
        for split in snapshot.splits:
            if split.blocks and split.random_at_start:
                load_random_choices[split.stable_id] = rng.choice(split.blocks)

    def remember_bank_selection(split, block: PreviewBlock) -> None:
        bank = int(split.group)
        if 1 <= bank <= 31:
            bank_indices[bank] = int(block.index)

    def follower_choice(split) -> PreviewBlock | None:
        bank = int(split.group)
        index = bank_indices.get(bank)
        if index is None:
            diagnostics.append(
                RouteDiagnostic(
                    "route.follower-bank-unset",
                    split.stable_id,
                    f"Follower bank {bank} has no earlier selection to reuse",
                )
            )
            return None
        if index >= len(split.blocks):
            diagnostics.append(
                RouteDiagnostic(
                    "route.follower-bank-shape",
                    split.stable_id,
                    f"Follower bank {bank} reuses Block index {index}, but this "
                    f"Split contains only {len(split.blocks)} Blocks",
                )
            )
            return None
        return split.blocks[index]

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
            return (
                split.block(selected),
                "active non-random Block" if seeded else "manual choice",
            )
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
        bank = int(split.group)
        load_random = bool(split.random_at_start)
        # Existing runtime validation gives 0x80 precedence when both selector
        # bits are present, so 0xC0/0xC1 remain raw-preserved but do not execute
        # a second 0x40 selection phase in this resolver.
        block_start_random = (
            bool(split.random_at_trigger) and not load_random and bank == 0
        )
        follower = (
            bool(split.random_at_trigger) and not load_random and 1 <= bank <= 31
        )

        if policy is RoutePolicy.MANUAL:
            # Manual preview is intentionally authoritative. It must be able to
            # inspect any branch even when the serialized selector would choose
            # or follow another one at runtime.
            chosen, reason = local_manual_choice(split, seeded=False)

        elif policy is RoutePolicy.SEEDED:
            if load_random:
                chosen = load_random_choices[split.stable_id]
                reason = (
                    "independent random event"
                    if bank == 0
                    else f"random bank {bank} selector choice"
                )
            elif block_start_random:
                chosen = rng.choice(split.blocks)
                # Retain the historical reason string consumed by regression
                # tests. User-facing UI names this precisely as block-start random.
                reason = "independent random event"
            elif follower:
                chosen = follower_choice(split)
                if chosen is not None:
                    reason = f"follower bank {bank} -> Block index {chosen.index}"
            else:
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
            elif len(eligible) == 1:
                # Conditions have already produced a unique answer. Selector
                # state is only needed to disambiguate multiple viable branches.
                chosen = eligible[0]
                reason = "all-perfect conditions"
            elif follower:
                bank_choice = follower_choice(split)
                if bank_choice is not None:
                    eligible_by_index = {block.index: block for block in eligible}
                    chosen = eligible_by_index.get(bank_choice.index)
                    if chosen is None:
                        diagnostics.append(
                            RouteDiagnostic(
                                "route.follower-bank-ineligible",
                                split.stable_id,
                                f"Follower bank {bank} reuses Block index "
                                f"{bank_choice.index}, which does not match the simulated state",
                            )
                        )
                    else:
                        reason = (
                            f"all-perfect follower bank {bank} -> Block index {chosen.index}"
                        )
            elif len(eligible) > 1 and (load_random or block_start_random):
                if seed is None:
                    diagnostics.append(
                        RouteDiagnostic(
                            "route.seed-required",
                            split.stable_id,
                            "Random all-perfect resolution requires an explicit seed",
                        )
                    )
                else:
                    random_choice = (
                        load_random_choices[split.stable_id]
                        if load_random
                        else rng.choice(split.blocks)
                    )
                    eligible_by_index = {block.index: block for block in eligible}
                    chosen = eligible_by_index.get(random_choice.index)
                    if chosen is None:
                        diagnostics.append(
                            RouteDiagnostic(
                                "route.random-bank-ineligible",
                                split.stable_id,
                                f"Random selection chose Block index {random_choice.index}, "
                                "which does not match the simulated state",
                            )
                        )
                    else:
                        if load_random:
                            random_label = (
                                "independent random event"
                                if bank == 0
                                else f"random bank {bank}"
                            )
                        else:
                            random_label = "block-start random fallback"
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
