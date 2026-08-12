from __future__ import annotations

from dataclasses import dataclass

from stepnx.authoring.tools import NoteFunction, NoteVisibility, apply_note_modifiers
from stepnx.core.commands import NoteEdit, SetNotesAt
from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import (
    EmptyRow,
    LightmapRow,
    NoteRow,
    NX20Document,
    PackedNoteRow,
)


@dataclass(frozen=True, order=True, slots=True)
class CellTarget:
    row_id: int
    lane: int


@dataclass(frozen=True, slots=True)
class CellSelection:
    targets: frozenset[CellTarget] = frozenset()
    anchor: CellTarget | None = None

    def replace(self, target: CellTarget) -> CellSelection:
        return CellSelection(frozenset((target,)), target)

    def toggle(self, target: CellTarget) -> CellSelection:
        targets = set(self.targets)
        if target in targets:
            targets.remove(target)
        else:
            targets.add(target)
        return CellSelection(frozenset(targets), target)

    def clear(self) -> CellSelection:
        return CellSelection()

    def rectangle(
        self,
        ordered_row_ids: tuple[int, ...],
        target: CellTarget,
    ) -> CellSelection:
        anchor = self.anchor or target
        try:
            first = ordered_row_ids.index(anchor.row_id)
            last = ordered_row_ids.index(target.row_id)
        except ValueError as exc:
            raise ValueError("rectangular selection must stay in one Block") from exc
        row_start, row_end = sorted((first, last))
        lane_start, lane_end = sorted((anchor.lane, target.lane))
        targets = frozenset(
            CellTarget(row_id, lane)
            for row_id in ordered_row_ids[row_start : row_end + 1]
            for lane in range(lane_start, lane_end + 1)
        )
        return CellSelection(targets, anchor)


@dataclass(frozen=True, slots=True)
class NoteClipboard:
    width: int
    height: int
    cells: tuple[tuple[int, int, bytes], ...]

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or not self.cells:
            raise ValueError("note clipboard cannot be empty")


def _raw_at(document: NX20Document, target: CellTarget) -> bytes:
    matches = []
    for split in document.splits:
        for block in split.blocks:
            for row in block.rows:
                if row.stable_id != target.row_id:
                    continue
                if not 0 <= target.lane < int(document.columns.value):
                    raise ModelInvariantError(
                        f"lane {target.lane} is outside the document"
                    )
                if isinstance(row, (EmptyRow, LightmapRow)):
                    if isinstance(row, LightmapRow):
                        raise ModelInvariantError("note operations cannot edit Lightmap rows")
                    matches.append(b"\x00\x00\x00\x00")
                elif isinstance(row, PackedNoteRow):
                    matches.append(row.cell(target.lane).raw)
                elif isinstance(row, NoteRow):
                    matches.append(row.cells[target.lane].raw)
    if len(matches) != 1:
        raise ModelInvariantError(
            f"expected one row with stable ID {target.row_id}, found {len(matches)}"
        )
    return matches[0]


def set_selection_raw(selection: CellSelection, raw: bytes) -> SetNotesAt:
    if not selection.targets:
        raise ValueError("a bulk edit requires a non-empty selection")
    return SetNotesAt(
        tuple(NoteEdit(target.row_id, target.lane, raw) for target in sorted(selection.targets))
    )


def modify_selection_notes(
    document: NX20Document,
    selection: CellSelection,
    functionality: NoteFunction,
    visibility: NoteVisibility,
) -> SetNotesAt:
    """Apply StepEdit-style H/G and visibility modes without replacing notes.

    Division cells are excluded because bit 0x20 has division-trigger semantics
    there rather than the normal-note no-combo-break meaning.
    """
    if not selection.targets:
        raise ValueError("a bulk edit requires a non-empty selection")

    targets_by_row: dict[int, set[int]] = {}
    for target in selection.targets:
        targets_by_row.setdefault(target.row_id, set()).add(target.lane)

    rows: dict[int, object] = {}
    for split in document.splits:
        for block in split.blocks:
            for row in block.rows:
                if row.stable_id in targets_by_row:
                    rows[row.stable_id] = row

    edits = []
    columns = int(document.columns.value)
    for row_id, lanes in targets_by_row.items():
        row = rows.get(row_id)
        if row is None:
            raise ModelInvariantError(f"row with stable ID {row_id} was not found")
        if isinstance(row, LightmapRow):
            raise ModelInvariantError("note operations cannot edit Lightmap rows")
        for lane in sorted(lanes):
            if not 0 <= lane < columns:
                raise ModelInvariantError(f"lane {lane} is outside the document")
            if isinstance(row, EmptyRow):
                raw = b"\x00\x00\x00\x00"
            elif isinstance(row, PackedNoteRow):
                raw = row.cell(lane).raw
            else:
                raw = row.cells[lane].raw

            # NX note-like cells use odd low-nibble types.  This includes the
            # less common 5/9/D hold variants found in real charts.  Empty
            # cells and Division triggers (type 2) must never receive H/G.
            if not (raw[0] & 0x01):
                continue
            edits.append(
                NoteEdit(
                    row_id,
                    lane,
                    apply_note_modifiers(raw, functionality, visibility),
                )
            )
    if not edits:
        raise ValueError("selection contains no editable notes")
    return SetNotesAt(tuple(edits))


def mirror_selection(
    document: NX20Document, selection: CellSelection
) -> tuple[SetNotesAt, CellSelection]:
    if not selection.targets:
        raise ValueError("mirror requires a non-empty selection")
    columns = int(document.columns.value)
    mirrored = {
        CellTarget(target.row_id, columns - 1 - target.lane): _raw_at(document, target)
        for target in selection.targets
    }
    original = set(selection.targets)
    destinations = set(mirrored)
    edits = [
        NoteEdit(target.row_id, target.lane, b"\x00\x00\x00\x00")
        for target in sorted(original - destinations)
    ]
    edits.extend(
        NoteEdit(target.row_id, target.lane, raw)
        for target, raw in sorted(mirrored.items())
    )
    new_anchor = None
    if selection.anchor is not None:
        new_anchor = CellTarget(
            selection.anchor.row_id, columns - 1 - selection.anchor.lane
        )
    return SetNotesAt(tuple(edits)), CellSelection(frozenset(destinations), new_anchor)


def _block_rows_for_target(
    document: NX20Document, target: CellTarget
) -> tuple[object, tuple[int, ...], int]:
    matches = []
    for split in document.splits:
        for block in split.blocks:
            row_ids = tuple(row.stable_id for row in block.rows)
            if target.row_id in row_ids:
                matches.append((block, row_ids, row_ids.index(target.row_id)))
    if len(matches) != 1:
        raise ModelInvariantError(
            f"expected one Block containing row {target.row_id}, found {len(matches)}"
        )
    return matches[0]


def copy_selection(document: NX20Document, selection: CellSelection) -> NoteClipboard:
    if not selection.targets:
        raise ValueError("copy requires a non-empty selection")
    ordered = sorted(selection.targets)
    _, row_ids, _ = _block_rows_for_target(document, ordered[0])
    try:
        row_indexes = [row_ids.index(target.row_id) for target in ordered]
    except ValueError as exc:
        raise ValueError("copy selection cannot cross Block boundaries") from exc
    if any(target.row_id not in row_ids for target in ordered):
        raise ValueError("copy selection cannot cross Block boundaries")
    first_row = min(row_indexes)
    first_lane = min(target.lane for target in ordered)
    cells = tuple(
        (
            row_ids.index(target.row_id) - first_row,
            target.lane - first_lane,
            _raw_at(document, target),
        )
        for target in ordered
    )
    return NoteClipboard(
        max(target.lane for target in ordered) - first_lane + 1,
        max(row_indexes) - first_row + 1,
        cells,
    )


def paste_clipboard(
    document: NX20Document, clipboard: NoteClipboard, anchor: CellTarget
) -> tuple[SetNotesAt, CellSelection]:
    _, row_ids, anchor_row = _block_rows_for_target(document, anchor)
    columns = int(document.columns.value)
    if anchor.lane + clipboard.width > columns:
        raise ValueError("paste would cross the document's lane boundary")
    if anchor_row + clipboard.height > len(row_ids):
        raise ValueError("paste would cross the Block boundary")
    edits = []
    targets = set()
    for row_offset, lane_offset, raw in clipboard.cells:
        target = CellTarget(
            row_ids[anchor_row + row_offset], anchor.lane + lane_offset
        )
        edits.append(NoteEdit(target.row_id, target.lane, raw))
        targets.add(target)
    return SetNotesAt(tuple(edits)), CellSelection(frozenset(targets), anchor)


def replace_selection_type(
    document: NX20Document,
    selection: CellSelection,
    note_type: int,
    replacement: bytes,
) -> SetNotesAt:
    if not 0 <= note_type <= 0x0F:
        raise ValueError("note type must be between 0 and 15")
    edits = tuple(
        NoteEdit(target.row_id, target.lane, replacement)
        for target in sorted(selection.targets)
        if _raw_at(document, target)[0] & 0x0F == note_type
    )
    if not edits:
        raise ValueError("no selected cell matches that note type")
    return SetNotesAt(edits)
