from __future__ import annotations

from types import SimpleNamespace

from stepnx.exporters.ssc import SscChart
from stepnx.exporters.ssc_division import (
    SscDivisionCondition,
    SscDivisionDecision,
    SscDivisionRuntime,
)
from stepnx.exporters.ssc_random import SscLabeledChart
from stepnx.exporters.ssc_xsanity import _dense_rows, _measure_rows
from stepnx.exporters.ssc_xsanity_lifetime import _hide_runtime_routes


def _chart(description: str, note_row: int | None = None) -> SscChart:
    rows = ["00000"] * 64
    if note_row is not None:
        rows[note_row] = "10000"
    return SscChart(
        steps_type="pump-single",
        difficulty="Edit",
        description=description,
        meter=5,
        credit="",
        offset=0.0,
        bpms="0=120,",
        stops="",
        delays="",
        warps="",
        scrolls="0=1,",
        speeds="0=1=1=1,",
        notes=_measure_rows(rows, 5),
        noteskin_banks=(),
    )


def _decision() -> SscDivisionDecision:
    return SscDivisionDecision(
        split_index=10,
        timestamp_seconds=6.0,
        conditions=(
            None,
            SscDivisionCondition(1, 999, "W"),
            SscDivisionCondition(1, 999, "G"),
            SscDivisionCondition(1, 999, "WG"),
        ),
    )


def test_pure_division_keeps_only_base_normal() -> None:
    charts = (
        SscLabeledChart(_chart("BASE"), "NORMAL"),
        SscLabeledChart(_chart("W"), "NORMAL"),
        SscLabeledChart(_chart("G"), "NORMAL"),
        SscLabeledChart(_chart("WG"), "NORMAL"),
    )
    bundle = SscDivisionRuntime(
        charts=charts,
        chart_names=("BASE", "W", "G", "WG"),
        division_tables=((), (), (), ()),
        route_count=4,
    )
    report = SimpleNamespace(helper_count=0)

    hidden = _hide_runtime_routes(report, bundle)

    assert tuple(item.label_type for item in hidden.charts) == (
        "NORMAL",
        "DIVISION",
        "DIVISION",
        "DIVISION",
    )


def test_tail_division_reuses_dead_random_helpers_instead_of_visible_routes(monkeypatch) -> None:
    import stepnx.exporters.ssc_xsanity_lifetime as lifetime

    helpers = tuple(
        SscLabeledChart(_chart(f"R{index + 1}", note_row=4 + index), "DIVISION", index)
        for index in range(5)
    )
    routes = tuple(
        SscLabeledChart(_chart(name, note_row=40 + index), "NORMAL")
        for index, name in enumerate(("W", "G", "WG"))
    )
    charts = (SscLabeledChart(_chart("BASE"), "NORMAL"),) + helpers + routes
    names = (
        "EF662_BASE",
        "EF662_RANDOM_001",
        "EF662_RANDOM_002",
        "EF662_RANDOM_003",
        "EF662_RANDOM_004",
        "EF662_RANDOM_005",
        "EF662_DIVISION_02",
        "EF662_DIVISION_03",
        "EF662_DIVISION_04",
    )
    bundle = SscDivisionRuntime(
        charts=charts,
        chart_names=names,
        division_tables=tuple(() for _ in charts),
        route_count=4,
    )
    report = SimpleNamespace(
        helper_count=5,
        program=SimpleNamespace(base_snapshot=SimpleNamespace(columns=5)),
    )
    monkeypatch.setattr(lifetime, "compile_division_decisions", lambda _report: (_decision(),))

    hidden = _hide_runtime_routes(report, bundle)

    # No extra route Steps remain. Loader sees one NORMAL chart; T still sees
    # exactly the original five DIVISION tickets.
    assert len(hidden.charts) == 6
    assert sum(item.label_type == "NORMAL" for item in hidden.charts) == 1
    assert sum(item.label_type == "DIVISION" for item in hidden.charts) == 5
    assert hidden.chart_names == names[:6]
    assert hidden.division_tables[0] == (
        "0=0=EF662_BASE=6.00000=WG",
        "1=999=EF662_RANDOM_001=6.00000=W",
        "1=999=EF662_RANDOM_002=6.00000=G",
        "1=999=EF662_RANDOM_003=6.00000=WG",
    )

    rows1 = _dense_rows(hidden.charts[1].chart.notes, 5)
    rows2 = _dense_rows(hidden.charts[2].chart.notes, 5)
    rows3 = _dense_rows(hidden.charts[3].chart.notes, 5)
    assert rows1[4] == "10000" and rows1[40] == "10000"
    assert rows2[5] == "10000" and rows2[41] == "10000"
    assert rows3[6] == "10000" and rows3[42] == "10000"
