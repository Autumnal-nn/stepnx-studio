from __future__ import annotations

from stepnx.exporters import ssc
from stepnx.exporters.ssc_item_semantics import XSANITY_LATE_ITEM_CHARS


def test_late_item_alphabet_matches_official_sanity_pairs() -> None:
    assert XSANITY_LATE_ITEM_CHARS == {
        21: "i",
        22: "n",
        23: "t",
    }
    assert ssc._ITEM_CHARS[21] == "i"
    assert ssc._ITEM_CHARS[22] == "n"
    assert ssc._ITEM_CHARS[23] == "t"


def test_random_speed_nuke_and_hyper_potion_render_as_native_item_tokens() -> None:
    state = ssc._ExportState()
    where = (0, 0, 0, 0)

    # 0x41 is the bonus/pickup item class and layer 3 maps to Sanity layer 4.
    assert ssc._render_item(state, bytes((0x41, 3, 21, 0xC0)), where) == "{i04}"
    assert ssc._render_item(state, bytes((0x41, 3, 22, 0xC0)), where) == "{n04}"
    assert ssc._render_item(state, bytes((0x41, 3, 23, 0xC0)), where) == "{t04}"
    assert not state.diagnostics


def test_ef1329_hypot_shape_maps_exactly_to_official_sanity_token() -> None:
    state = ssc._ExportState()

    # EF1329/D.NX contains exactly one 0x41/layer3/item23 cell. The official
    # Sanity STEP.SSC represents that cell as {t04}.
    assert ssc._render_item(state, bytes((0x41, 3, 23, 0xC0)), (0, 0, 0, 0)) == "{t04}"
    assert all(item.code != "ssc.unknown-item" for item in state.diagnostics)
