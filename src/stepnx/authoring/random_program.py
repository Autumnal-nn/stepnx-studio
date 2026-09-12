from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from stepnx.authoring.random_state import (
    BankEpisode,
    RandomPoolPlan,
    RandomPoolPolicy,
    RandomStructureAnalysis,
    TicketMapping,
    analyze_random_structure,
    plan_random_pool,
)
from stepnx.authoring.snapshot import AuthoringSnapshot


class RandomCompileError(ValueError):
    """Raised when random state cannot be materialized safely."""


class RandomControlKind(str, Enum):
    WRAP_BEFORE_SPLIT = "wrap-before-split"
    RETURN_AFTER_SPLIT = "return-after-split"


@dataclass(frozen=True, slots=True)
class RandomControl:
    kind: RandomControlKind
    split_index: int
    bank_id: int = 0


@dataclass(frozen=True, slots=True)
class CompiledRandomProgram:
    """Target-independent materialization of NX random state.

    ``helper_snapshots`` are ordinary authoring snapshots with every random and
    random-bank-follow block choice already materialized for one helper identity.
    Conditional selector banks are intentionally left unresolved here so the
    target's Division compiler can preserve them as runtime branches.
    """

    base_snapshot: AuthoringSnapshot
    helper_snapshots: tuple[AuthoringSnapshot, ...]
    controls: tuple[RandomControl, ...]
    analysis: RandomStructureAnalysis
    pool: RandomPoolPlan

    @property
    def helper_count(self) -> int:
        return len(self.helper_snapshots)


def _mapping_by_split(pool: RandomPoolPlan) -> dict[int, TicketMapping]:
    return {mapping.split_index: mapping for mapping in pool.mappings}


def _episode_by_store(episodes: tuple[BankEpisode, ...]) -> dict[int, BankEpisode]:
    return {episode.store_split_index: episode for episode in episodes}


def _store_for_follower(
    episodes: tuple[BankEpisode, ...],
    follower_split_index: int,
) -> BankEpisode | None:
    for episode in episodes:
        if follower_split_index in episode.follower_split_indices:
            return episode
    return None


def _conditional_store_before(
    snapshot: AuthoringSnapshot,
    analysis: RandomStructureAnalysis,
    follower_split_index: int,
    bank_id: int,
) -> int | None:
    """Find the latest non-random selector that can establish ``bank_id``.

    NX uses the low selector bits for more than random state.  In official
    Fiesta EX charts, for example, raw 0x01 selects a conditional Block and
    stores its index in bank 1, while later 0x41 Splits reuse that same index.
    Those followers are not random orphans and belong to the Division compiler.
    """

    latest: int | None = None
    for split_index in range(follower_split_index):
        selector = analysis.selectors[split_index]
        if selector.bank_id != bank_id:
            continue
        if selector.random_start or selector.follow_bank:
            continue
        if not snapshot.splits[split_index].blocks:
            continue
        latest = split_index
    return latest


def _validate_materializable(
    snapshot: AuthoringSnapshot,
    analysis: RandomStructureAnalysis,
) -> None:
    for diagnostic in analysis.diagnostics:
        if diagnostic.code == "random.orphan-bank-follow":
            selector = analysis.selectors[diagnostic.split_index]
            if _conditional_store_before(
                snapshot,
                analysis,
                diagnostic.split_index,
                selector.bank_id,
            ) is not None:
                continue
        raise RandomCompileError(
            f"{diagnostic.code} at split {diagnostic.split_index}: {diagnostic.message}"
        )

    # Overlapping live random banks and a new draw while another bank is live
    # are materializable as a joint helper identity. Conditional banks are left
    # untouched and are resolved later by the target-specific branch compiler.
    for split_index in analysis.random_split_indices:
        if not snapshot.splits[split_index].blocks:
            raise RandomCompileError(f"random split {split_index} has no blocks")


def _helper_choices(
    snapshot: AuthoringSnapshot,
    analysis: RandomStructureAnalysis,
    pool: RandomPoolPlan,
) -> tuple[dict[int, int], ...]:
    """Return split-index -> block-index random choices for every helper state."""

    mappings = _mapping_by_split(pool)
    choices = [dict() for _ in range(pool.helper_count)]

    for split_index in analysis.random_split_indices:
        mapping = mappings[split_index]
        for helper_index, block_index in enumerate(mapping.helper_to_block):
            choices[helper_index][split_index] = block_index

        selector = analysis.selectors[split_index]
        if not selector.stores_bank:
            continue
        episode = _episode_by_store(analysis.bank_episodes)[split_index]
        for follower_index in episode.follower_split_indices:
            for helper_index, block_index in enumerate(mapping.helper_to_block):
                choices[helper_index][follower_index] = block_index

    # A 0x4n follower without a random BankEpisode may legally follow an earlier
    # conditional 0x0n store. True orphans have already been rejected above.
    for split_index, selector in enumerate(analysis.selectors):
        if not selector.follows_named_bank:
            continue
        episode = _store_for_follower(analysis.bank_episodes, split_index)
        if episode is not None:
            continue
        if _conditional_store_before(
            snapshot,
            analysis,
            split_index,
            selector.bank_id,
        ) is not None:
            continue
        raise RandomCompileError(
            f"bank follower at split {split_index} could not be associated with a store"
        )

    return tuple(choices)


def _materialize_snapshot(
    base: AuthoringSnapshot,
    choices: dict[int, int],
) -> AuthoringSnapshot:
    snapshot = base
    for split_index, block_index in sorted(choices.items()):
        split = snapshot.splits[split_index]
        if block_index >= len(split.blocks):
            raise RandomCompileError(
                f"split {split_index} has no block {block_index} while materializing helper"
            )
        snapshot = snapshot.with_active_block(split.stable_id, split.blocks[block_index].stable_id)
    return snapshot


def _controls(analysis: RandomStructureAnalysis) -> tuple[RandomControl, ...]:
    controls: list[RandomControl] = []
    episode_by_store = _episode_by_store(analysis.bank_episodes)

    for split_index in analysis.random_split_indices:
        selector = analysis.selectors[split_index]
        controls.append(
            RandomControl(
                RandomControlKind.WRAP_BEFORE_SPLIT,
                split_index,
                selector.bank_id if selector.stores_bank else 0,
            )
        )

        if selector.stores_bank:
            episode = episode_by_store[split_index]
            controls.append(
                RandomControl(
                    RandomControlKind.RETURN_AFTER_SPLIT,
                    episode.last_use_split_index,
                    selector.bank_id,
                )
            )
        else:
            controls.append(
                RandomControl(RandomControlKind.RETURN_AFTER_SPLIT, split_index, 0)
            )

    order = {
        RandomControlKind.RETURN_AFTER_SPLIT: 0,
        RandomControlKind.WRAP_BEFORE_SPLIT: 1,
    }
    controls.sort(key=lambda control: (control.split_index, order[control.kind], control.bank_id))
    return tuple(controls)


def compile_random_program(
    snapshot: AuthoringSnapshot,
    policy: RandomPoolPolicy = RandomPoolPolicy(),
) -> CompiledRandomProgram:
    """Materialize random choices while preserving conditional selector banks."""

    analysis = analyze_random_structure(snapshot)
    _validate_materializable(snapshot, analysis)
    pool = plan_random_pool(snapshot, policy)
    helper_choices = _helper_choices(snapshot, analysis, pool)
    helpers = tuple(
        _materialize_snapshot(snapshot, choices) for choices in helper_choices
    )
    return CompiledRandomProgram(
        base_snapshot=snapshot,
        helper_snapshots=helpers,
        controls=_controls(analysis),
        analysis=analysis,
        pool=pool,
    )
