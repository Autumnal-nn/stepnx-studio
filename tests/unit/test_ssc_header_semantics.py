from __future__ import annotations

from types import SimpleNamespace

from stepnx.exporters import ssc
from stepnx.exporters.ssc import SscChart
from stepnx.exporters.ssc_header_semantics import (
    NX20_NOTESKIN_NAMES,
    apply_header_preloads,
    header_noteskin_context,
    header_preload_noteskins,
    player_slot_skin_values,
    resolved_meter,
    unify_runtime_preloads,
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


def test_fiesta2_header_skin_enumeration_matches_sanity_aliases() -> None:
    assert NX20_NOTESKIN_NAMES[1] == "flower"
    assert NX20_NOTESKIN_NAMES[2] == "old"
    assert NX20_NOTESKIN_NAMES[3] == "easy"
    assert NX20_NOTESKIN_NAMES[13] == "fire"
    assert NX20_NOTESKIN_NAMES[14] == "ice"
    assert NX20_NOTESKIN_NAMES[16] == "perfor1"
    assert NX20_NOTESKIN_NAMES[17] == "perfor2"
    assert NX20_NOTESKIN_NAMES[18] == "perfor3"
    assert NX20_NOTESKIN_NAMES[27] == "soccer"
    assert NX20_NOTESKIN_NAMES[30] == "fiesta"


def test_ef1225_header_family_preloads_every_declared_skin() -> None:
    snapshot = _snapshot((900, 8), (901, 2), (902, 13), (903, 14), (904, 3))
    assert set(header_preload_noteskins(snapshot)) == {
        "nx",
        "old",
        "fire",
        "ice",
        "easy",
    }


def test_player_bank_uses_901_905_but_special_bank_keeps_legacy_semantics() -> None:
    snapshot = _snapshot((900, 8), (901, 2), (902, 13), (903, 14), (904, 3))
    state = ssc._ExportState()

    with header_noteskin_context(snapshot):
        assert ssc._render_cell(state, bytes((0x43, 3, 2, 0)), "0", (0, 0, 0, 0)) == "{1k0}"
        assert ssc._render_cell(state, bytes((0x43, 3, 4, 0)), "0", (0, 0, 1, 0)) == "{1a0}"
        assert ssc._render_cell(state, bytes((0x47, 3, 0, 4)), "0", (0, 0, 2, 0)) == "{440}"

    assert {"fire", "easy", "soccer"}.issubset(state.banks)


def test_header19_fills_only_missing_player_slots_with_random_sentinel() -> None:
    configured = player_slot_skin_values(_snapshot((19, 6), (902, 13)))
    assert configured == {1: 254, 2: 13, 3: 254, 4: 254, 5: 254}


def test_header19_random_slot_stays_unbanked_for_runtime_randomskin() -> None:
    snapshot = _snapshot((19, 6))
    state = ssc._ExportState()

    with header_noteskin_context(snapshot):
        rendered = ssc._render_cell(state, bytes((0x43, 3, 1, 0)), "0", (0, 0, 0, 0))

    assert rendered == "1"
    assert state.diagnostics[0].code == "ssc.random-noteskin-header"


def test_meter_prefers_1001_then_falls_back_to_mission_1101() -> None:
    assert resolved_meter(_snapshot((1101, 5))) == 5
    assert resolved_meter(_snapshot((1001, 18), (1101, 5))) == 18
    assert resolved_meter(_snapshot((1001, 18), (1101, 5)), 22) == 22


def test_header_preloads_are_added_without_dropping_existing_special_banks() -> None:
    snapshot = _snapshot((901, 2), (902, 13))
    chart = _chart("soccer")
    result = apply_header_preloads(chart, snapshot)
    assert set(result.noteskin_banks) == {"soccer", "old", "fire"}


def test_runtime_preload_union_is_applied_to_every_swap_target() -> None:
    charts = (_chart("fire"), _chart("ice"), _chart("soccer"))
    merged = unify_runtime_preloads(charts)
    assert len(merged) == 3
    assert all(set(chart.noteskin_banks) == {"fire", "ice", "soccer"} for chart in merged)
