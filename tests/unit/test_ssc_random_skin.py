from __future__ import annotations

from types import SimpleNamespace

from stepnx.exporters import ssc
from stepnx.exporters.ssc import SscChart
from stepnx.exporters.ssc_division import SscDivisionRuntime
from stepnx.exporters.ssc_header_semantics import (
    RANDOM_SKIN_CORPUS_POOL,
    XSANITY_BANK_CHARS,
    header_noteskin_context,
)
from stepnx.exporters.ssc_random import SscLabeledChart
from stepnx.exporters.ssc_random_skin import (
    RANDOM_SKIN_RUNTIME_LIST,
    add_random_skin_preloads,
    inject_random_skin_attacks,
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


def _render_random_note(snapshot, *, player: int, where):
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


def test_direct_900_254_materializes_explicit_varying_banks() -> None:
    snapshot = _snapshot((900, 254))
    rendered = []
    banks = set()
    for row in range(24):
        cell, state = _render_random_note(snapshot, player=0, where=(0, 0, row, 0))
        rendered.append(cell)
        assert not state.diagnostics
        assert cell.startswith("{1") and cell.endswith("0}")
        banks.add(cell[2])

    allowed = {XSANITY_BANK_CHARS[name] for name in RANDOM_SKIN_RUNTIME_LIST}
    assert banks <= allowed
    assert len(banks) > 1

    # Export is deterministic: the same source location gets the same explicit bank.
    repeated, _state = _render_random_note(snapshot, player=0, where=(0, 0, 7, 0))
    assert repeated == rendered[7]


def test_header19_materializes_unconfigured_player_slots_including_slot_zero() -> None:
    snapshot = _snapshot((19, 6))
    slot0, state0 = _render_random_note(snapshot, player=0, where=(0, 0, 1, 0))
    slot1, state1 = _render_random_note(snapshot, player=1, where=(0, 0, 2, 0))

    assert slot0.startswith("{1") and slot0.endswith("0}")
    assert slot1.startswith("{1") and slot1.endswith("0}")
    assert not state0.diagnostics
    assert not state1.diagnostics


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


def test_randomskin_runtime_tags_are_retained_as_compatibility_metadata() -> None:
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

    rendered = inject_random_skin_attacks(text, (True, False))
    assert rendered.count("MODS=randomskin") == 1
    assert "LEN=180.000000" in rendered
    assert rendered.count("#RANDOMSKINLIST:") == 1
    assert "#RANDOMSKINLIST:" + ",".join(RANDOM_SKIN_RUNTIME_LIST) + ";" in rendered

    first_steps = rendered.split("#NOTEDATA:;", 2)[1]
    assert first_steps.index("#RANDOMSKINLIST:") < first_steps.index("#DIFFICULTY:")
    assert first_steps.index("MODS=randomskin") < first_steps.index("#NOTES:")

    second_steps = rendered.split("#NOTEDATA:;", 2)[2]
    assert "MODS=randomskin" not in second_steps
    assert "#RANDOMSKINLIST:" not in second_steps
    assert "#ATTACKS:;" in rendered
