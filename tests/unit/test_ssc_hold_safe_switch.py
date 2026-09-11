from __future__ import annotations

from types import SimpleNamespace

from stepnx.exporters.ssc import LINES_PER_MEASURE, SscChart
from stepnx.exporters.ssc_random import SscLabeledChart
from stepnx.exporters.ssc_xsanity import _retime_wraps_around_active_holds


def _notes(rows: list[str], columns: int = 5) -> str:
    blank = "0" * columns
    padded = list(rows)
    if len(padded) % LINES_PER_MEASURE:
        padded.extend([blank] * (LINES_PER_MEASURE - len(padded) % LINES_PER_MEASURE))
    measures = []
    for start in range(0, len(padded), LINES_PER_MEASURE):
        measure = padded[start : start + LINES_PER_MEASURE]
        measures.append("\n".join(measure) + "\n")
    return ",\n".join(measures)


def _rows(notes: str, columns: int = 5) -> list[str]:
    blank = "0" * columns
    result: list[str] = []
    for measure in notes.rstrip("\n").split(",\n"):
        lines = measure.splitlines()
        if lines == [blank]:
            lines = [blank] * LINES_PER_MEASURE
        result.extend(lines)
    return result


def _chart(notes: str, description: str) -> SscChart:
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
        notes=notes,
        noteskin_banks=(),
    )


def test_wrap_inside_active_hold_moves_before_head_and_restores_helper_prefix() -> None:
    blank = "00000"
    base_rows = [blank] * 64
    base_rows[8] = "20000"
    base_rows[16] = "T0000"
    base_rows[24] = "30000"

    helper_rows = [blank] * 64
    # This models the sparse helper before the runtime repair: T was at row 16,
    # so the long-note head at row 8 was discarded while its tail remained.
    helper_rows[24] = "30000"
    helper_rows[40] = "O0000"

    report = SimpleNamespace(
        helper_count=1,
        program=SimpleNamespace(base_snapshot=SimpleNamespace(columns=5)),
        charts=(
            SscLabeledChart(_chart(_notes(base_rows), "BASE"), "NORMAL"),
            SscLabeledChart(_chart(_notes(helper_rows), "HELPER"), "DIVISION", 0),
        ),
    )

    runtime = _retime_wraps_around_active_holds(report)
    repaired_base = _rows(runtime[0].chart.notes)
    repaired_helper = _rows(runtime[1].chart.notes)

    assert "T" in repaired_base[7]
    assert "T" not in repaired_base[16]
    assert repaired_helper[8].startswith("2")
    assert repaired_helper[24].startswith("3")
    assert "O" in repaired_helper[40]


def test_wrap_outside_active_hold_is_left_in_place() -> None:
    blank = "00000"
    base_rows = [blank] * 64
    base_rows[8] = "20000"
    base_rows[24] = "30000"
    base_rows[32] = "T0000"

    helper_rows = [blank] * 64
    helper_rows[40] = "O0000"

    report = SimpleNamespace(
        helper_count=1,
        program=SimpleNamespace(base_snapshot=SimpleNamespace(columns=5)),
        charts=(
            SscLabeledChart(_chart(_notes(base_rows), "BASE"), "NORMAL"),
            SscLabeledChart(_chart(_notes(helper_rows), "HELPER"), "DIVISION", 0),
        ),
    )

    runtime = _retime_wraps_around_active_holds(report)
    repaired_base = _rows(runtime[0].chart.notes)

    assert "T" in repaired_base[32]
