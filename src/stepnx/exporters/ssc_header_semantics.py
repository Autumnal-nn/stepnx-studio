"""NX20 header semantics needed by the XSanity SSC projection.

The note payload's third byte is a *slot selector*, not an XSanity noteskin
bank. NXA/Fiesta metadata IDs 900..905 configure the six noteskin slots:
900 is the default slot and 901..905 are the explicit P1..P5 slots.

Fiesta 2's native string table gives the numeric skin enumeration. The Sanity
SSC corpus provides the target folder aliases (for example ``skin_hwatoo`` ->
``flower`` and ``skin_left`` -> ``perfor1``). Keeping this translation outside
the low-level SSC writer is intentional: the writer also uses the fourth byte
as a direct legacy bank selector for several note kinds, and that field must not
be remapped through 900..905.

Runtime A/B testing also established that every noteskin reachable through a
Steps swap must already be preloaded by the controlling chart. The helpers in
this module therefore expose both per-note slot decoding and deterministic
preload-union helpers.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Iterable, Iterator

from stepnx.authoring.snapshot import AuthoringSnapshot
from stepnx.exporters import ssc


NX20_NOTESKIN_NAMES: dict[int, str] = {
    1: "flower",
    2: "old",
    3: "easy",
    4: "slime",
    5: "music",
    6: "canon",
    7: "poker",
    8: "nx",
    9: "sheep",
    10: "horse",
    11: "dog",
    12: "girl",
    13: "fire",
    14: "ice",
    15: "wind",
    16: "perfor1",
    17: "perfor2",
    18: "perfor3",
    19: "nxa",
    20: "nx2",
    21: "lightning",
    22: "drum",
    23: "missile",
    24: "aadmb",
    25: "aadmr",
    26: "aadmy",
    27: "soccer",
    28: "rebirth",
    29: "basic",
    30: "fiesta",
}

XSANITY_BANK_CHARS: dict[str, str] = {
    "perfor1": "1",
    "perfor2": "2",
    "perfor3": "3",
    "soccer": "4",
    "aadmb": "5",
    "aadmr": "6",
    "aadmy": "7",
    "flower": "8",
    "old": "9",
    "easy": "a",
    "slime": "b",
    "canon": "c",
    "poker": "d",
    "music": "e",
    "nx": "f",
    "sheep": "g",
    "horse": "h",
    "dog": "i",
    "girl": "j",
    "fire": "k",
    "ice": "l",
    "wind": "m",
    "nxa": "n",
    "nx2": "o",
    "lightning": "p",
    "drum": "q",
    "missile": "r",
    "rebirth": "s",
    "basic": "t",
    "fiesta": "u",
    "fiesta2": "v",
    "prime2": "w",
}

_XSANITY_PRELOAD_ORDER = tuple(XSANITY_BANK_CHARS)
_PLAYER_HEADER_IDS = {1: 901, 2: 902, 3: 903, 4: 904, 5: 905}
_RANDOM_SKIN_ID = 254
_RANDOM_SKIN_SELECTOR_ID = 19

RANDOM_SKIN_CORPUS_POOL = (
    "easy",
    "music",
    "canon",
    "horse",
    "fire",
    "ice",
    "wind",
    "nxa",
    "nx2",
    "fiesta2",
)


def _header_values(snapshot: AuthoringSnapshot) -> dict[int, int]:
    """Return last-value-wins header metadata, matching native scalar lookup."""

    values: dict[int, int] = {}
    for entry in snapshot.header_metadata:
        values[int(entry.meta_id)] = int(entry.value)
    return values


def noteskin_name(value: int) -> str | None:
    """Map one native noteskin payload to a Sanity folder name when known."""

    if value == 0:
        return None
    return NX20_NOTESKIN_NAMES.get(int(value))


def player_slot_skin_values(snapshot: AuthoringSnapshot) -> dict[int, int]:
    """Resolve P1..P5 noteskin payloads, including native Header-19 RSK fallback.

    An ordinary absent 901..905 entry is deliberately *not* replaced by header
    900. Exact Fiesta EX pairs disproved that shortcut. Header 19 is different:
    the recovered native ``ApplyStepParamToMod`` routine explicitly writes skin
    sentinel 254 into every otherwise-unconfigured slot when Random Skin is
    active. Mirroring that behavior is essential because an explicit SSC bank
    (for example perfor1) is not affected by the target's random-skin runtime
    machinery; an RSK slot must remain bank 0/random instead.
    """

    values = _header_values(snapshot)
    configured = {
        player: values[meta_id]
        for player, meta_id in _PLAYER_HEADER_IDS.items()
        if meta_id in values
    }
    selector = values.get(_RANDOM_SKIN_SELECTOR_ID)
    if selector is not None and selector not in (0, 0xFFFFFFFF):
        for player in _PLAYER_HEADER_IDS:
            configured.setdefault(player, _RANDOM_SKIN_ID)
    return configured


def header_preload_noteskins(snapshot: AuthoringSnapshot) -> tuple[str, ...]:
    """Return every known skin named by metadata 900..905."""

    values = _header_values(snapshot)
    names: set[str] = set()
    for meta_id in range(900, 906):
        value = values.get(meta_id)
        if value is None or value == 0:
            continue
        if value == _RANDOM_SKIN_ID:
            names.update(RANDOM_SKIN_CORPUS_POOL)
            continue
        name = noteskin_name(value)
        if name is not None:
            names.add(name)
    return tuple(name for name in _XSANITY_PRELOAD_ORDER if name in names)


def resolved_meter(snapshot: AuthoringSnapshot, explicit: int | None = None) -> int | None:
    """Resolve SSC meter as explicit > ordinary level 1001 > mission level 1101."""

    if explicit is not None and explicit > 0:
        return explicit
    values = _header_values(snapshot)
    ordinary = values.get(1001, 0)
    if ordinary > 0:
        return ordinary
    mission = values.get(1101, 0)
    if mission > 0:
        return mission
    return explicit


def _player_bank_char(
    state,
    player: int,
    where: tuple[int, int, int, int],
    configured: dict[int, int],
) -> str:
    value = configured.get(player)
    if value is None:
        return ssc._bank_char(state, player, where)
    if value == 0:
        return "0"
    if value == _RANDOM_SKIN_ID:
        state.note(
            "ssc.random-noteskin-header",
            "NX header noteskin 254 is Random Skin; its selection is delegated to "
            "XSanity RANDOMSKINLIST/randomskin runtime semantics",
            *where,
        )
        return "0"

    name = noteskin_name(value)
    if name is None:
        state.note(
            "ssc.unknown-header-noteskin",
            f"NX header noteskin value {value} has no Sanity folder mapping; the note "
            "keeps the runtime default skin",
            *where,
        )
        return "0"

    bank = XSANITY_BANK_CHARS.get(name)
    if bank is None:
        state.note(
            "ssc.unaddressable-header-noteskin",
            f"Sanity noteskin {name!r} has no XSanity bank character; the note keeps "
            "the runtime default skin",
            *where,
        )
        return "0"
    state.banks.add(name)
    return bank


def _render_cell_with_header(
    configured: dict[int, int],
    state,
    raw: bytes,
    brain_char: str,
    where: tuple[int, int, int, int],
) -> str:
    kind, layer, player, special = raw
    if kind == 0:
        return "0"

    if special == ssc.NOTE_ITEM_MARKER:
        return ssc._render_item(state, raw, where)

    if kind == ssc.NOTE_BRAIN:
        head = "3"
        if special == ssc.NOTE_BRAIN_SPECIAL_CLEAR:
            head = "-"
        elif special == ssc.NOTE_BRAIN_SPECIAL_CROSS:
            head = "+"
        return "{" + head + brain_char + ssc._LAYER_BRAIN + "}"

    entry = ssc._NOTE_TABLE.get(kind)
    if entry is None:
        state.note(
            "ssc.unknown-note",
            f"note byte 0x{kind:02X} has no XSanity equivalent and is written as a mine",
            *where,
        )
        return ssc._MINE_CHAR

    head, note_class, bank_source, brace_optional = entry
    if note_class is None:
        return head

    if bank_source == ssc._BANK_FROM_PLAYER:
        bank = _player_bank_char(state, player, where, configured)
    else:
        bank = ssc._bank_char(state, special, where)

    layer_char = ssc._layer_char(state, note_class, layer, where)
    if brace_optional and layer_char == "0" and bank == "0":
        return head
    return "{" + head + bank + layer_char + "}"


@contextmanager
def header_noteskin_context(snapshot: AuthoringSnapshot) -> Iterator[None]:
    """Temporarily make the low-level writer honor this chart's 901..905 slots."""

    configured = player_slot_skin_values(snapshot)
    if not configured:
        yield
        return

    previous = ssc._render_cell

    def render_cell(state, raw: bytes, brain_char: str, where):
        return _render_cell_with_header(configured, state, raw, brain_char, where)

    ssc._render_cell = render_cell
    try:
        yield
    finally:
        ssc._render_cell = previous


def apply_header_preloads(chart, snapshot: AuthoringSnapshot):
    """Add every header-declared skin to one generated SSC chart."""

    names = set(chart.noteskin_banks)
    names.update(header_preload_noteskins(snapshot))
    ordered = tuple(name for name in _XSANITY_PRELOAD_ORDER if name in names)
    extras = tuple(sorted(names.difference(_XSANITY_PRELOAD_ORDER)))
    return replace(chart, noteskin_banks=ordered + extras)


def unify_runtime_preloads(charts: Iterable):
    """Give every runtime-switchable chart the union of all bundle noteskins."""

    frozen = tuple(charts)
    names: set[str] = set()
    for chart in frozen:
        names.update(chart.noteskin_banks)
    ordered = tuple(name for name in _XSANITY_PRELOAD_ORDER if name in names)
    extras = tuple(sorted(names.difference(_XSANITY_PRELOAD_ORDER)))
    merged = ordered + extras
    return tuple(replace(chart, noteskin_banks=merged) for chart in frozen)


__all__ = [
    "NX20_NOTESKIN_NAMES",
    "RANDOM_SKIN_CORPUS_POOL",
    "XSANITY_BANK_CHARS",
    "apply_header_preloads",
    "header_noteskin_context",
    "header_preload_noteskins",
    "noteskin_name",
    "player_slot_skin_values",
    "resolved_meter",
    "unify_runtime_preloads",
]
