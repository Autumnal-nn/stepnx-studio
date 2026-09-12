from __future__ import annotations

from types import SimpleNamespace

from stepnx.exporters import ssc
from stepnx.exporters.ssc import SscChart
from stepnx.exporters.ssc_header_semantics import (
    NX20_NOTESKIN_NAMES,
    apply_header_preloads,
    header_noteskin_context,
    header_preload_noteskins,
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
        # Normal tap, player slot 2 -> header 902 == 13 == fire -> XSanity bank k.
        assert ssc._render_cell(state, bytes((0x43, 3, 2, 0)), "0", (0, 0, 0, 0)) == "{1k0}"
        # Player slot 4 -> header 904 == 3 == easy -> bank a.
        assert ssc._render_cell(state, bytes((0x43, 3, 4, 0)), "0", (0, 0, 1, 0)) == "{1a0}"
        # 0x47 takes its bank from the *special* byte. Header remapping must not
        # reinterpret that direct legacy selector; special 4 remains soccer.
        assert ssc._render_cell(state, bytes((0x47, 3, 0, 4)), "0", (0, 0, 2, 0)) == "{440}"

    assert {"fire", "easy", "soccer"}.issubset(state.banks)


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
