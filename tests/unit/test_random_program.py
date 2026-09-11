from __future__ import annotations

from stepnx.authoring.random_program import (
    RandomControlKind,
    compile_random_program,
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
    split_id = 2000 + index
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
    splits = tuple(_split(index, selector, count) for index, (selector, count) in enumerate(spec))
    return AuthoringSnapshot(
        document_stable_id=2,
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


def _active_index(snapshot: AuthoringSnapshot, split_index: int) -> int:
    split = snapshot.splits[split_index]
    active_id = snapshot.active_block_id(split.stable_id)
    return next(index for index, block in enumerate(split.blocks) if block.stable_id == active_id)


def test_1309_helpers_keep_store_and_followers_on_same_twenty_way_choice() -> None:
    snapshot = _snapshot(
        [
            (0x00, 1),
            (0x81, 20),
            (0x41, 20),
            (0x41, 20),
            (0x00, 1),
        ]
    )
    program = compile_random_program(snapshot)

    assert program.helper_count == 20
    assert [control.kind for control in program.controls] == [
        RandomControlKind.WRAP_BEFORE_SPLIT,
        RandomControlKind.RETURN_AFTER_SPLIT,
    ]
    assert program.controls[0].split_index == 1
    assert program.controls[1].split_index == 3

    seen = set()
    for helper in program.helper_snapshots:
        store = _active_index(helper, 1)
        assert _active_index(helper, 2) == store
        assert _active_index(helper, 3) == store
        seen.add(store)
    assert seen == set(range(20))


def test_independent_random_keeps_primitive_per_decision_controls() -> None:
    snapshot = _snapshot([(0x80, 3), (0x00, 1), (0x80, 2)])
    program = compile_random_program(snapshot)
    controls = [(control.kind, control.split_index) for control in program.controls]
    assert controls == [
        (RandomControlKind.WRAP_BEFORE_SPLIT, 0),
        (RandomControlKind.RETURN_AFTER_SPLIT, 0),
        (RandomControlKind.WRAP_BEFORE_SPLIT, 2),
        (RandomControlKind.RETURN_AFTER_SPLIT, 2),
    ]


def test_sequential_banks_reuse_one_helper_identity_at_a_time() -> None:
    snapshot = _snapshot(
        [
            (0x81, 7),
            (0x41, 7),
            (0x82, 9),
            (0x42, 9),
        ]
    )
    program = compile_random_program(snapshot)
    assert program.analysis.max_live_banks == 1

    for helper in program.helper_snapshots:
        assert _active_index(helper, 1) == _active_index(helper, 0)
        assert _active_index(helper, 3) == _active_index(helper, 2)


def test_random_draw_inside_live_bank_materializes_joint_state() -> None:
    snapshot = _snapshot(
        [
            (0x81, 3),
            (0x80, 2),
            (0x41, 3),
        ]
    )
    program = compile_random_program(snapshot)

    assert program.analysis.max_live_banks == 1
    assert program.helper_count == 6
    for helper in program.helper_snapshots:
        assert _active_index(helper, 2) == _active_index(helper, 0)
        assert 0 <= _active_index(helper, 1) < 2


def test_overlapping_named_banks_materialize_both_followers() -> None:
    snapshot = _snapshot(
        [
            (0x81, 2),
            (0x82, 3),
            (0x41, 2),
            (0x42, 3),
        ]
    )
    program = compile_random_program(snapshot)

    assert program.analysis.max_live_banks == 2
    assert program.helper_count == 6
    for helper in program.helper_snapshots:
        assert _active_index(helper, 2) == _active_index(helper, 0)
        assert _active_index(helper, 3) == _active_index(helper, 1)
