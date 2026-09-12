from __future__ import annotations

from types import SimpleNamespace

from stepnx.authoring.snapshot import AuthoringSnapshot, BlockSnapshot, SplitSnapshot
from stepnx.exporters.ssc_division import SscDivisionRuntime
from stepnx.exporters.ssc_runtime_compile import resolve_ordered_unconditional_snapshot
from stepnx.exporters.ssc_xsanity_lifetime import (
    _inject_division_tables_runtime_order,
    _normalize_single_decision_bundle,
    _single_decision_entries,
)


def _block(split_id: int, stable_id: int, index: int, *, divisions=()) -> BlockSnapshot:
    return BlockSnapshot(
        stable_id=stable_id,
        split_id=split_id,
        index=index,
        start_time=0.0,
        bpm=120.0,
        scroll=1.0,
        offset_or_delay=0.0,
        speed_or_freeze=1.0,
        beat_split=8,
        beat_measure=4,
        smooth_speed=0,
        raw_flag=0,
        rows=(),
        divisions=tuple(divisions),
    )


def _snapshot(*, raw_select: int = 0x00, conditioned: bool = False) -> AuthoringSnapshot:
    split_id = 100
    blocks = tuple(
        _block(
            split_id,
            1000 + index,
            index,
            divisions=(SimpleNamespace(meta_id=5, value=1),) if conditioned and index == 1 else (),
        )
        for index in range(4)
    )
    split = SplitSnapshot(
        stable_id=split_id,
        index=0,
        raw_select=raw_select,
        raw_brain=0,
        raw_padding=0,
        metadata=(),
        blocks=blocks,
    )
    return AuthoringSnapshot(
        document_stable_id=1,
        source_name="EF334.NX",
        profile="nxa-native",
        role="chart",
        start_column=0,
        columns=5,
        effective_lightmap=False,
        header_metadata=(),
        splits=(split,),
        active_blocks=((split_id, blocks[0].stable_id),),
        diagnostics=(),
    )


def test_ordered_unconditional_multiblock_uses_last_runtime_candidate() -> None:
    snapshot = resolve_ordered_unconditional_snapshot(_snapshot())

    assert len(snapshot.splits[0].blocks) == 1
    assert snapshot.splits[0].blocks[0].index == 3
    assert snapshot.active_block(snapshot.splits[0].stable_id).index == 3


def test_ordered_split_with_real_division_metadata_is_not_collapsed() -> None:
    source = _snapshot(conditioned=True)
    snapshot = resolve_ordered_unconditional_snapshot(source)

    assert snapshot is source
    assert len(snapshot.splits[0].blocks) == 4


def test_single_division_table_omits_implicit_fallback_and_matches_official_order() -> None:
    entries = (
        "0=0=STEP1=6.00000=WG",
        "1=999=STEP2=6.00000=W",
        "1=999=STEP3=6.00000=G",
        "1=999=STEP4=6.00000=WG",
    )

    assert _single_decision_entries(entries) == (
        "1=999=STEP4=6.00000=WG",
        "1=999=STEP2=6.00000=W",
        "1=999=STEP3=6.00000=G",
    )


def test_nonrandom_single_division_table_belongs_only_to_base(monkeypatch) -> None:
    import stepnx.exporters.ssc_xsanity_lifetime as lifetime

    table = (
        "0=0=STEP1=6.00000=WG",
        "1=999=STEP2=6.00000=W",
        "1=999=STEP3=6.00000=G",
        "1=999=STEP4=6.00000=WG",
    )
    bundle = SscDivisionRuntime(
        charts=(),
        chart_names=("STEP1", "STEP2", "STEP3", "STEP4"),
        division_tables=(table, table, table, table),
        route_count=4,
    )
    report = SimpleNamespace(helper_count=0)
    monkeypatch.setattr(lifetime, "compile_division_decisions", lambda _report: (object(),))

    normalized = _normalize_single_decision_bundle(report, bundle)

    assert normalized.division_tables[0] == (
        "1=999=STEP4=6.00000=WG",
        "1=999=STEP2=6.00000=W",
        "1=999=STEP3=6.00000=G",
    )
    assert normalized.division_tables[1:] == ((), (), ())


def test_division_metadata_is_inserted_after_speeds_not_after_tickcounts() -> None:
    text = "\n".join(
        (
            "#NOTEDATA:;",
            "#DESCRIPTION:S;",
            "#TICKCOUNTS:0.000000=8;",
            "#SCROLLS:0=1,;",
            "#SPEEDS:0=1=1=1,;",
            "#NOTES:",
            "00000",
            ";",
        )
    ) + "\n"
    rendered = _inject_division_tables_runtime_order(
        text,
        (("1=999=STEP2=6.00000=W",),),
    )

    assert rendered.index("#TICKCOUNTS:") < rendered.index("#SPEEDS:")
    assert rendered.index("#SPEEDS:") < rendered.index("#DIVISION:")
    assert rendered.index("#DIVISION:") < rendered.index("#NOTES:")


def test_division_destination_gets_empty_runtime_tags_at_same_position() -> None:
    text = "\n".join(
        (
            "#NOTEDATA:;",
            "#DESCRIPTION:STEP1;",
            "#SPEEDS:0=1=1=1,;",
            "#NOTES:",
            "00000",
            ";",
            "#NOTEDATA:;",
            "#DESCRIPTION:STEP2;",
            "#SPEEDS:0=1=1=1,;",
            "#NOTES:",
            "00000",
            ";",
        )
    ) + "\n"
    rendered = _inject_division_tables_runtime_order(
        text,
        (("1=999=STEP2=6.00000=W",), ()),
    )

    assert rendered.count("#DIVISION:") == 2
    assert "#DIVISION:;\n#SPECIALDIVISION:;" in rendered
