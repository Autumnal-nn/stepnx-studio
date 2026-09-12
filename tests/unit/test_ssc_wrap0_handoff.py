from __future__ import annotations

from types import SimpleNamespace

from stepnx.exporters.ssc import LINES_PER_MEASURE, SscChart
from stepnx.exporters.ssc_random import SscLabeledChart
from stepnx.exporters.ssc_xsanity_segmented import materialize_segmented_random


def _notes(rows: list[str], columns: int = 5) -> str:
    blank = "0" * columns
    padded = list(rows)
    if len(padded) % LINES_PER_MEASURE:
        padded.extend([blank] * (LINES_PER_MEASURE - len(padded) % LINES_PER_MEASURE))
    return ",\n".join(
        "\n".join(padded[start : start + LINES_PER_MEASURE]) + "\n"
        for start in range(0, len(padded), LINES_PER_MEASURE)
    )


def _rows(notes: str, columns: int = 5) -> list[str]:
    blank = "0" * columns
    result: list[str] = []
    for measure in notes.rstrip("\n").split(",\n"):
        lines = measure.splitlines()
        if lines == [blank]:
            lines = [blank] * LINES_PER_MEASURE
        result.extend(lines)
    return result


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


def _report(base_rows: list[str], helper_rows: tuple[list[str], ...]):
    charts = [SscLabeledChart(_chart(base_rows, "BASE"), "NORMAL")]
    charts.extend(
        SscLabeledChart(_chart(rows, f"HELPER-{index}"), "DIVISION", index - 1)
        for index, rows in enumerate(helper_rows, 1)
    )
    return SimpleNamespace(
        helper_count=len(helper_rows),
        program=SimpleNamespace(base_snapshot=SimpleNamespace(columns=5)),
        charts=tuple(charts),
    )


def _two_window_fixture(*, second_wrap: int = 100, with_hold: bool = False):
    blank = "00000"
    base = [blank] * 160
    base[8] = "10000"
    base[20] = "T0000"
    base[30] = "10000"
    base[second_wrap] = "T0000"
    base[115] = "10000"
    if with_hold:
        base[45] = "20000"
        base[90] = "30000"

    helpers: list[list[str]] = []
    for first, second in (("01000", "00100"), ("00010", "00001")):
        rows = [blank] * 160
        rows[30] = first
        rows[40] = "O0000"
        rows[115] = second
        rows[130] = "O0000"
        helpers.append(rows)
    return _report(base, tuple(helpers))


def test_wrap0_handoff_adds_fresh_draw_only_in_long_dead_air() -> None:
    runtime = materialize_segmented_random(_two_window_fixture())
    base = _rows(runtime[0].chart.notes)
    helpers = [_rows(item.chart.notes) for item in runtime[1:]]

    t_rows = [index for index, row in enumerate(base) if "T" in row]
    assert t_rows == [0, 98]

    for rows in helpers:
        o_rows = [index for index, row in enumerate(rows) if "O" in row]
        assert o_rows == [41]

    # Full helpers retain both random groups. The new O0/T pair changes only
    # which helper supplies the second group at runtime.
    assert helpers[0][30] == "01000"
    assert helpers[0][115] == "00100"
    assert helpers[1][30] == "00010"
    assert helpers[1][115] == "00001"


def test_wrap0_handoff_is_skipped_when_gap_is_too_short() -> None:
    runtime = materialize_segmented_random(_two_window_fixture(second_wrap=48))
    base = _rows(runtime[0].chart.notes)
    helpers = [_rows(item.chart.notes) for item in runtime[1:]]

    assert [index for index, row in enumerate(base) if "T" in row] == [0]
    assert all(all("O" not in row for row in rows) for rows in helpers)


def test_wrap0_handoff_is_skipped_across_active_hold() -> None:
    runtime = materialize_segmented_random(_two_window_fixture(with_hold=True))
    base = _rows(runtime[0].chart.notes)
    helpers = [_rows(item.chart.notes) for item in runtime[1:]]

    assert [index for index, row in enumerate(base) if "T" in row] == [0]
    assert all(all("O" not in row for row in rows) for rows in helpers)
