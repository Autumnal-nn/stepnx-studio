"""XSanity projection for NX Random Skin / RSK semantics.

Two native NX encodings reach Random Skin behavior:

* Header 19 is the Fiesta/Prime ``RSK`` selector. Runtime treats any nonzero
  value as enabled and fills otherwise-unconfigured player skin slots with the
  native Random sentinel 254.
* Header noteskin values 900..905 may contain 254 directly.

The Sanity corpus exposes two mechanisms relevant to those sources. Arcade NXA
charts use the player option ``randomskin`` through ``#ATTACKS``. Fiesta EX
mission charts also prove a dedicated per-Steps ``#RANDOMSKINLIST`` that changes
bank-0 notes among a preloaded skin list. Runtime testing showed that emitting
only the attack is insufficient for a direct-254 Fiesta 2 chart, so the exporter
uses both native mechanisms: bank-0/random slots are preserved, a corpus-backed
RandomSkinList is emitted, and Header-19 RSK additionally remains compatible
with the ordinary ``randomskin`` player option.

The runtime also proved that Steps swaps can crash when the destination needs a
noteskin that was not already loaded. Random Skin therefore preloads every skin
in the emitted list on all runtime-switchable Steps sections.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Iterable, Iterator

from stepnx.authoring.snapshot import AuthoringSnapshot
from stepnx.exporters import ssc
from stepnx.exporters.ssc_division import SscDivisionRuntime
from stepnx.exporters.ssc_header_semantics import (
    RANDOM_SKIN_CORPUS_POOL,
    XSANITY_BANK_CHARS,
)

_RANDOM_SKIN_HEADER_ID = 19
_RANDOM_SKIN_VALUE = 254
_RANDOM_SKIN_DIAGNOSTIC = "ssc.random-noteskin-header"

# Exact non-empty RANDOMSKINLIST used by official Fiesta EX EF1603. Unlike the
# ten-skin EF1475 preload family, this is direct evidence for the runtime list
# grammar itself, so it is the conservative default when NX only says "random"
# without carrying a candidate list.
RANDOM_SKIN_RUNTIME_LIST = ("nx", "old", "music", "poker", "flower")

# Every observed Arcade ``randomskin`` attack uses a finite 180-second window.
# Using the corpus value is safer than the previous guessed LEN=9999, which the
# target accepted syntactically but did not reproduce EF1329's skin changes.
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


@contextmanager
def random_skin_projection_context(snapshot: AuthoringSnapshot) -> Iterator[None]:
    """Suppress the obsolete direct-254 lossy diagnostic while projecting."""

    if not random_skin_requested(snapshot):
        yield
        return

    previous = ssc._ExportState.note

    def note(self, code: str, message: str, *args, **kwargs):
        if code == _RANDOM_SKIN_DIAGNOSTIC:
            return None
        return previous(self, code, message, *args, **kwargs)

    ssc._ExportState.note = note
    try:
        yield
    finally:
        ssc._ExportState.note = previous


def _preload_order(names: set[str]) -> tuple[str, ...]:
    ordered = tuple(name for name in XSANITY_BANK_CHARS if name in names)
    extras = tuple(sorted(names.difference(XSANITY_BANK_CHARS)))
    return ordered + extras


def add_random_skin_preloads(
    runtime: SscDivisionRuntime,
    snapshot: AuthoringSnapshot,
) -> SscDivisionRuntime:
    """Preload every skin needed by RandomSkinList before any Steps swap."""

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
    """Insert native RandomSkinList plus the XSanity randomskin player option.

    ``#RANDOMSKINLIST`` is inserted before DIFFICULTY, matching official
    StepPrime mission ordering. ``#ATTACKS`` remains immediately before NOTES,
    matching the Arcade NXA files that use the player option. Keeping both is
    intentional: direct NX skin 254 is a per-note/list semantic, while Header 19
    is also an RSK gameplay modifier. The target safely accepts the combination
    and it avoids converting either source into one fixed skin at export time.
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
