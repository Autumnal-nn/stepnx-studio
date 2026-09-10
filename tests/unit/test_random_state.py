from __future__ import annotations

from stepnx.authoring.random_state import (
    RandomPoolPolicy,
    analyze_random_structure,
    balanced_ticket_mapping,
    choose_helper_count,
    decode_split_selector,
    exact_helper_count,
    plan_random_pool,
)
from stepnx.authoring.snapshot import AuthoringSnapshot, BlockSnapshot, SplitSnapshot


def _block(split_id: int, stable_id: int, index: int) -> BlockSnapshot:
    return BlockSnapshot(
        stable_id=stable_id,
        split_id=split_id,
        index=index,
        start_time=float(index),
        bpm=120.0,
        scroll=1.0,
        offset_or_delay=0.0,
        speed_or_freeze=1.0,
        beat_split=4,
        beat_measure=4,
        smooth_speed=0,
        raw_flag=0,
        rows=(),
        divisions=(),
    )


def _split(index: int, selector: int, block_count: int) -> SplitSnapshot:
    split_id = 1000 + index
    return SplitSnapshot(
        stable_id=split_id,
        index=index,
        raw_select=selector,
        raw_brain=0,
        raw_padding=0,
        metadata=(),
        blocks=tuple(_block(split_id, split_id * 100 + block, block) for block in range(block_count)),
    )


def _snapshot(spec: list[tuple[int, int]]) -> AuthoringSnapshot:
    splits = tuple(_split(index, selector, blocks) for index, (selector, blocks) in enumerate(spec))
    return AuthoringSnapshot(
        document_stable_id=1,
        source_name="fixture.NX",
        profile="nxa-native",
        role="chart",
        start_column=0,
        columns=10,
        effective_lightmap=False,
        header_metadata=(),
        splits=splits,
        active_blocks=tuple((split.stable_id, split.blocks[0].stable_id) for split in splits if split.blocks),
        diagnostics=(),
    )


def test_selector_bits_are_independent() -> None:
    plain = decode_split_selector(0x80)
    assert plain.random_start
    assert plain.bank_id == 0
    assert not plain.follow_bank
    assert not plain.recalc_conditions

    store = decode_split_selector(0xA1)
    assert store.random_start
    assert store.stores_bank
    assert store.bank_id == 1
    assert store.recalc_conditions

    follow = decode_split_selector(0x41)
    assert follow.follows_named_bank
    assert follow.bank_id == 1
    assert not follow.random_start


def test_1309_bank_episode_preserves_twenty_block_probability_mass() -> None:
    snapshot = _snapshot(
        [
            (0x00, 1),
            (0x00, 1),
            (0x00, 1),
            (0x81, 20),
            (0x41, 20),
            (0x41, 20),
            (0x00, 1),
        ]
    )

    analysis = analyze_random_structure(snapshot)
    assert analysis.random_split_indices == (3,)
    assert analysis.random_arities == (20,)
    assert analysis.max_live_banks == 1
    assert analysis.diagnostics == ()

    episode = analysis.bank_episodes[0]
    assert episode.bank_id == 1
    assert episode.store_split_index == 3
    assert episode.follower_split_indices == (4, 5)
    assert episode.last_use_split_index == 5
    assert episode.block_count == 20

    plan = plan_random_pool(snapshot)
    assert plan.helper_count == 20
    assert plan.exact_helper_count == 20
    assert plan.max_probability_error == 0.0
    assert plan.mappings[0].tickets_per_block == (1,) * 20


def test_ef662_arities_choose_sixty_helpers_at_default_quality() -> None:
    helper_count, exact, error = choose_helper_count((7, 8, 9, 10))
    assert exact == 2520
    assert helper_count == 60
    assert error <= 0.0125


def test_exact_helper_count_is_lcm_not_product() -> None:
    assert exact_helper_count((2, 3, 4, 5)) == 60
    assert exact_helper_count((7, 8, 9, 10)) == 2520
    assert exact_helper_count(()) == 0


def test_balanced_mapping_keeps_every_block_reachable_and_rotates_remainder() -> None:
    first = balanced_ticket_mapping(0, 3, 10)
    second = balanced_ticket_mapping(1, 3, 10)

    assert first.tickets_per_block == (4, 3, 3)
    assert second.tickets_per_block == (3, 4, 3)
    assert set(first.helper_to_block) == {0, 1, 2}
    assert len(first.helper_to_block) == 10


def test_sequential_banks_do_not_create_false_cartesian_overlap() -> None:
    snapshot = _snapshot(
        [
            (0x81, 7),
            (0x41, 7),
            (0x82, 9),
            (0x42, 9),
            (0x83, 10),
            (0x43, 10),
        ]
    )
    analysis = analyze_random_structure(snapshot)
    assert analysis.max_live_banks == 1
    assert [episode.bank_id for episode in analysis.bank_episodes] == [1, 2, 3]


def test_overlapping_banks_are_detected() -> None:
    snapshot = _snapshot(
        [
            (0x81, 2),
            (0x82, 3),
            (0x41, 2),
            (0x42, 3),
        ]
    )
    analysis = analyze_random_structure(snapshot)
    assert analysis.max_live_banks == 2


def test_bank_follower_arity_mismatch_is_diagnostic() -> None:
    snapshot = _snapshot([(0x81, 20), (0x41, 19)])
    analysis = analyze_random_structure(snapshot)
    assert [diagnostic.code for diagnostic in analysis.diagnostics] == [
        "random.bank-arity-mismatch"
    ]


def test_orphan_named_follower_is_diagnostic() -> None:
    snapshot = _snapshot([(0x41, 4)])
    analysis = analyze_random_structure(snapshot)
    assert [diagnostic.code for diagnostic in analysis.diagnostics] == [
        "random.orphan-bank-follow"
    ]


def test_policy_ceiling_falls_back_to_best_available_pool() -> None:
    helper_count, exact, error = choose_helper_count(
        (7, 8, 9, 10),
        RandomPoolPolicy(max_probability_error=0.001, max_helpers=64),
    )
    assert helper_count == 64
    assert exact == 2520
    assert error > 0.001
