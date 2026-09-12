from __future__ import annotations

from types import SimpleNamespace

from stepnx.exporters import ssc
from stepnx.exporters.ssc import SscChart
from stepnx.exporters.ssc_division import SscDivisionRuntime
from stepnx.exporters.ssc_header_semantics import (
    RANDOM_SKIN_CORPUS_POOL,
    header_noteskin_context,
)
from stepnx.exporters.ssc_random import SscLabeledChart
from stepnx.exporters.ssc_random_skin import (
    add_random_skin_preloads,
    inject_random_skin_attacks,
    random_skin_projection_context,
    random_skin_requested,
)


def _snapshot(*pairs: tuple[int, int]):
    return SimpleNamespace(
        header_metadata=tuple(
            SimpleNamespace(meta_id=meta_id, value=value)
            for meta_id, value in pairs
        )
    )


def _chart(*banks: str) -> SscChart:
    return SscChart(
        steps_type="pump-single",
        difficulty="Edit",
        description="fixture",
        meter=1,
        credit="",
        offset=0.0,
        bpms="0=120,",
        stops="",
        delays="",
        warps="",
        scrolls="0=8,",
        speeds="",
        notes="00000\n",
        noteskin_banks=tuple(banks),
    )


def test_rsk_header_19_and_direct_254_both_request_random_skin() -> None:
    assert random_skin_requested(_snapshot((19, 6)))
    assert random_skin_requested(_snapshot((900, 254)))
    assert random_skin_requested(_snapshot((901, 254), (902, 254)))
    assert not random_skin_requested(_snapshot((19, 0)))
    assert not random_skin_requested(_snapshot((19, 0xFFFFFFFF)))
    assert not random_skin_requested(_snapshot((900, 8), (901, 2)))


def test_direct_254_no_longer_reports_loss_inside_runtime_projection() -> None:
    snapshot = _snapshot((901, 254))
    state = ssc._ExportState()

    with random_skin_projection_context(snapshot), header_noteskin_context(snapshot):
        # Header slot 901 is Random. The note intentionally keeps bank 0 because
        # the real display behavior is supplied by the chart-level randomskin
        # modifier in the final renderer.
        assert ssc._render_cell(state, bytes((0x43, 3, 1, 0)), "0", (0, 0, 0, 0)) == "1"

    assert not state.diagnostics


def test_rsk_preloads_known_random_skin_family_on_every_runtime_step() -> None:
    runtime = SscDivisionRuntime(
        charts=(
            SscLabeledChart(_chart("fire"), "NORMAL"),
            SscLabeledChart(_chart("ice"), "DIVISION", 0),
        ),
        chart_names=("BASE", "HELPER"),
        division_tables=((), ()),
        route_count=1,
    )

    result = add_random_skin_preloads(runtime, _snapshot((19, 6)))
    expected = set(RANDOM_SKIN_CORPUS_POOL) | {"fire", "ice"}
    assert all(set(item.chart.noteskin_banks) == expected for item in result.charts)


def test_randomskin_attack_is_per_steps_and_inserted_before_notes() -> None:
    text = "\n".join(
        (
            "#TITLE:fixture;",
            "#ATTACKS:;",
            "#NOTEDATA:;",
            "#DESCRIPTION:A;",
            "#SPEEDS:0=1=1=1,;",
            "#NOTES:",
            "00000",
            ";",
            "#NOTEDATA:;",
            "#DESCRIPTION:B;",
            "#SPEEDS:0=1=1=1,;",
            "#NOTES:",
            "00000",
            ";",
        )
    ) + "\n"

    rendered = inject_random_skin_attacks(text, (True, False))
    assert rendered.count("MODS=randomskin") == 1
    first_steps = rendered.split("#NOTEDATA:;", 2)[1]
    assert first_steps.index("MODS=randomskin") < first_steps.index("#NOTES:")
    second_steps = rendered.split("#NOTEDATA:;", 2)[2]
    assert "MODS=randomskin" not in second_steps
    assert "#ATTACKS:;" in rendered
