"""XSanity projection for NX Random Skin / RSK semantics.

Two native NX encodings reach Random Skin behavior:

* Header 19 is the Fiesta/Prime ``RSK`` selector. Runtime treats any nonzero
  value as enabled and fills otherwise-unconfigured player skin slots with the
  native Random sentinel 254.
* Header noteskin values 900..905 may contain 254 directly.

Runtime testing on the target XSanity build showed that merely emitting the
``randomskin`` PlayerOption or a non-empty ``#RANDOMSKINLIST`` leaves affected
notes on the default skin. The Sanity Fiesta EX corpus explains why: charts with
non-empty ``#RANDOMSKINLIST`` already carry explicit per-note noteskin banks;
the list describes the candidate family rather than replacing those banks for
us.

The exporter therefore materializes Random Skin into deterministic per-note
banks from a corpus-proven five-skin family. This preserves the visible
skin-changing behavior without depending on an engine-side randomizer that is
not active in the tested loader. The exact native RNG stream is intentionally
not claimed: repeated exports are stable, while the original game may choose a
different random sequence each play.

Every materialized skin is preloaded before T/O0/#DIVISION swaps, following the
runtime rule established by the Division Access-Violation tests.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Iterable, Iterator
import zlib

from stepnx.authoring.snapshot import AuthoringSnapshot
from stepnx.exporters import ssc
from stepnx.exporters import ssc_header_semantics as header_semantics
from stepnx.exporters.ssc_division import SscDivisionRuntime
from stepnx.exporters.ssc_header_semantics import (
    RANDOM_SKIN_CORPUS_POOL,
    XSANITY_BANK_CHARS,
)

_RANDOM_SKIN_HEADER_ID = 19
_RANDOM_SKIN_VALUE = 254
_RANDOM_SKIN_DIAGNOSTIC = "ssc.random-noteskin-header"

# Exact non-empty RANDOMSKINLIST used by official Fiesta EX EF1603. These five
# skins also have stable XSanity bank characters and are safe to materialize.
RANDOM_SKIN_RUNTIME_LIST = ("nx", "old", "music", "poker", "flower")

# Keep the historical modifier in the generated file as metadata/compatibility,
# but correctness no longer depends on it because affected notes now carry an
# explicit bank. 180 seconds is the exact window used by the Arcade Sanity
# randomskin examples D02/D03.
_RANDOM_SKIN_ATTACK = "#ATTACKS:TIME=0.000000:LEN=180.000000:MODS=randomskin;"


def _header_values(snapshot: AuthoringSnapshot) -> dict[int, int]:
    values: dict[int, int] = {}
    for entry in snapshot.header_metadata:
        values[int(entry.meta_id)] = int(entry.value)
    return values


def random_skin_requested(snapshot: AuthoringSnapshot) -> bool:
    """Return whether the source requests native Random Skin behavior."""

    values = _header_values(snapshot)
    selector = values.get(_RANDOM_SKIN_HEADER_ID)
    if selector is not None and selector not in (0, 0xFFFFFFFF):
        return True
    return any(values.get(meta_id) == _RANDOM_SKIN_VALUE for meta_id in range(900, 906))


def random_skin_header_enabled(snapshot: AuthoringSnapshot) -> bool:
    """Return whether Header 19 specifically enables the RSK modifier."""

    value = _header_values(snapshot).get(_RANDOM_SKIN_HEADER_ID)
    return value is not None and value not in (0, 0xFFFFFFFF)


def _seed(snapshot: AuthoringSnapshot) -> int:
    identity = f"{snapshot.source_name or ''}|{snapshot.document_stable_id}".encode(
        "utf-8", "surrogatepass"
    )
    return zlib.crc32(identity) & 0xFFFFFFFF


def _random_skin_name(seed: int, where: tuple[int, int, int, int]) -> str:
    """Choose one stable candidate for a source note location.

    Python's process-randomized ``hash`` is deliberately avoided so exporting
    the same chart twice yields identical SSC bytes.
    """

    split_index, block_index, row_index, lane = where
    value = seed
    value ^= ((split_index + 1) * 0x9E3779B1) & 0xFFFFFFFF
    value ^= ((block_index + 1) * 0x85EBCA6B) & 0xFFFFFFFF
    value ^= ((row_index + 1) * 0xC2B2AE35) & 0xFFFFFFFF
    value ^= ((lane + 1) * 0x27D4EB2F) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return RANDOM_SKIN_RUNTIME_LIST[value % len(RANDOM_SKIN_RUNTIME_LIST)]


@contextmanager
def random_skin_projection_context(snapshot: AuthoringSnapshot) -> Iterator[None]:
    """Materialize native Random Skin while the low-level note writer runs.

    The header-semantic layer normally resolves 901..905 and delegates 254 to a
    runtime modifier. Here we temporarily extend that resolver in two ways:

    * slot 0 is read from header 900, which is the actual source for notes whose
      player byte is zero;
    * any resolved value 254 is replaced by a deterministic explicit XSanity
      bank chosen per note.

    Header 19 keeps the recovered native behavior: every unspecified slot,
    including slot 0, becomes 254. All monkeypatches are exporter-local and are
    restored immediately after projection.
    """

    if not random_skin_requested(snapshot):
        yield
        return

    previous_note = ssc._ExportState.note
    previous_slots = header_semantics.player_slot_skin_values
    previous_bank = header_semantics._player_bank_char
    seed = _seed(snapshot)

    def note(self, code: str, message: str, *args, **kwargs):
        if code == _RANDOM_SKIN_DIAGNOSTIC:
            return None
        return previous_note(self, code, message, *args, **kwargs)

    def player_slots(active_snapshot: AuthoringSnapshot) -> dict[int, int]:
        configured = dict(previous_slots(active_snapshot))
        values = _header_values(active_snapshot)
        if 900 in values:
            configured[0] = values[900]
        if random_skin_header_enabled(active_snapshot):
            for player in range(6):
                configured.setdefault(player, _RANDOM_SKIN_VALUE)
        return configured

    def player_bank(state, player: int, where, configured: dict[int, int]) -> str:
        value = configured.get(player)
        if value == _RANDOM_SKIN_VALUE:
            name = _random_skin_name(seed, where)
            state.banks.add(name)
            return XSANITY_BANK_CHARS[name]
        return previous_bank(state, player, where, configured)

    ssc._ExportState.note = note
    header_semantics.player_slot_skin_values = player_slots
    header_semantics._player_bank_char = player_bank
    try:
        yield
    finally:
        header_semantics._player_bank_char = previous_bank
        header_semantics.player_slot_skin_values = previous_slots
        ssc._ExportState.note = previous_note


def _preload_order(names: set[str]) -> tuple[str, ...]:
    ordered = tuple(name for name in XSANITY_BANK_CHARS if name in names)
    extras = tuple(sorted(names.difference(XSANITY_BANK_CHARS)))
    return ordered + extras


def add_random_skin_preloads(
    runtime: SscDivisionRuntime,
    snapshot: AuthoringSnapshot,
) -> SscDivisionRuntime:
    """Preload every skin needed by materialized Random Skin notes."""

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


def inject_random_skin_attacks(text: str, flags: Iterable[bool]) -> str:
    """Emit corpus-shaped Random Skin metadata for materialized charts.

    Explicit note banks are the functional representation. ``RANDOMSKINLIST``
    records the candidate family used by the materializer, while the historical
    ``randomskin`` attack is retained for compatibility with XSanity builds that
    implement it. Either may be ignored by a loader without losing the visible
    skin variation because the cells themselves already select skins.
    """

    frozen = tuple(bool(flag) for flag in flags)
    if not any(frozen):
        return text

    skin_list = ",".join(RANDOM_SKIN_RUNTIME_LIST)
    output: list[str] = []
    chart_index = -1
    list_inserted: set[int] = set()
    attack_inserted: set[int] = set()
    for line in text.splitlines():
        if line == "#NOTEDATA:;":
            chart_index += 1

        if (
            line.startswith("#DIFFICULTY:")
            and 0 <= chart_index < len(frozen)
            and frozen[chart_index]
        ):
            output.append(f"#RANDOMSKINLIST:{skin_list};")
            list_inserted.add(chart_index)

        if (
            line.startswith("#NOTES:")
            and 0 <= chart_index < len(frozen)
            and frozen[chart_index]
        ):
            output.append(_RANDOM_SKIN_ATTACK)
            attack_inserted.add(chart_index)

        output.append(line)

    if chart_index + 1 != len(frozen):
        raise ssc.SscExportError(
            f"rendered simfile contains {chart_index + 1} chart sections but "
            f"{len(frozen)} Random Skin flags were expected"
        )

    missing_list = [
        index for index, flag in enumerate(frozen) if flag and index not in list_inserted
    ]
    if missing_list:
        raise ssc.SscExportError(
            "rendered simfile is missing #DIFFICULTY for Random Skin chart section(s): "
            + ", ".join(str(index + 1) for index in missing_list)
        )

    missing_attack = [
        index for index, flag in enumerate(frozen) if flag and index not in attack_inserted
    ]
    if missing_attack:
        raise ssc.SscExportError(
            "rendered simfile is missing #NOTES for Random Skin chart section(s): "
            + ", ".join(str(index + 1) for index in missing_attack)
        )
    return "\n".join(output) + "\n"


__all__ = [
    "RANDOM_SKIN_RUNTIME_LIST",
    "add_random_skin_preloads",
    "inject_random_skin_attacks",
    "random_skin_flags",
    "random_skin_header_enabled",
    "random_skin_projection_context",
    "random_skin_requested",
]
