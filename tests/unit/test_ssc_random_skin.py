from __future__ import annotations

from types import SimpleNamespace

from stepnx.exporters import ssc
from stepnx.exporters.ssc import SscChart
from stepnx.exporters.ssc_division import SscDivisionRuntime
from stepnx.exporters.ssc_header_semantics import RANDOM_SKIN_CORPUS_POOL, header_noteskin_context
from stepnx.exporters.ssc_random import SscLabeledChart
from stepnx.exporters.ssc_random_skin import (
    RANDOM_SKIN_RUNTIME_LIST,
    add_random_skin_preloads,
    inject_random_skin_metadata,
    random_skin_projection_context,
    random_skin_requested,
)


def _snapshot(*pairs: tuple[int, int]):
    return SimpleNamespace(
        document_stable_id=123,
        source_name="EF_TEST.NX",
        header_metadata=tuple(
            SimpleNamespace(meta_id=meta_id, value=value)
            for meta_id, value in pairs
        ),
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


def _render_random_note(snapshot, *, player: int, where=(0, 0, 0, 0)):
    state = ssc._ExportState()
    with random_skin_projection_context(snapshot), header_noteskin_context(snapshot):
        rendered = ssc._render_cell(state, bytes((0x43, 3, player, 0)), "0", where)
    return rendered, state


def test_rsk_header_19_and_direct_254_both_request_random_skin() -> None:
    assert random_skin_requested(_snapshot((19, 6)))
    assert random_skin_requested(_snapshot((900, 254)))
    assert random_skin_requested(_snapshot((901, 254), (902, 254)))
    assert not random_skin_requested(_snapshot((19, 0)))
    assert not random_skin_requested(_snapshot((19, 0xFFFFFFFF)))
    assert not random_skin_requested(_snapshot((900, 8), (901, 2)))


def test_direct_900_254_stays_on_bank_zero_and_reports_loader_limitation() -> None:
    cell, state = _render_random_note(_snapshot((900, 254)), player=0)

    assert cell == "1"
    assert len(state.diagnostics) == 1
    diagnostic = state.diagnostics[0]
    assert diagnostic.code == "ssc.random-noteskin-header"
    assert "enabled before chart selection" in diagnostic.message
    assert "bank 0" in diagnostic.message


def test_header19_keeps_unconfigured_slots_random_compatible() -> None:
    snapshot = _snapshot((19, 6))
    slot0, state0 = _render_random_note(snapshot, player=0)
    slot1, state1 = _render_random_note(snapshot, player=1)

    assert slot0 == "1"
    assert slot1 == "1"
    assert state0.diagnostics[0].code == "ssc.random-noteskin-header"
    assert state1.diagnostics[0].code == "ssc.random-noteskin-header"


def test_rsk_preloads_runtime_list_on_every_runtime_step() -> None:
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
    expected = set(RANDOM_SKIN_CORPUS_POOL) | set(RANDOM_SKIN_RUNTIME_LIST) | {"fire", "ice"}
    assert all(set(item.chart.noteskin_banks) == expected for item in result.charts)


def test_randomskin_metadata_emits_list_but_no_ineffective_enable_command() -> None:
    text = "\n".join(
        (
            "#VERSION:0.83;",
            "#TITLE:fixture;",
            "#ATTACKS:;",
            "#NOTEDATA:;",
            "#DESCRIPTION:A;",
            "#DIFFICULTY:Edit;",
            "#PRELOADNOTESKIN:nx,old,music,poker,flower;",
            "#SPEEDS:0=1=1=1,;",
            "#NOTES:",
            "00000",
            ";",
            "#NOTEDATA:;",
            "#DESCRIPTION:B;",
            "#DIFFICULTY:Edit;",
            "#PRELOADNOTESKIN:fire;",
            "#SPEEDS:0=1=1=1,;",
            "#NOTES:",
            "00000",
            ";",
        )
    ) + "\n"

    rendered = inject_random_skin_metadata(text, (True, False))
    assert "MODS=randomskin" not in rendered
    assert "MODS=RSK" not in rendered
    assert "#QUESTMODS:RSK;" not in rendered
    assert rendered.count("#RANDOMSKINLIST:") == 1
    assert "#RANDOMSKINLIST:" + ",".join(RANDOM_SKIN_RUNTIME_LIST) + ";" in rendered

    first_steps = rendered.split("#NOTEDATA:;", 2)[1]
    assert first_steps.index("#RANDOMSKINLIST:") < first_steps.index("#DIFFICULTY:")

    second_steps = rendered.split("#NOTEDATA:;", 2)[2]
    assert "#RANDOMSKINLIST:" not in second_steps
    assert "#ATTACKS:;" in rendered
