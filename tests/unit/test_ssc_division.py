from __future__ import annotations

from types import SimpleNamespace

import pytest

from stepnx.exporters.ssc import SscExportError
from stepnx.exporters.ssc_division import (
    _table,
    compile_division_decisions,
    inject_division_tables,
)


def _meta(meta_id: int, minimum: int, maximum: int) -> SimpleNamespace:
    return SimpleNamespace(meta_id=meta_id, value=(maximum << 16) | minimum)


def _block(index: int, divisions=()) -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        divisions=tuple(divisions),
        row_count=0,
        rows=(),
        start_time=268_539.0,
        bpm=140.0,
        scroll=1.0,
        offset_or_delay=0.0,
        speed_or_freeze=1.0,
        beat_split=8,
        beat_measure=4,
        smooth_speed=0,
        raw_flag=0,
    )


def _report(blocks) -> SimpleNamespace:
    split = SimpleNamespace(index=219, blocks=tuple(blocks))
    snapshot = SimpleNamespace(splits=(split,))
    analysis = SimpleNamespace(random_split_indices=(), bank_episodes=())
    return SimpleNamespace(
        program=SimpleNamespace(base_snapshot=snapshot, analysis=analysis)
    )


def test_ef662_style_g_w_wg_compiles_to_native_division_table() -> None:
    report = _report(
        (
            _block(0),
            _block(1, (_meta(6, 1, 1),)),
            _block(2, (_meta(5, 1, 1),)),
            _block(3, (_meta(5, 1, 1), _meta(6, 1, 1))),
        )
    )

    decisions = compile_division_decisions(report)
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.timestamp_seconds == pytest.approx(268.539)
    assert decision.conditions[0] is None
    assert (decision.conditions[1].minimum, decision.conditions[1].maximum, decision.conditions[1].operator) == (1, 1, "W")
    assert (decision.conditions[2].minimum, decision.conditions[2].maximum, decision.conditions[2].operator) == (1, 1, "G")
    assert (decision.conditions[3].minimum, decision.conditions[3].maximum, decision.conditions[3].operator) == (1, 1, "WG")

    assert _table(decisions, ("STEP1", "STEP2", "STEP3", "STEP4")) == (
        "0=0=STEP1=268.53900=WG",
        "1=1=STEP2=268.53900=W",
        "1=1=STEP3=268.53900=G",
        "1=1=STEP4=268.53900=WG",
    )


def test_asymmetric_g_w_range_is_rejected_instead_of_inventing_wg_rule() -> None:
    report = _report(
        (
            _block(0),
            _block(1, (_meta(5, 1, 1), _meta(6, 1, 3))),
        )
    )

    with pytest.raises(SscExportError, match="asymmetric"):
        compile_division_decisions(report)


def test_unknown_division_family_is_rejected_explicitly() -> None:
    report = _report((_block(0), _block(1, (_meta(0, 1, 1),))))

    with pytest.raises(SscExportError, match="supports only G/W"):
        compile_division_decisions(report)


def test_division_metadata_is_inserted_per_notedata_section() -> None:
    text = "\n".join(
        (
            "#VERSION:0.83;",
            "#NOTEDATA:;",
            "#DESCRIPTION:BASE;",
            "#TICKCOUNTS:0.000000=8;",
            "#NOTES:",
            "00000",
            ";",
            "#NOTEDATA:;",
            "#DESCRIPTION:ROUTE;",
            "#TICKCOUNTS:0.000000=8;",
            "#NOTES:",
            "00000",
            ";",
            "",
        )
    )
    table = (
        "0=0=STEP1=12.00000=WG",
        "1=1=STEP2=12.00000=W",
    )

    rendered = inject_division_tables(text, (table, table))
    assert rendered.count("#DIVISION:") == 2
    assert rendered.count("#SPECIALDIVISION:;") == 2
    assert "#DIVISION:0=0=STEP1=12.00000=WG\n,1=1=STEP2=12.00000=W\n;" in rendered
