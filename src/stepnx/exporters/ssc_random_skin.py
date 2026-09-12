"""XSanity projection for NX Random Skin / RSK semantics.

Two native NX encodings reach the same display behavior:

* Header 19 is the Fiesta/Prime ``RSK`` selector. Runtime treats any nonzero
  value as enabled for the display modifier and official Fiesta 2 / Prime 2
  charts use value 6.
* Header noteskin values 900..905 may contain the direct noteskin value 254,
  which is the native Random noteskin sentinel.

XSanity already exposes the equivalent player option as the ``randomskin``
modifier. The safest projection is therefore to preserve the original note
payload and activate that modifier for the whole generated Steps lifetime,
rather than choosing one fixed noteskin at export time.

The runtime also proved that Steps swaps can crash when the destination needs a
noteskin that was not already loaded. For Random Skin charts we preload the
known Sanity random-skin family on every runtime-switchable Steps section.
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
_RANDOM_SKIN_ATTACK = "#ATTACKS:TIME=0.000000:LEN=9999.000000:MODS=randomskin;"
_RANDOM_SKIN_DIAGNOSTIC = "ssc.random-noteskin-header"


def _header_values(snapshot: AuthoringSnapshot) -> dict[int, int]:
    values: dict[int, int] = {}
    for entry in snapshot.header_metadata:
        values[int(entry.meta_id)] = int(entry.value)
    return values


def random_skin_requested(snapshot: AuthoringSnapshot) -> bool:
    """Return whether the source requests native Random Skin behavior.

    Header 19 is the RSK selector. Direct 254 in any noteskin slot is the older
    per-slot form used by official mission charts. The native -1 sentinel is not
    considered an enabled selector.
    """

    values = _header_values(snapshot)
    selector = values.get(_RANDOM_SKIN_HEADER_ID)
    if selector is not None and selector not in (0, 0xFFFFFFFF):
        return True
    return any(values.get(meta_id) == _RANDOM_SKIN_VALUE for meta_id in range(900, 906))


@contextmanager
def random_skin_projection_context(snapshot: AuthoringSnapshot) -> Iterator[None]:
    """Suppress the old 'Random Skin is lossy' warning while projecting.

    ``ssc_header_semantics`` deliberately emits that warning when a configured
    P1..P5 slot is 254 because the low-level writer cannot materialize native
    random choice by itself. The final XSanity renderer now preserves that
    behavior with an actual ``randomskin`` attack, so the warning would be stale
    and alternate Division route projection would incorrectly reject the chart.

    The low-level writer already uses a short-lived monkeypatch context for
    header noteskin decoding. This context follows the same exporter-local
    pattern and restores the method immediately after projection.
    """

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
    """Preload the known Random Skin family on every switchable Steps."""

    if not random_skin_requested(snapshot):
        return runtime

    charts = []
    for item in runtime.charts:
        names = set(item.chart.noteskin_banks)
        names.update(RANDOM_SKIN_CORPUS_POOL)
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
    """Insert a full-chart XSanity ``randomskin`` attack into selected Steps.

    The Sanity corpus encodes RSK as a per-Steps ``#ATTACKS`` player modifier,
    e.g. ``MODS=...,randomskin``. We use a long finite interval rather than a
    guessed song duration so the modifier remains active across every practical
    PIU chart and through T/O0/#DIVISION Steps swaps.
    """

    frozen = tuple(bool(flag) for flag in flags)
    if not any(frozen):
        return text

    output: list[str] = []
    chart_index = -1
    inserted: set[int] = set()
    for line in text.splitlines():
        if line == "#NOTEDATA:;":
            chart_index += 1
        if line.startswith("#NOTES:") and 0 <= chart_index < len(frozen) and frozen[chart_index]:
            output.append(_RANDOM_SKIN_ATTACK)
            inserted.add(chart_index)
        output.append(line)

    if chart_index + 1 != len(frozen):
        raise ssc.SscExportError(
            f"rendered simfile contains {chart_index + 1} chart sections but "
            f"{len(frozen)} Random Skin flags were expected"
        )
    missing = [index for index, flag in enumerate(frozen) if flag and index not in inserted]
    if missing:
        raise ssc.SscExportError(
            "rendered simfile is missing #NOTES for Random Skin chart section(s): "
            + ", ".join(str(index + 1) for index in missing)
        )
    return "\n".join(output) + "\n"


__all__ = [
    "add_random_skin_preloads",
    "inject_random_skin_attacks",
    "random_skin_flags",
    "random_skin_projection_context",
    "random_skin_requested",
]
