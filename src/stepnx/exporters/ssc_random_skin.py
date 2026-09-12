"""XSanity projection for NX Random Skin / RSK semantics.

Two native NX encodings request Random Skin behavior:

* Header 19 is the Fiesta/Prime ``RSK`` selector.
* Header noteskin values 900..905 may contain the native Random sentinel 254.

Runtime testing established an important target limitation. XSanity can render
these bank-0 notes with genuinely random skins when Display -> Random Skin is
enabled *before chart selection*, but the tested standalone SSC paths do not
turn that option on early enough: ``#ATTACKS:...MODS=randomskin``, ``MODS=RSK``,
and ``#QUESTMODS:RSK`` were all ineffective. Static inspection agrees with the
runtime result: ``QUESTMODS`` is stored as Steps metadata, while the ordinary
PlayerOptions token table contains randomspeed/randomvel/randomnote but no
randomskin token.

The exporter therefore preserves Random Skin as runtime-compatible bank-0
notes instead of freezing a pseudo-random pattern into the file. It emits a
corpus-backed ``#RANDOMSKINLIST`` and preloads the candidate skins, but also
reports that the target build requires the Random Skin Display modifier to be
enabled before selecting the chart. This keeps every play genuinely random
when the native option is active and avoids pretending that a deterministic
export-time sequence is equivalent to RSK.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Iterable, Iterator

from stepnx.authoring.snapshot import AuthoringSnapshot
from stepnx.exporters import ssc
from stepnx.exporters import ssc_header_semantics as header_semantics
from stepnx.exporters.ssc import SscExportError
from stepnx.exporters.ssc_division import SscDivisionRuntime
from stepnx.exporters.ssc_header_semantics import (
    RANDOM_SKIN_CORPUS_POOL,
    XSANITY_BANK_CHARS,
)

_RANDOM_SKIN_HEADER_ID = 19
_RANDOM_SKIN_VALUE = 254
_RANDOM_SKIN_DIAGNOSTIC = "ssc.random-noteskin-header"
_RANDOM_SKIN_WARNING = (
    "NX requests Random Skin. The tested XSanity build reproduces it only when "
    "Display -> Random Skin is enabled before chart selection; ATTACKS/QUESTMODS "
    "cannot enable that pre-load option from a standalone SSC. The export keeps "
    "affected notes on bank 0 so the native modifier still works when enabled."
)

# Exact non-empty RANDOMSKINLIST used by official Fiesta EX content. Runtime
# testing proved that the list alone does not enable Random Skin; it describes
# the candidate family used once the native Display option is already active.
RANDOM_SKIN_RUNTIME_LIST = ("nx", "old", "music", "poker", "flower")


def _header_values(snapshot: AuthoringSnapshot) -> dict[int, int]:
    values: dict[int, int] = {}
    for entry in snapshot.header_metadata:
        values[int(entry.meta_id)] = int(entry.value)
    return values


def random_skin_requested(snapshot: AuthoringSnapshot) -> bool:
    """Return whether the NX source requests native Random Skin behavior."""

    values = _header_values(snapshot)
    selector = values.get(_RANDOM_SKIN_HEADER_ID)
    if selector is not None and selector not in (0, 0xFFFFFFFF):
        return True
    return any(values.get(meta_id) == _RANDOM_SKIN_VALUE for meta_id in range(900, 906))


def random_skin_header_enabled(snapshot: AuthoringSnapshot) -> bool:
    """Return whether Header 19 specifically enables the RSK modifier."""

    value = _header_values(snapshot).get(_RANDOM_SKIN_HEADER_ID)
    return value is not None and value not in (0, 0xFFFFFFFF)


@contextmanager
def random_skin_projection_context(snapshot: AuthoringSnapshot) -> Iterator[None]:
    """Keep RSK/direct-254 notes on bank 0 so XSanity may randomize them.

    The ordinary header-semantic layer handles 901..905. For Random Skin we also
    expose header 900 as slot zero, because direct-254 Fiesta missions use that
    default slot. Header 19 mirrors the native fallback by filling every
    otherwise-unconfigured slot, including slot zero, with sentinel 254.

    ``header_noteskin_context`` then resolves 254 to bank 0. The diagnostic is
    rewritten here to document the tested loader limitation rather than claiming
    an ineffective ATTACKS/QUESTMODS path can enable RSK.
    """

    if not random_skin_requested(snapshot):
        yield
        return

    previous_slots = header_semantics.player_slot_skin_values
    previous_note = ssc._ExportState.note

    def player_slots(active_snapshot: AuthoringSnapshot) -> dict[int, int]:
        configured = dict(previous_slots(active_snapshot))
        values = _header_values(active_snapshot)
        if 900 in values:
            configured[0] = values[900]
        if random_skin_header_enabled(active_snapshot):
            for player in range(6):
                configured.setdefault(player, _RANDOM_SKIN_VALUE)
        return configured

    def note(self, code: str, message: str, *args, **kwargs):
        if code == _RANDOM_SKIN_DIAGNOSTIC:
            message = _RANDOM_SKIN_WARNING
        return previous_note(self, code, message, *args, **kwargs)

    header_semantics.player_slot_skin_values = player_slots
    ssc._ExportState.note = note
    try:
        yield
    finally:
        ssc._ExportState.note = previous_note
        header_semantics.player_slot_skin_values = previous_slots


def _preload_order(names: set[str]) -> tuple[str, ...]:
    ordered = tuple(name for name in XSANITY_BANK_CHARS if name in names)
    extras = tuple(sorted(names.difference(XSANITY_BANK_CHARS)))
    return ordered + extras


def add_random_skin_preloads(
    runtime: SscDivisionRuntime,
    snapshot: AuthoringSnapshot,
) -> SscDivisionRuntime:
    """Preload Random Skin candidates before any T/O0/#DIVISION Steps swap."""

    if not random_skin_requested(snapshot):
        return runtime

    charts = []
    for item in runtime.charts:
        names = set(item.chart.noteskin_banks)
        names.update(RANDOM_SKIN_CORPUS_POOL)
        names.update(RANDOM_SKIN_RUNTIME_LIST)
        chart = replace(item.chart, noteskin_banks=_preload_order(names))
        charts.append(replace(item, chart=chart))
    return replace(runtime, charts=tuple(charts))


def random_skin_flags(
    snapshot: AuthoringSnapshot,
    chart_count: int,
) -> tuple[bool, ...]:
    enabled = random_skin_requested(snapshot)
    return tuple(enabled for _ in range(chart_count))


def inject_random_skin_metadata(text: str, flags: Iterable[bool]) -> str:
    """Emit the proven per-Steps candidate list without a fake enable command.

    The tested XSanity build accepts ``#RANDOMSKINLIST`` but does not let a
    standalone SSC enable the pre-load Display Random Skin option through
    ATTACKS or QUESTMODS. Consequently this function writes only the candidate
    list. The note banks remain zero/random-compatible and the export diagnostic
    tells the user that Random Skin must be enabled before chart selection.
    """

    frozen = tuple(bool(flag) for flag in flags)
    if not any(frozen):
        return text

    skin_list = ",".join(RANDOM_SKIN_RUNTIME_LIST)
    output: list[str] = []
    chart_index = -1
    inserted: set[int] = set()
    for line in text.splitlines():
        if line == "#NOTEDATA:;":
            chart_index += 1

        if (
            line.startswith("#DIFFICULTY:")
            and 0 <= chart_index < len(frozen)
            and frozen[chart_index]
        ):
            output.append(f"#RANDOMSKINLIST:{skin_list};")
            inserted.add(chart_index)

        output.append(line)

    if chart_index + 1 != len(frozen):
        raise SscExportError(
            f"rendered simfile contains {chart_index + 1} chart sections but "
            f"{len(frozen)} Random Skin flags were expected"
        )

    missing = [index for index, flag in enumerate(frozen) if flag and index not in inserted]
    if missing:
        raise SscExportError(
            "rendered simfile is missing #DIFFICULTY for Random Skin chart section(s): "
            + ", ".join(str(index + 1) for index in missing)
        )
    return "\n".join(output) + "\n"


__all__ = [
    "RANDOM_SKIN_RUNTIME_LIST",
    "add_random_skin_preloads",
    "inject_random_skin_metadata",
    "random_skin_flags",
    "random_skin_header_enabled",
    "random_skin_projection_context",
    "random_skin_requested",
]
