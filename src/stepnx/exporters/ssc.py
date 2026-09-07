"""Export NX20 charts to the SSC dialect read by the XSanity engine.

XSanity is a StepMania 5 derivative whose note lines carry an optional
``{<kind><bank><layer>}`` group after each lane character: the first character
is the ordinary SM note kind, the second names a preloaded noteskin bank, and
the remaining characters describe the note's score, display, and effect layer.
This module projects an NX20 document onto that dialect.

A Hold Head or Tail whose sustain bit is clear is a Roll, and its scoring and
display layer come from the same function bits as every other note. The target
engine's own NX reader writes a fixed Bonus layer there instead, which turns a
hidden normal Roll into a visible Bonus one.

Visibility 4 and 5 of the second byte, VanishLow and AppearLow, reach the
target as its second-threshold appearance layers rather than as plain notes:
they fade at the same screen positions, further from the receptor than the
ordinary Vanish and Appear layers.

The projection is one-way and lossy by construction.  NX20 addresses rows
inside Divs at a per-Div Beat Split, while SSC addresses beats on a single
global grid, so every Div is resampled onto a fixed grid of
``LINE_BEAT_SPLIT`` lines per beat and its BPM is scaled by the ratio between
its own Beat Split and that grid.  Only the active branch of each Split is
written; alternate branches have no SSC representation.
"""

from __future__ import annotations

from dataclasses import dataclass

from stepnx.authoring.snapshot import (
    AuthoringSnapshot,
    BlockSnapshot,
    create_authoring_snapshot,
)
from stepnx.core.model import (
    EmptyRow,
    LightmapRow,
    NoteRow,
    NX20Document,
    PackedNoteRow,
)

SSC_VERSION = "0.83"
SSC_HEADER = "xSanity"
SSC_EXTENSION_HEADER = "xSanity Extension"

LINE_BEAT_SPLIT = 8
LINES_PER_MEASURE = LINE_BEAT_SPLIT * 4
BEATS_PER_LINE = 1.0 / LINE_BEAT_SPLIT

FROZEN_BPM = "9999999"
DIV_FLAG_SKIP = 0x02
DIV_FLAG_FREEZE = 0x03

BRAIN_TRIGGER_SCORE = 26

STEPS_TYPES = {5: "pump-single", 6: "pump-halfdouble", 10: "pump-double"}

NOTE_KIND_MASK = 0x0F
NOTE_CLASS_MASK = 0x60
NOTE_CLASS_FAKE = 0x20
NOTE_CLASS_NORMAL = 0x40
NOTE_CLASS_BONUS = 0x60

NOTE_ITEM_MARKER = 0xC0
NOTE_BRAIN = 0x42
NOTE_BRAIN_SPECIAL_CLEAR = 0xC6
NOTE_BRAIN_SPECIAL_CROSS = 0xC7

_LAYER_NORMAL = {0: "3", 1: "1", 2: "2", 3: "0", 4: "d", 5: "s", 19: "y"}
_LAYER_BONUS = {0: "7", 1: "5", 2: "6", 3: "4", 4: "j", 5: "h", 19: "k"}
_LAYER_FAKE = {1: "9", 2: "a", 3: "8", 4: "w", 5: "q", 18: "t"}

_LAYER_TABLES = {
    NOTE_CLASS_NORMAL: _LAYER_NORMAL,
    NOTE_CLASS_BONUS: _LAYER_BONUS,
    NOTE_CLASS_FAKE: _LAYER_FAKE,
}

_LAYER_FALLBACK = {
    NOTE_CLASS_NORMAL: "0",
    NOTE_CLASS_BONUS: "4",
    NOTE_CLASS_FAKE: "8",
}

# Noteskin banks.  The second character of a note's brace group names the bank,
# and the engine resolves that character to a skin folder.  Its full alphabet is:
#
#     0  (none)      9  old          i  dog          r  missile
#     1  perfor1     a  easy         j  girl         s  rebirth
#     2  perfor2     b  slime        k  fire         t  basic
#     3  perfor3     c  canon        l  ice          u  fiesta
#     4  soccer      d  poker        m  wind         v  fiesta2
#     5  aadmb       e  music        n  nxa          w  prime2
#     6  aadmr       f  nx           o  nx2
#     7  aadmy       g  sheep        p  lightning
#     8  flower      h  horse        q  drum
#
# x, y and z are unassigned and free for a new skin.
#
# Only a handful of those are reachable from NX20.  A note cell names its bank
# by slot number, not by skin name, and _BANK_SLOTS holds every slot whose skin
# is known; 64 and 128 are aliases of slots 1 and 2 seen in the corpus.  A slot
# outside that table is reported as ssc.unknown-noteskin-bank rather than
# guessed, because picking the wrong skin is worse than keeping the default.
#
# Adding a skin means learning which slot number selects it, then adding it to
# both tables below and to _BANK_ORDER, which fixes #PRELOADNOTESKIN ordering.
_BANK_ORDER = ("perfor1", "perfor2", "perfor3", "soccer", "fire")
_BANK_CHARS = {
    "perfor1": "1",
    "perfor2": "2",
    "perfor3": "3",
    "soccer": "4",
    "fire": "k",
}
_BANK_SLOTS = {
    0: None,
    1: "perfor1",
    2: "perfor2",
    3: "perfor3",
    4: "soccer",
    5: "fire",
    64: "perfor1",
    128: "perfor2",
}

_ITEM_CHARS = {
    0: "z",
    1: "x",
    2: "c",
    3: "y",
    4: "k",
    5: "M",
    6: "M",
    7: "l",
    8: "m",
    9: "h",
    10: "s",
    11: "b",
    12: "d",
    13: "f",
    14: "g",
    15: "a",
    16: "p",
    17: "e",
    18: "r",
    19: "w",
    20: "q",
    21: "i",
}

_SPECIAL_CHARS = {0: "G", 1: "W", 2: "z", 3: "x", 4: "c"}

_LAYER_BRAIN = "4"

_PLAIN_HOLD_BODY = "0"

_BANK_FROM_PLAYER = "player"
_BANK_FROM_SPECIAL = "special"

_NOTE_TABLE = {
    0x23: ("1", NOTE_CLASS_FAKE, _BANK_FROM_PLAYER, False),
    0x27: ("4", NOTE_CLASS_FAKE, _BANK_FROM_SPECIAL, False),
    0x2B: (_PLAIN_HOLD_BODY, None, None, False),
    0x2F: ("3", NOTE_CLASS_FAKE, _BANK_FROM_SPECIAL, False),
    0x37: ("2", NOTE_CLASS_FAKE, _BANK_FROM_PLAYER, False),
    0x3B: (_PLAIN_HOLD_BODY, None, None, False),
    0x3F: ("3", NOTE_CLASS_FAKE, _BANK_FROM_PLAYER, False),
    0x43: ("1", NOTE_CLASS_NORMAL, _BANK_FROM_PLAYER, True),
    0x47: ("4", NOTE_CLASS_NORMAL, _BANK_FROM_SPECIAL, False),
    0x4B: (_PLAIN_HOLD_BODY, None, None, False),
    0x4F: ("3", NOTE_CLASS_NORMAL, _BANK_FROM_SPECIAL, False),
    0x57: ("2", NOTE_CLASS_NORMAL, _BANK_FROM_PLAYER, True),
    0x5B: (_PLAIN_HOLD_BODY, None, None, False),
    0x5F: ("3", NOTE_CLASS_NORMAL, _BANK_FROM_PLAYER, True),
    0x63: ("1", NOTE_CLASS_BONUS, _BANK_FROM_PLAYER, False),
    0x67: ("4", NOTE_CLASS_BONUS, _BANK_FROM_SPECIAL, False),
    0x6B: (_PLAIN_HOLD_BODY, None, None, False),
    0x6F: ("3", NOTE_CLASS_BONUS, _BANK_FROM_SPECIAL, False),
    0x77: ("2", NOTE_CLASS_BONUS, _BANK_FROM_SPECIAL, False),
    0x7B: (_PLAIN_HOLD_BODY, None, None, False),
    0x7F: ("3", NOTE_CLASS_BONUS, _BANK_FROM_SPECIAL, False),
}

_ITEM_TABLE = {
    0x21: NOTE_CLASS_FAKE,
    0x41: NOTE_CLASS_BONUS,
    0x61: NOTE_CLASS_BONUS,
}

_ITEM_FALLBACK_CHAR = "p"
_ITEM_SPECIAL_BYTES = frozenset({0x42, 0x62})
_ITEM_SPECIAL_LAYER = "7"

_ITEM_WIDE_LAYERS = {17: "41f", 18: "82f"}

_MINE_CHAR = "M"

_DIFFICULTY_BY_NAME = {
    "PR": "Beginner",
    "NO": "Easy",
    "HD": "Hard",
    "CR": "Challenge",
    "NM": "Challenge",
    "FR": "Hard",
    "HF": "Hard",
}

SSC_DIFFICULTIES = ("Beginner", "Easy", "Medium", "Hard", "Challenge", "Edit")


class SscExportError(ValueError):
    """Raised when a document cannot be projected onto the SSC dialect at all."""


@dataclass(frozen=True, slots=True)
class SscDiagnostic:
    """One reportable deviation between the NX20 source and the SSC projection.

    Repeated deviations are collapsed into a single entry whose ``occurrences``
    counts them and whose location names the first one.
    """

    code: str
    message: str
    split_index: int | None = None
    block_index: int | None = None
    row_index: int | None = None
    lane: int | None = None
    occurrences: int = 1


@dataclass(frozen=True, slots=True)
class SscChart:
    """A single ``#NOTEDATA`` section ready to be rendered."""

    steps_type: str
    difficulty: str
    description: str
    meter: int
    credit: str
    offset: float
    bpms: str
    stops: str
    delays: str
    warps: str
    scrolls: str
    speeds: str
    notes: str
    noteskin_banks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SscSongInfo:
    """Song-level header fields for a standalone simfile."""

    title: str = ""
    subtitle: str = ""
    artist: str = ""
    credit: str = ""
    music: str = ""
    banner: str = ""
    background: str = ""
    sample_start: float = 0.0
    sample_length: float = 12.0


@dataclass(frozen=True, slots=True)
class SscExportReport:
    """The projected chart plus everything the projection could not preserve."""

    chart: SscChart
    diagnostics: tuple[SscDiagnostic, ...]

    @property
    def lossless(self) -> bool:
        return not self.diagnostics


class _ExportState:
    def __init__(self) -> None:
        self.banks: set[str] = set()
        self._order: list[tuple[str, str]] = []
        self._entries: dict[tuple[str, str], SscDiagnostic] = {}

    def note(
        self,
        code: str,
        message: str,
        split_index: int | None = None,
        block_index: int | None = None,
        row_index: int | None = None,
        lane: int | None = None,
    ) -> None:
        key = (code, message)
        existing = self._entries.get(key)
        if existing is None:
            self._order.append(key)
            self._entries[key] = SscDiagnostic(
                code, message, split_index, block_index, row_index, lane
            )
            return
        self._entries[key] = SscDiagnostic(
            existing.code,
            existing.message,
            existing.split_index,
            existing.block_index,
            existing.row_index,
            existing.lane,
            existing.occurrences + 1,
        )

    @property
    def diagnostics(self) -> list[SscDiagnostic]:
        return [self._entries[key] for key in self._order]


_MISSING = object()


def _bank_char(state: _ExportState, slot: int, where: tuple[int, int, int, int]) -> str:
    name = _BANK_SLOTS.get(slot, _MISSING)
    if name is _MISSING:
        state.note(
            "ssc.unknown-noteskin-bank",
            f"noteskin bank {slot} has no XSanity name; the note keeps the default skin",
            *where,
        )
        return "0"
    if name is None:
        return "0"
    state.banks.add(name)
    return _BANK_CHARS[name]


def _layer_char(
    state: _ExportState,
    note_class: int,
    layer: int,
    where: tuple[int, int, int, int],
) -> str:
    char = _LAYER_TABLES[note_class].get(layer)
    if char is None:
        state.note(
            "ssc.unknown-note-layer",
            f"layer byte {layer} has no XSanity display equivalent; the note keeps "
            "its scoring class and falls back to a normal display",
            *where,
        )
        return _LAYER_FALLBACK[note_class]
    return char


def _render_item(
    state: _ExportState,
    raw: bytes,
    where: tuple[int, int, int, int],
) -> str:
    kind, layer, slot, _ = raw
    if kind in _ITEM_SPECIAL_BYTES:
        char = _SPECIAL_CHARS.get(slot)
        if char is None:
            state.note(
                "ssc.unknown-special-item",
                f"special item {slot} has no XSanity equivalent and is dropped",
                *where,
            )
            return "0"
        return "{" + char + "0" + _ITEM_SPECIAL_LAYER + "}"

    note_class = _ITEM_TABLE.get(kind)
    if note_class is None:
        state.note(
            "ssc.unknown-item-note",
            f"item note byte 0x{kind:02X} has no XSanity equivalent and is dropped",
            *where,
        )
        return "0"

    char = _ITEM_CHARS.get(slot)
    if char is None:
        state.note(
            "ssc.unknown-item",
            f"item {slot} has no XSanity equivalent and is dropped",
            *where,
        )
        return "0"

    if kind == 0x41 and layer in _ITEM_WIDE_LAYERS:
        return "{" + char + "0" + _ITEM_WIDE_LAYERS[layer] + "}"

    layer_char = _LAYER_TABLES[note_class].get(layer)
    if layer_char is None:
        state.note(
            "ssc.unknown-item-layer",
            f"layer byte {layer} has no XSanity display equivalent for an item; "
            "the item is written as a generic pickup",
            *where,
        )
        return "{" + _ITEM_FALLBACK_CHAR + "0" + _LAYER_FALLBACK[note_class] + "}"
    return "{" + char + "0" + layer_char + "}"


def _render_cell(
    state: _ExportState,
    raw: bytes,
    brain_char: str,
    where: tuple[int, int, int, int],
) -> str:
    kind, layer, player, special = raw
    if kind == 0:
        return "0"

    if special == NOTE_ITEM_MARKER:
        return _render_item(state, raw, where)

    if kind == NOTE_BRAIN:
        head = "3"
        if special == NOTE_BRAIN_SPECIAL_CLEAR:
            head = "-"
        elif special == NOTE_BRAIN_SPECIAL_CROSS:
            head = "+"
        return "{" + head + brain_char + _LAYER_BRAIN + "}"

    entry = _NOTE_TABLE.get(kind)
    if entry is None:
        state.note(
            "ssc.unknown-note",
            f"note byte 0x{kind:02X} has no XSanity equivalent and is written as a mine",
            *where,
        )
        return _MINE_CHAR

    head, note_class, bank_source, brace_optional = entry
    if note_class is None:
        return head

    slot = player if bank_source == _BANK_FROM_PLAYER else special
    bank = _bank_char(state, slot, where)

    layer_char = _layer_char(state, note_class, layer, where)
    if brace_optional and layer_char == "0" and bank == "0":
        return head
    return "{" + head + bank + layer_char + "}"


def _brain_char(block: BlockSnapshot) -> str:
    for entry in block.divisions:
        if abs(_signed32(entry.meta_id)) != BRAIN_TRIGGER_SCORE:
            continue
        minimum = _signed16(entry.value & 0xFFFF)
        if abs(minimum) == 2:
            return "2"
        if abs(minimum) == 3:
            return "3"
    return "0"


def _signed32(value: int) -> int:
    return value - 0x100000000 if value & 0x80000000 else value


def _signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


_FROZEN_SMOOTH = (2, 3)


def _num(value: float) -> str:
    return f"{value:g}"


def _active_blocks(snapshot: AuthoringSnapshot) -> list[tuple[object, BlockSnapshot]]:
    return [
        (split, snapshot.active_block(split.stable_id))
        for split in snapshot.splits
        if split.blocks
    ]


def _row_cells(row: object, columns: int) -> list[bytes] | None:
    if isinstance(row, EmptyRow):
        return None
    if isinstance(row, (NoteRow, PackedNoteRow)):
        return [cell.raw for cell in row.cells]
    raise SscExportError("Lightmap rows have no SSC representation")


def _note_lines(
    snapshot: AuthoringSnapshot,
    columns: int,
    state: _ExportState,
) -> tuple[list[str], str]:
    blank = "0" * columns
    lines: list[str] = []
    for split_index, (_, block) in enumerate(_active_blocks(snapshot)):
        brain = _brain_char(block)
        for row_index, row in enumerate(block.rows):
            cells = _row_cells(row, columns)
            if cells is None:
                lines.append(blank)
                continue
            if len(cells) != columns:
                state.note(
                    "ssc.row-width-mismatch",
                    f"row holds {len(cells)} cells but the chart declares {columns} "
                    "columns; the row is padded or truncated",
                    split_index,
                    block.index,
                    row_index,
                )
            rendered = []
            for lane in range(columns):
                if lane >= len(cells):
                    rendered.append("0")
                    continue
                rendered.append(
                    _render_cell(
                        state,
                        cells[lane],
                        brain,
                        (split_index, block.index, row_index, lane),
                    )
                )
            lines.append("".join(rendered))
    return lines, blank


def _measures(lines: list[str], blank: str) -> str:
    padded = list(lines)
    padded.extend([blank] * (LINES_PER_MEASURE - (len(padded) % LINES_PER_MEASURE)))
    parts: list[str] = []
    total = len(padded) // LINES_PER_MEASURE
    for index in range(total):
        measure = padded[index * LINES_PER_MEASURE : (index + 1) * LINES_PER_MEASURE]
        if all(line == blank for line in measure):
            parts.append(blank + "\n")
        else:
            parts.append("\n".join(measure) + "\n")
        if index != total - 1:
            parts.append(",\n")
    return "".join(parts)


def _timing(
    snapshot: AuthoringSnapshot,
    state: _ExportState,
) -> tuple[str, str, str, str, str, str]:
    active = _active_blocks(snapshot)
    bpms: list[str] = []
    scrolls: list[str] = []
    speeds: list[str] = []
    warps: list[str] = []
    stops: list[str] = []
    delays: list[str] = []

    position = 0.0
    previous_speed = -99.0
    for index, (split, block) in enumerate(active):
        factor = block.beat_split / LINE_BEAT_SPLIT if block.beat_split else 0.0
        if not factor:
            state.note(
                "ssc.zero-beat-split",
                "Div has a zero Beat Split; its BPM is written as a frozen section",
                index,
                block.index,
            )

        if block.smooth_speed in _FROZEN_SMOOTH or not factor or block.bpm == 0.0:
            bpms.append(f"{_num(position)}={FROZEN_BPM},")
        else:
            bpms.append(f"{_num(position)}={_num(block.bpm * factor)},")

        if block.scroll == 0.0 or not factor:
            scrolls.append(f"{_num(position)}=0,")
        else:
            scrolls.append(f"{_num(position)}={_num(1.0 / factor)},")

        speed = abs(block.speed_or_freeze)
        if previous_speed != speed:
            if block.smooth_speed == 0:
                speeds.append(f"{_num(position)}={_num(speed)}=1=1,")
            else:
                length = block.row_count / LINE_BEAT_SPLIT
                speeds.append(f"{_num(position)}={_num(speed)}={_num(length)}=0,")
        previous_speed = speed

        if index:
            offset = split.blocks[0].offset_or_delay
            seconds = offset / 1000.0
            if block.speed_or_freeze > 0.0:
                if seconds > 0.0:
                    stops.append(f"{_num(position)}={_num(seconds)},")
            elif seconds > 0.0:
                delays.append(f"{_num(position)}={_num(seconds)},")
            if offset < 0.0:
                if block.bpm > 0.0:
                    beat_ms = int(60000.0 / block.bpm)
                    if beat_ms:
                        warp = (-offset / beat_ms) * factor
                        if warp > 0.0:
                            warps.append(f"{_num(position)}={_num(warp)},")
                else:
                    state.note(
                        "ssc.warp-without-bpm",
                        "Div starts before the previous one but has no usable BPM; "
                        "the warp is dropped",
                        index,
                        block.index,
                    )

        position += BEATS_PER_LINE * block.row_count

    return (
        "".join(bpms),
        "".join(stops),
        "".join(delays),
        "".join(warps),
        "".join(scrolls),
        "".join(speeds),
    )


def difficulty_for_name(name: str) -> str:
    """Return the XSanity difficulty slot conventionally implied by a chart filename."""

    stem = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    stem = stem.split(".", 1)[0].upper()
    return _DIFFICULTY_BY_NAME.get(stem, "Edit")


def _meter_from_metadata(document: NX20Document) -> int | None:
    meter = None
    for entry in document.header_metadata:
        if int(entry.meta_id.value) & 0xFFFF == 1001:
            meter = int(entry.value.value)
    return meter


def _is_mission(document: NX20Document) -> bool:
    return any(
        1100 <= (int(entry.meta_id.value) & 0xFFFF) <= 1103
        for entry in document.header_metadata
    )


def _credit_from_trailer(document: NX20Document) -> str:
    if _is_mission(document):
        return ""
    from stepnx.authoring.trailer import project_trailer_strings

    projection = project_trailer_strings(document)
    for entry in projection.strings:
        if entry.text:
            return entry.text
    return ""


def export_chart(
    document: NX20Document,
    *,
    description: str,
    difficulty: str | None = None,
    meter: int | None = None,
    credit: str | None = None,
    snapshot: AuthoringSnapshot | None = None,
) -> SscExportReport:
    """Project one NX20 document onto a single XSanity ``#NOTEDATA`` section.

    ``description`` names the chart inside the simfile and is also what the
    XSanity editor shows.  ``difficulty`` defaults to the slot implied by the
    description, ``meter`` to header metadata 1001, and ``credit`` to the first
    trailer string of a non-mission chart.  Only the branch selected in
    ``snapshot`` is written; pass a snapshot to choose branches explicitly.
    """

    if document.effective_lightmap:
        raise SscExportError("a Lightmap document has no SSC representation")

    columns = int(document.columns.value)
    steps_type = STEPS_TYPES.get(columns)
    if steps_type is None:
        raise SscExportError(f"{columns} columns have no XSanity StepsType")

    if snapshot is None:
        snapshot = create_authoring_snapshot(document)

    active = _active_blocks(snapshot)
    if not active:
        raise SscExportError("the document has no Div to export")

    state = _ExportState()
    lines, blank = _note_lines(snapshot, columns, state)
    bpms, stops, delays, warps, scrolls, speeds = _timing(snapshot, state)

    branches = sum(len(split.blocks) - 1 for split in snapshot.splits if split.blocks)
    if branches:
        state.note(
            "ssc.alternate-branches-dropped",
            f"{branches} alternate branch(es) have no SSC representation and are "
            "not written; only the selected branch of each Split is exported",
        )

    offset = -active[0][1].start_time / 1000.0
    if meter is None:
        meter = _meter_from_metadata(document)
    if credit is None:
        credit = _credit_from_trailer(document)

    chart = SscChart(
        steps_type=steps_type,
        difficulty=difficulty or difficulty_for_name(description),
        description=description,
        meter=meter if meter and meter > 0 else 1,
        credit=credit,
        offset=offset,
        bpms=bpms,
        stops=stops,
        delays=delays,
        warps=warps,
        scrolls=scrolls,
        speeds=speeds,
        notes=_measures(lines, blank),
        noteskin_banks=tuple(name for name in _BANK_ORDER if name in state.banks),
    )
    return SscExportReport(chart, tuple(state.diagnostics))


def _timing_tag(name: str, value: str) -> str:
    return f"#{name}:{value.replace(',', ',' + chr(10))};"


def _notedata_lines(chart: SscChart) -> list[str]:
    lines = [
        "#NOTEDATA:;",
        f"#STEPSTYPE:{chart.steps_type};",
        f"#DESCRIPTION:{chart.description};",
        f"#DIFFICULTY:{chart.difficulty};",
        f"#METER:{chart.meter};",
    ]
    if chart.credit:
        lines.append(f"#CREDIT:{chart.credit};")
    lines.append(f"#OFFSET:{_num(chart.offset)};")
    if chart.noteskin_banks:
        lines.append("#PRELOADNOTESKIN:" + ",".join(chart.noteskin_banks) + ";")
    lines.append(_timing_tag("BPMS", chart.bpms))
    lines.append(_timing_tag("STOPS", chart.stops))
    lines.append(_timing_tag("DELAYS", chart.delays))
    lines.append(_timing_tag("WARPS", chart.warps))
    lines.append(_timing_tag("SCROLLS", chart.scrolls))
    lines.append(_timing_tag("SPEEDS", chart.speeds))
    lines.append("#NOTES:\n" + chart.notes + ";")
    return lines


def render_extension(chart: SscChart, song_tag: str) -> str:
    """Render one chart as an ``.ssc.ext`` companion file for an existing song.

    ``song_tag`` is the ``group/song`` folder pair the extension attaches to,
    exactly as XSanity writes it into ``#SONG``.
    """

    lines = [
        f"#VERSION:{SSC_VERSION} {SSC_EXTENSION_HEADER};",
        f"#SONG:{song_tag};",
        "",
        f"//----------- (NX) {chart.description} ---------",
    ]
    lines.extend(_notedata_lines(chart))
    return "\n".join(lines) + "\n"


def render_simfile(charts: list[SscChart], song: SscSongInfo) -> str:
    """Render a standalone ``.ssc`` simfile holding every given chart."""

    if not charts:
        raise SscExportError("a simfile needs at least one chart")

    lines = [
        f"#VERSION:{SSC_VERSION} {SSC_HEADER};",
        f"#TITLE:{song.title};",
        f"#SUBTITLE:{song.subtitle};",
        f"#ARTIST:{song.artist};",
        "#TITLETRANSLIT:;",
        "#SUBTITLETRANSLIT:;",
        "#ARTISTTRANSLIT:;",
        "#GENRE:;",
        "#ORIGIN:;",
        f"#CREDIT:{song.credit};",
        f"#BANNER:{song.banner};",
        f"#BACKGROUND:{song.background};",
        "#CDTITLE:;",
        f"#MUSIC:{song.music};",
        f"#OFFSET:{_num(charts[0].offset)};",
        f"#SAMPLESTART:{_num(song.sample_start)};",
        f"#SAMPLELENGTH:{_num(song.sample_length)};",
        "#SELECTABLE:YES;",
        _timing_tag("BPMS", charts[0].bpms),
        "#STOPS:;",
        "#DELAYS:;",
        "#WARPS:;",
        "#BGCHANGES:;",
        "#KEYSOUNDS:;",
        "#ATTACKS:;",
    ]
    for chart in charts:
        lines.append("")
        lines.append(
            f"//--------------- {chart.steps_type} - {chart.description} ----------------"
        )
        lines.extend(_notedata_lines(chart))
    return "\n".join(lines) + "\n"
