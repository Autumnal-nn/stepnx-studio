from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from math import gcd

from stepnx.authoring.snapshot import AuthoringSnapshot, SplitSnapshot


SELECT_RANDOM = 0x80
SELECT_FOLLOW = 0x40
SELECT_RECALC = 0x20
SELECT_BANK_MASK = 0x1F


@dataclass(frozen=True, slots=True)
class SplitSelector:
    """Bitwise interpretation of an NX20 split selector byte.

    The selector bits are intentionally exposed independently. Some corpus
    values combine flags, and callers must not collapse those values into a
    single enum before the semantics are known.
    """

    raw: int
    bank_id: int
    random_start: bool
    follow_bank: bool
    recalc_conditions: bool

    @property
    def stores_bank(self) -> bool:
        return self.random_start and self.bank_id != 0

    @property
    def follows_named_bank(self) -> bool:
        return self.follow_bank and self.bank_id != 0


@dataclass(frozen=True, slots=True)
class BankEpisode:
    """One stored random choice and the followers that consume it.

    A later store to the same bank starts a new episode. The lifetime only
    extends through the last follower before that overwrite, because no state
    has to be retained after the final observable use.
    """

    bank_id: int
    store_split_index: int
    follower_split_indices: tuple[int, ...]
    last_use_split_index: int
    block_count: int


@dataclass(frozen=True, slots=True)
class RandomStructureDiagnostic:
    code: str
    split_index: int
    message: str


@dataclass(frozen=True, slots=True)
class RandomStructureAnalysis:
    selectors: tuple[SplitSelector, ...]
    random_split_indices: tuple[int, ...]
    random_arities: tuple[int, ...]
    bank_episodes: tuple[BankEpisode, ...]
    max_live_banks: int
    diagnostics: tuple[RandomStructureDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class TicketMapping:
    """Map uniformly selected helper states onto one NX random split.

    Blocks are kept as distinct slots even when their contents are identical.
    This is deliberate: repeated blocks are probability mass. A 20-block split
    with nineteen equal blocks and one distinct block must remain 95/5, not be
    deduplicated into a 50/50 two-outcome choice.
    """

    split_index: int
    block_count: int
    helper_to_block: tuple[int, ...]
    tickets_per_block: tuple[int, ...]
    max_probability_error: float


@dataclass(frozen=True, slots=True)
class RandomPoolPlan:
    helper_count: int
    exact_helper_count: int
    max_probability_error: float
    mappings: tuple[TicketMapping, ...]


@dataclass(frozen=True, slots=True)
class RandomPoolPolicy:
    """Quality policy for projecting NX random choices onto XSanity Wrap.

    ``max_probability_error`` is expressed as an absolute probability, so
    0.0125 means 1.25 percentage points. ``max_helpers`` is a safety ceiling,
    not a semantic constant of the format.
    """

    max_probability_error: float = 0.0125
    max_helpers: int = 128

    def __post_init__(self) -> None:
        if not 0.0 <= self.max_probability_error < 1.0:
            raise ValueError("max_probability_error must be in [0, 1)")
        if self.max_helpers < 1:
            raise ValueError("max_helpers must be positive")


def decode_split_selector(raw: int) -> SplitSelector:
    if not 0 <= raw <= 0xFF:
        raise ValueError("split selector must fit in one byte")
    return SplitSelector(
        raw=raw,
        bank_id=raw & SELECT_BANK_MASK,
        random_start=bool(raw & SELECT_RANDOM),
        follow_bank=bool(raw & SELECT_FOLLOW),
        recalc_conditions=bool(raw & SELECT_RECALC),
    )


def _episodes_for_bank(
    splits: tuple[SplitSnapshot, ...],
    selectors: tuple[SplitSelector, ...],
    bank_id: int,
) -> tuple[BankEpisode, ...]:
    stores = [
        index
        for index, selector in enumerate(selectors)
        if selector.stores_bank and selector.bank_id == bank_id
    ]
    episodes: list[BankEpisode] = []
    for store_number, store_index in enumerate(stores):
        next_store = stores[store_number + 1] if store_number + 1 < len(stores) else len(splits)
        followers = tuple(
            index
            for index in range(store_index + 1, next_store)
            if selectors[index].follows_named_bank and selectors[index].bank_id == bank_id
        )
        episodes.append(
            BankEpisode(
                bank_id=bank_id,
                store_split_index=store_index,
                follower_split_indices=followers,
                last_use_split_index=followers[-1] if followers else store_index,
                block_count=len(splits[store_index].blocks),
            )
        )
    return tuple(episodes)


def _max_live_banks(episodes: tuple[BankEpisode, ...], split_count: int) -> int:
    maximum = 0
    for split_index in range(split_count):
        live = sum(
            episode.store_split_index <= split_index <= episode.last_use_split_index
            for episode in episodes
        )
        maximum = max(maximum, live)
    return maximum


def analyze_random_structure(snapshot: AuthoringSnapshot) -> RandomStructureAnalysis:
    """Describe NX random decisions without choosing or flattening any branch."""

    splits = snapshot.splits
    selectors = tuple(decode_split_selector(split.raw_select) for split in splits)
    random_indices = tuple(
        index for index, selector in enumerate(selectors) if selector.random_start
    )
    random_arities = tuple(len(splits[index].blocks) for index in random_indices)

    bank_ids = sorted(
        {selector.bank_id for selector in selectors if selector.stores_bank}
    )
    episodes = tuple(
        episode
        for bank_id in bank_ids
        for episode in _episodes_for_bank(splits, selectors, bank_id)
    )

    diagnostics: list[RandomStructureDiagnostic] = []
    for index, selector in enumerate(selectors):
        if selector.follows_named_bank:
            preceding = [
                episode
                for episode in episodes
                if episode.bank_id == selector.bank_id
                and episode.store_split_index < index <= episode.last_use_split_index
            ]
            if not preceding:
                diagnostics.append(
                    RandomStructureDiagnostic(
                        "random.orphan-bank-follow",
                        index,
                        f"split follows bank {selector.bank_id} without a preceding live random store",
                    )
                )
                continue
            episode = preceding[-1]
            follower_blocks = len(splits[index].blocks)
            if follower_blocks != episode.block_count:
                diagnostics.append(
                    RandomStructureDiagnostic(
                        "random.bank-arity-mismatch",
                        index,
                        f"bank {selector.bank_id} stored {episode.block_count} choices but follower has "
                        f"{follower_blocks} blocks",
                    )
                )

    for index in random_indices:
        if not splits[index].blocks:
            diagnostics.append(
                RandomStructureDiagnostic(
                    "random.empty-random-split",
                    index,
                    "random split has no blocks",
                )
            )

    return RandomStructureAnalysis(
        selectors=selectors,
        random_split_indices=random_indices,
        random_arities=random_arities,
        bank_episodes=episodes,
        max_live_banks=_max_live_banks(episodes, len(splits)),
        diagnostics=tuple(diagnostics),
    )


def _lcm(left: int, right: int) -> int:
    if left == 0 or right == 0:
        return 0
    return abs(left * right) // gcd(left, right)


def exact_helper_count(arities: tuple[int, ...]) -> int:
    positive = tuple(arity for arity in arities if arity > 0)
    if not positive:
        return 0
    return reduce(_lcm, positive, 1)


def probability_error(helper_count: int, block_count: int) -> float:
    """Worst per-block probability error for a balanced ticket assignment."""

    if helper_count < 1:
        raise ValueError("helper_count must be positive")
    if block_count < 1:
        raise ValueError("block_count must be positive")
    if helper_count < block_count:
        return 1.0 / block_count

    quotient, remainder = divmod(helper_count, block_count)
    target = 1.0 / block_count
    probabilities = {quotient / helper_count}
    if remainder:
        probabilities.add((quotient + 1) / helper_count)
    return max(abs(probability - target) for probability in probabilities)


def choose_helper_count(
    arities: tuple[int, ...],
    policy: RandomPoolPolicy = RandomPoolPolicy(),
) -> tuple[int, int, float]:
    """Return helper count, exact LCM count, and achieved worst-case error."""

    positive = tuple(arity for arity in arities if arity > 0)
    if not positive:
        return 0, 0, 0.0

    minimum = max(positive)
    if policy.max_helpers < minimum:
        raise ValueError(
            f"max_helpers={policy.max_helpers} cannot cover a random split with {minimum} blocks"
        )

    exact = exact_helper_count(positive)
    for helper_count in range(minimum, policy.max_helpers + 1):
        error = max(probability_error(helper_count, arity) for arity in positive)
        if error <= policy.max_probability_error:
            return helper_count, exact, error

    helper_count = policy.max_helpers
    error = max(probability_error(helper_count, arity) for arity in positive)
    return helper_count, exact, error


def _shuffle_tickets(values: list[int], *, split_index: int, block_count: int) -> None:
    """Deterministically decorrelate helper identities across random decisions.

    A joint helper window necessarily compresses the full Cartesian product of
    several NX load-time choices. If every exact mapping emitted the same
    repeating ``0..N-1`` sequence, equal-arity decisions inside one window
    would become perfectly correlated. A deterministic Fisher-Yates shuffle
    preserves ticket counts exactly while spreading those correlations across
    the helper pool. No runtime randomness is consumed here.
    """

    if len(values) < 2:
        return
    state = (
        ((split_index + 1) * 0x9E3779B1)
        ^ (block_count * 0x85EBCA6B)
        ^ (len(values) * 0xC2B2AE35)
    ) & 0xFFFFFFFF
    for index in range(len(values) - 1, 0, -1):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        other = state % (index + 1)
        values[index], values[other] = values[other], values[index]


def balanced_ticket_mapping(
    split_index: int,
    block_count: int,
    helper_count: int,
) -> TicketMapping:
    """Assign helper states to block slots as evenly as possible.

    The remainder rotates by split index so approximate projections do not
    systematically favour the lowest-numbered block slots throughout a chart.
    The resulting ticket multiset is then deterministically shuffled per split
    so multiple decisions coalesced into one helper window are not trivially
    locked to the same block index.
    """

    if block_count < 1:
        raise ValueError("block_count must be positive")
    if helper_count < block_count:
        raise ValueError("helper_count must be at least block_count to keep every block reachable")

    quotient, remainder = divmod(helper_count, block_count)
    counts = [quotient] * block_count
    rotation = split_index % block_count
    for offset in range(remainder):
        counts[(rotation + offset) % block_count] += 1

    helper_to_block: list[int] = []
    for block_index, count in enumerate(counts):
        helper_to_block.extend([block_index] * count)
    _shuffle_tickets(helper_to_block, split_index=split_index, block_count=block_count)

    return TicketMapping(
        split_index=split_index,
        block_count=block_count,
        helper_to_block=tuple(helper_to_block),
        tickets_per_block=tuple(counts),
        max_probability_error=probability_error(helper_count, block_count),
    )


def plan_random_pool(
    snapshot: AuthoringSnapshot,
    policy: RandomPoolPolicy = RandomPoolPolicy(),
) -> RandomPoolPlan:
    """Plan a reusable XSanity Wrap helper pool for every NX random start.

    This stage does not serialize SSC and does not deduplicate source blocks.
    It only decides how many uniformly selectable helper states are required
    and which source block each helper represents at each random decision.
    Bank followers consume the mapping of their corresponding store decision
    later in the SSC compiler.
    """

    analysis = analyze_random_structure(snapshot)
    if any(arity <= 0 for arity in analysis.random_arities):
        raise ValueError("cannot plan a random pool for an empty random split")

    helper_count, exact, error = choose_helper_count(analysis.random_arities, policy)
    mappings = tuple(
        balanced_ticket_mapping(
            split_index,
            len(snapshot.splits[split_index].blocks),
            helper_count,
        )
        for split_index in analysis.random_split_indices
    )
    return RandomPoolPlan(
        helper_count=helper_count,
        exact_helper_count=exact,
        max_probability_error=error,
        mappings=mappings,
    )
