from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from stepnx.exporters.ssc import LINES_PER_MEASURE, SscChart
from stepnx.exporters.ssc_division import (
    SscDivisionCondition,
    SscDivisionDecision,
    SscDivisionRuntime,
)
from stepnx.exporters.ssc_division_lifetime import (
    materialize_division_routes_lifetime_aware,
)
from stepnx.exporters.ssc_random import SscLabeledChart
from stepnx.exporters.ssc_xsanity import _dense_rows


def _notes(rows: list[str], columns: int = 5) -> str:
    blank = "0" * columns
    padded = list(rows)
    if len(padded) % LINES_PER_MEASURE:
        padded.extend([blank] * (LINES_PER_MEASURE - len(padded) % LINES_PER_MEASURE))
    return ",\n".join(
        "\n".join(padded[start : start + LINES_PER_MEASURE]) + "\n"
        for start in range(0, len(padded), LINES_PER_MEASURE)
    )


def _chart(rows: list[str], description: str) -> SscChart:
    return SscChart(
        steps_type="pump-single",
        difficulty="Edit",
        description=description,
        meter=1,
        credit="",
        offset=0.0,
        bpms="0=120,",
        stops="",
        delays="",
        warps="",
        scrolls="0=1,",
        speeds="",
        notes=_notes(rows),
        noteskin_banks=(),
    )


def _fixture(helper_count: int = 5):
    blank = "00000"
    base_rows = [blank] * 160
    base_rows[0] = "T0000"
    base_rows[135] = "10000"
    runtime = [SscLabeledChart(_chart(base_rows, "BASE"), "NORMAL")]

    planning = [SscLabeledChart(_chart(base_rows, "BASE"), "NORMAL")]
    helper_snapshots = []
    for index in range(helper_count):
        runtime_rows = [blank] * 160
        runtime_rows[20] = "01000"
        runtime.append(
            SscLabeledChart(
                _chart(runtime_rows, f"R{index + 1}"),
                "DIVISION",
                index,
            )
        )

        planning_rows = [blank] * 160
        planning_rows[40] = "O0000"
        planning.append(
            SscLabeledChart(
                _chart(planning_rows, f"PLAN{index + 1}"),
                "DIVISION",
                index,
            )
        )
        helper_snapshots.append(SimpleNamespace(columns=5))

    report = SimpleNamespace(
        helper_count=helper_count,
        charts=tuple(planning),
        program=SimpleNamespace(
            base_snapshot=SimpleNamespace(columns=5),
            helper_snapshots=tuple(helper_snapshots),
        ),
    )
    return report, tuple(runtime)


def _decision() -> SscDivisionDecision:
    return SscDivisionDecision(
        split_index=7,
        timestamp_seconds=12.0,
        conditions=(
            None,
            SscDivisionCondition(1, 1, "W"),
            SscDivisionCondition(1, 1, "G"),
            SscDivisionCondition(1, 1, "WG"),
        ),
    )


def test_tail_division_reuses_dead_random_helpers_without_cartesian_product(monkeypatch) -> None:
    import stepnx.exporters.ssc_division_lifetime as lifetime

    report, runtime = _fixture(helper_count=5)
    monkeypatch.setattr(lifetime, "compile_division_decisions", lambda _report: (_decision(),))
    monkeypatch.setattr(lifetime, "_split_bounds", lambda _snapshot: {7: (120, 160)})
    monkeypatch.setattr(
        lifetime,
        "_route_variant",
        lambda source, *_args, description, helper_index, **_kwargs: replace(
            source,
            chart=replace(source.chart, description=description),
            helper_index=helper_index,
        ),
    )
    monkeypatch.setattr(
        lifetime,
        "materialize_division_routes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fallback used")),
    )

    bundle = materialize_division_routes_lifetime_aware(report, runtime, prefix="EF662")

    # Base + the original five random tickets. No 5x4 route lattice is created.
    assert len(bundle.charts) == 6
    assert bundle.chart_names == (
        "EF662_BASE",
        "EF662_RANDOM_001",
        "EF662_RANDOM_002",
        "EF662_RANDOM_003",
        "EF662_RANDOM_004",
        "EF662_RANDOM_005",
    )
    assert bundle.division_tables[0] == (
        "0=0=EF662_BASE=12.00000=WG",
        "1=1=EF662_RANDOM_001=12.00000=W",
        "1=1=EF662_RANDOM_002=12.00000=G",
        "1=1=EF662_RANDOM_003=12.00000=WG",
    )
    assert all(not table for table in bundle.division_tables[1:])

    helper_rows = [_dense_rows(item.chart.notes, 5) for item in bundle.charts[1:]]
    assert all("O" in rows[40] for rows in helper_rows)

    # Three tickets are recycled as late Division carriers and therefore keep a
    # sparse late suffix. The remaining dead tickets end shortly after O0.
    assert all(len(rows) == 160 for rows in helper_rows[:3])
    assert all(len(rows) < 160 for rows in helper_rows[3:])
    assert all(len(rows) >= 40 + 16 + 1 for rows in helper_rows[3:])


def test_division_too_close_to_final_random_return_uses_conservative_fallback(monkeypatch) -> None:
    import stepnx.exporters.ssc_division_lifetime as lifetime

    report, runtime = _fixture(helper_count=5)
    monkeypatch.setattr(lifetime, "compile_division_decisions", lambda _report: (_decision(),))
    monkeypatch.setattr(lifetime, "_split_bounds", lambda _snapshot: {7: (48, 80)})
    sentinel = SscDivisionRuntime(runtime, tuple(f"C{index}" for index in range(len(runtime))), tuple(() for _ in runtime), 99)
    monkeypatch.setattr(
        lifetime,
        "materialize_division_routes",
        lambda *_args, **_kwargs: sentinel,
    )

    assert materialize_division_routes_lifetime_aware(report, runtime) is sentinel
