"""NX20 header semantics needed by the XSanity SSC projection.

The note payload's third byte is a *slot selector*, not an XSanity noteskin
bank.  NXA/Fiesta metadata IDs 900..905 configure the six noteskin slots:
900 is the default slot and 901..905 are the explicit P1..P5 slots.

Fiesta 2's native string table gives the numeric skin enumeration.  The Sanity
SSC corpus provides the target folder aliases (for example ``skin_hwatoo`` ->
``flower`` and ``skin_left`` -> ``perfor1``).  Keeping this translation outside
the low-level SSC writer is intentional: the writer also uses the fourth byte
as a direct legacy bank selector for several note kinds, and that field must not
be remapped through 900..905.

Runtime A/B testing also established that every noteskin reachable through a
Steps swap must already be preloaded by the controlling chart.  The helpers in
this module therefore expose both per-note slot decoding and deterministic
preload-union helpers.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Iterable, Iterator

from stepnx.authoring.snapshot import AuthoringSnapshot
from stepnx.exporters import ssc


# Fiesta 2 native order, converted to the folder names used by the Sanity
# corpus.  The native table is one-based at the NX metadata boundary: value 1
# selects skin_hwatoo, 2 skin_old, ... 30 skin_fiesta.
NX20_NOTESKIN_NAMES: dict[int, str] = {
    1: "flower",       # skin_hwatoo
    2: "old",
    3: "easy",         # skin_ez
    4: "slime",
    5: "music",        # skin_note
    6: "canon",
    7: "poker",        # skin_card
    8: "nx",
    9: "sheep",
    10: "horse",
    11: "dog",
    12: "girl",
    13: "fire",
    14: "ice",
    15: "wind",
    16: "perfor1",     # skin_left
    17: "perfor2",     # skin_right
    18: "perfor3",     # skin_both
    19: "nxa",
    20: "nx2",
    21: "lightning",
    22: "drum",
    23: "missile",
    24: "aadmb",       # skin_drum_b
    25: "aadmr",       # skin_drum_r
    26: "aadmy",       # skin_drum_y
    27: "soccer",      # skin_football
    28: "rebirth",
    29: "basic",
    30: "fiesta",
}

# XSanity bank alphabet.  x/y/z are intentionally unassigned by the target.
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

# EF1475 in the Sanity Fiesta EX corpus materializes metadata value 254 as this
# ten-skin random family.  We document the evidence but do not pretend that a
# fixed per-note bank can preserve the native random-skin behavior yet.
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
    """Return explicit P1..P5 noteskin payloads from IDs 901..905.

    ID 900 is deliberately not substituted for a missing Pn field here.  Exact
    Fiesta EX pairs show that an absent Pn entry is not represented by blindly
    banking those notes with the 900 value.  Unconfigured slots therefore keep
    the writer's legacy/default behavior until that native fallback is proven.
    """

    values = _header_values(snapshot)
    return {
        player: values[meta_id]
        for player, meta_id in _PLAYER_HEADER_IDS.items()
        if meta_id in values
    }


def header_preload_noteskins(snapshot: AuthoringSnapshot) -> tuple[str, ...]:
    """Return every known skin named by metadata 900..905.

    Preloading the complete header family is cheap and, more importantly,
    prevents XSanity from dereferencing an unloaded noteskin when #DIVISION/T
    swaps into a backing Steps that uses a skin absent from the controller.
    """

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
            "NX header noteskin 254 is Random Skin; its per-note native selection is not "
            "materialized yet, so this note keeps the runtime default skin",
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
    """Header-aware copy of the writer's cell renderer.

    Only ``BANK_FROM_PLAYER`` changes.  ``BANK_FROM_SPECIAL`` keeps the original
    direct-byte interpretation, which is why replacing the writer's global bank
    table would be incorrect.
    """

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
    """Give every runtime-switchable chart the union of all bundle noteskins.

    XSanity crashes when a Steps swap lands on a chart that introduces a skin
    the currently active Steps did not preload.  Applying the union to all
    members also makes later Wrap0/T transitions symmetric and safe.
    """

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
