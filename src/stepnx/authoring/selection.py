from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass

from stepnx.authoring.tools import NoteFunction, NoteVisibility, apply_note_modifiers
from stepnx.core.commands import NoteEdit, SetNotesAt
from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import (
    Block,
    CompactRows,
    EmptyRow,
    LightmapRow,
    NoteRow,
    NX20Document,
    OverlayRows,
    PackedNoteRow,
    Row,
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


@dataclass(frozen=True, slots=True)
class _SelectionRectangle:
    block: Block
    rows: Sequence[Row]
    row_ids: tuple[int, ...]
    lanes: tuple[int, ...]


def _compact_row_index(rows: CompactRows | OverlayRows, row_id: int) -> int | None:
    base = rows.base if isinstance(rows, OverlayRows) else rows
    index = bisect_left(base._row_ids, row_id)
    if index < len(base) and int(base._row_ids[index]) == row_id:
        return index
    return None


def _locate_rows(
    document: NX20Document, row_ids: set[int]
) -> dict[int, tuple[Block, Sequence[Row], int, Row]]:
    matches: dict[int, list[tuple[Block, Sequence[Row], int, Row]]] = {
        row_id: [] for row_id in row_ids
    }
    for split in document.splits:
        for block in split.blocks:
            if isinstance(block.rows, (CompactRows, OverlayRows)):
                for row_id in row_ids:
                    index = _compact_row_index(block.rows, row_id)
                    if index is not None:
                        matches[row_id].append(
                            (block, block.rows, index, block.rows[index])
                        )
                continue
            for index, row in enumerate(block.rows):
                if row.stable_id in matches:
                    matches[row.stable_id].append((block, block.rows, index, row))
    located = {}
    for row_id, candidates in matches.items():
        if len(candidates) != 1:
            raise ModelInvariantError(
                f"expected one row with stable ID {row_id}, found {len(candidates)}"
            )
        located[row_id] = candidates[0]
    return located


def _raw_from_row(document: NX20Document, row: Row, lane: int) -> bytes:
    if not 0 <= lane < int(document.columns.value):
        raise ModelInvariantError(f"lane {lane} is outside the document")
    if isinstance(row, LightmapRow):
        raise ModelInvariantError("note operations cannot edit Lightmap rows")
    if isinstance(row, EmptyRow):
        return b"\x00\x00\x00\x00"
    if isinstance(row, PackedNoteRow):
        return row.cell(lane).raw
    return row.cells[lane].raw


def set_selection_raw(selection: CellSelection, raw: bytes) -> SetNotesAt:
    if not selection.targets:
        raise ValueError("a bulk edit requires a non-empty selection")
    return SetNotesAt(
        tuple(NoteEdit(target.row_id, target.lane, raw) for target in sorted(selection.targets))
    )


def cut_selection(
    document: NX20Document, selection: CellSelection
) -> tuple[NoteClipboard, SetNotesAt]:
    clipboard = copy_selection(document, selection)
    return clipboard, set_selection_raw(selection, b"\x00\x00\x00\x00")


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

    rows = {
        row_id: result[3]
        for row_id, result in _locate_rows(document, set(targets_by_row)).items()
    }

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
            raw = _raw_from_row(document, row, lane)

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


def _selection_rectangle(
    document: NX20Document, selection: CellSelection
) -> _SelectionRectangle:
    if not selection.targets:
        raise ValueError("a transform requires a non-empty selection")
    located = _locate_rows(document, {target.row_id for target in selection.targets})
    block_ids = {located[target.row_id][0].stable_id for target in selection.targets}
    if len(block_ids) != 1:
        raise ValueError("a transform selection cannot cross Block boundaries")

    row_indexes = sorted({located[target.row_id][2] for target in selection.targets})
    if row_indexes != list(range(row_indexes[0], row_indexes[-1] + 1)):
        raise ValueError("a transform requires contiguous rows")
    rows = located[next(iter(selection.targets)).row_id][1]
    row_ids = tuple(rows[index].stable_id for index in row_indexes)

    lanes = tuple(sorted({target.lane for target in selection.targets}))
    if lanes != tuple(range(lanes[0], lanes[-1] + 1)):
        raise ValueError("a transform requires contiguous columns")
    expected = frozenset(
        CellTarget(row_id, lane) for row_id in row_ids for lane in lanes
    )
    if selection.targets != expected:
        raise ValueError("a transform requires a rectangular selection")
    return _SelectionRectangle(
        located[row_ids[0]][0],
        rows,
        row_ids,
        lanes,
    )


def _transform_selection(
    document: NX20Document,
    selection: CellSelection,
    destination,
) -> tuple[SetNotesAt, CellSelection]:
    rectangle = _selection_rectangle(document, selection)
    located = _locate_rows(document, set(rectangle.row_ids))
    transformed: dict[CellTarget, bytes] = {}
    target_map: dict[CellTarget, CellTarget] = {}
    for row_position, row_id in enumerate(rectangle.row_ids):
        row = located[row_id][3]
        for lane_position, lane in enumerate(rectangle.lanes):
            source = CellTarget(row_id, lane)
            target_row, target_lane = destination(row_position, lane_position)
            target = CellTarget(
                rectangle.row_ids[target_row], rectangle.lanes[target_lane]
            )
            transformed[target] = _raw_from_row(document, row, lane)
            target_map[source] = target
    if len(transformed) != len(selection.targets):
        raise ModelInvariantError("selection transform is not a bijection")
    edits = tuple(
        NoteEdit(target.row_id, target.lane, raw)
        for target, raw in sorted(transformed.items())
    )
    anchor = target_map.get(selection.anchor) if selection.anchor is not None else None
    return SetNotesAt(edits), CellSelection(selection.targets, anchor)


def flip_horizontal_selection(
    document: NX20Document, selection: CellSelection
) -> tuple[SetNotesAt, CellSelection]:
    rectangle = _selection_rectangle(document, selection)
    lane_count = len(rectangle.lanes)
    return _transform_selection(
        document,
        selection,
        lambda row, lane: (row, lane_count - 1 - lane),
    )


def flip_vertical_selection(
    document: NX20Document, selection: CellSelection
) -> tuple[SetNotesAt, CellSelection]:
    rectangle = _selection_rectangle(document, selection)
    row_count = len(rectangle.row_ids)
    return _transform_selection(
        document,
        selection,
        lambda row, lane: (row_count - 1 - row, lane),
    )


def mirror_selection(
    document: NX20Document, selection: CellSelection
) -> tuple[SetNotesAt, CellSelection]:
    rectangle = _selection_rectangle(document, selection)
    columns = int(document.columns.value)
    lanes = rectangle.lanes
    if len(lanes) == 5 and (
        (columns == 5 and lanes == tuple(range(5)))
        or (columns == 10 and lanes in (tuple(range(5)), tuple(range(5, 10))))
    ):
        permutation = (3, 4, 2, 0, 1)
    elif columns == 6 and lanes == tuple(range(6)):
        permutation = (5, 3, 4, 1, 2, 0)
    elif columns == 10 and lanes == tuple(range(10)):
        permutation = (8, 9, 7, 5, 6, 3, 4, 2, 0, 1)
    else:
        raise ValueError(
            "Mirror requires all 5 Single columns, either 5-column pad or all "
            "10 Double columns, or all 6 Half Double columns"
        )
    return _transform_selection(
        document,
        selection,
        lambda row, lane: (row, permutation[lane]),
    )


def _block_rows_for_target(
    document: NX20Document, target: CellTarget
) -> tuple[Block, Sequence[Row], int]:
    block, rows, index, _ = _locate_rows(document, {target.row_id})[target.row_id]
    return block, rows, index


def copy_selection(document: NX20Document, selection: CellSelection) -> NoteClipboard:
    if not selection.targets:
        raise ValueError("copy requires a non-empty selection")
    ordered = sorted(selection.targets)
    located = _locate_rows(document, {target.row_id for target in ordered})
    block_ids = {located[target.row_id][0].stable_id for target in ordered}
    if len(block_ids) != 1:
        raise ValueError("copy selection cannot cross Block boundaries")
    row_indexes = [located[target.row_id][2] for target in ordered]
    first_row = min(row_indexes)
    first_lane = min(target.lane for target in ordered)
    cells = tuple(
        (
            located[target.row_id][2] - first_row,
            target.lane - first_lane,
            _raw_from_row(document, located[target.row_id][3], target.lane),
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
    _, rows, anchor_row = _block_rows_for_target(document, anchor)
    columns = int(document.columns.value)
    if anchor.lane + clipboard.width > columns:
        raise ValueError("paste would cross the document's lane boundary")
    if anchor_row + clipboard.height > len(rows):
        raise ValueError("paste would cross the Block boundary")
    edits = []
    targets = set()
    for row_offset, lane_offset, raw in clipboard.cells:
        target = CellTarget(
            rows[anchor_row + row_offset].stable_id, anchor.lane + lane_offset
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
    located = _locate_rows(document, {target.row_id for target in selection.targets})
    edits = tuple(
        NoteEdit(target.row_id, target.lane, replacement)
        for target in sorted(selection.targets)
        if _raw_from_row(document, located[target.row_id][3], target.lane)[0] & 0x0F
        == note_type
    )
    if not edits:
        raise ValueError("no selected cell matches that note type")
    return SetNotesAt(edits)
