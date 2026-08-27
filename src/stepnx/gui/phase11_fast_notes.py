from __future__ import annotations

from bisect import bisect_left
from dataclasses import replace

from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import (
    CompactRows,
    EmptyRow,
    LightmapRow,
    NoteCell,
    NoteRow,
    OverlayRows,
    PackedNoteRow,
)


_ACTIVE_BLOCK_ID: int | None = None


def _compact_row_index(rows: CompactRows, row_id: int) -> int | None:
    # CompactRows allocates stable IDs monotonically. Cell IDs may appear
    # between row IDs, so a range test alone is insufficient; binary-search the
    # parser's row-id table and verify an exact match without materializing rows.
    index = bisect_left(rows._row_ids, row_id)
    if index < len(rows._row_ids) and int(rows._row_ids[index]) == row_id:
        return index
    return None


def _row_index(rows, row_id: int) -> int | None:
    if isinstance(rows, CompactRows):
        return _compact_row_index(rows, row_id)
    if isinstance(rows, OverlayRows):
        # Overlay replacements preserve the row's stable identity, so the base
        # compact index remains valid after arbitrarily many sparse note edits.
        return _compact_row_index(rows.base, row_id)
    for index, row in enumerate(rows):
        if row.stable_id == row_id:
            return index
    return None


def _locate_row(
    document,
    row_id: int,
    block_hint: int | None = None,
) -> tuple[int, int, int]:
    hint = _ACTIVE_BLOCK_ID if block_hint is None else block_hint
    if hint is not None:
        for split_index, split in enumerate(document.splits):
            for block_index, block in enumerate(split.blocks):
                if block.stable_id != hint:
                    continue
                row_index = _row_index(block.rows, row_id)
                if row_index is not None:
                    return split_index, block_index, row_index
                break

    # Fallback for direct/test use or after an unexpected structure change.
    # Compact/overlay Blocks still use O(log rows) lookup and never materialize
    # their row tables during this search.
    for split_index, split in enumerate(document.splits):
        for block_index, block in enumerate(split.blocks):
            row_index = _row_index(block.rows, row_id)
            if row_index is not None:
                return split_index, block_index, row_index
    raise ModelInvariantError(f"row stable ID {row_id} was not found")


def _fast_find_row(document, row_id: int):
    try:
        split_index, block_index, row_index = _locate_row(document, row_id)
    except ModelInvariantError:
        return None
    split = document.splits[split_index]
    block = split.blocks[block_index]
    return split, block, row_index, block.rows[row_index]


def _rich_cells(row) -> list[NoteCell]:
    if isinstance(row, NoteRow):
        return list(row.cells)
    if isinstance(row, PackedNoteRow):
        return list(row.cells)
    raise ModelInvariantError("row is not a playable note row")


def _replace_one_row(rows, row_index: int, replacement):
    if isinstance(rows, (CompactRows, OverlayRows)):
        return rows.with_row(row_index, replacement)
    edited = list(rows)
    edited[row_index] = replacement
    return tuple(edited)


def _cells_for_empty_overlay_row(rows, row_index: int) -> list[NoteCell] | None:
    """Recover original cell identities when an overlay note row was cleared.

    OverlayRows deliberately keep a CompactRows base so sparse edits stay cheap.
    If a packed note row is replaced by EmptyRow and then receives a note again,
    allocating fresh IDs would make the replacement disagree with the base row's
    stable cell identities. The validator correctly rejects that state. Reuse the
    base PackedNoteRow cells instead.
    """

    if not isinstance(rows, OverlayRows):
        return None
    original = rows.base[row_index]
    if isinstance(original, PackedNoteRow):
        return list(original.cells)
    return None


class _FastSetNoteAt:
    """Interactive SetNoteAt with Block hinting and sparse row replacement.

    The public/core SetNoteAt deliberately remains generic and search-based.
    This adapter is installed only into the Phase10 interactive layer, where
    mouse hit-testing already gives us a Block identity and latency matters.
    """

    def __init__(self, row_id: int, lane: int, raw: bytes):
        self.row_id = int(row_id)
        self.lane = int(lane)
        self.raw = bytes(raw)

    def apply(self, document):
        if len(self.raw) != 4:
            raise ModelInvariantError("a note cell must contain exactly four bytes")
        columns = int(document.columns.value)
        if not 0 <= self.lane < columns:
            raise ModelInvariantError(
                f"lane {self.lane} is outside the document's {columns} columns"
            )

        split_index, block_index, row_index = _locate_row(document, self.row_id)
        split = document.splits[split_index]
        block = split.blocks[block_index]
        row = block.rows[row_index]
        if isinstance(row, LightmapRow):
            raise ModelInvariantError("note tools cannot edit a Lightmap row")

        next_id = document.next_stable_id
        if isinstance(row, EmptyRow):
            if self.raw == b"\0\0\0\0":
                return document
            cells = _cells_for_empty_overlay_row(block.rows, row_index)
            if cells is None:
                cells = [
                    NoteCell(next_id + index, b"\0\0\0\0", None)
                    for index in range(columns)
                ]
                next_id += columns
        else:
            cells = _rich_cells(row)
            if len(cells) != columns:
                raise ModelInvariantError(
                    f"row {self.row_id} has {len(cells)} cells, expected {columns}"
                )

        cell = cells[self.lane]
        cells[self.lane] = NoteCell(cell.stable_id, self.raw, None)
        if all(item.raw == b"\0\0\0\0" for item in cells):
            replacement = EmptyRow(self.row_id, b"\x80\0\0\0", None)
        else:
            replacement = NoteRow(self.row_id, tuple(cells), None)

        block = replace(
            block,
            rows=_replace_one_row(block.rows, row_index, replacement),
        )
        blocks = list(split.blocks)
        blocks[block_index] = block
        split = replace(split, blocks=tuple(blocks))
        splits = list(document.splits)
        splits[split_index] = split
        return replace(
            document,
            splits=tuple(splits),
            next_stable_id=next_id,
        )


def install_phase11_fast_note_index(window) -> None:
    if getattr(window, "_phase11_fast_note_index_installed", False):
        return
    window._phase11_fast_note_index_installed = True

    import stepnx.gui.phase10_install as phase10_module

    phase10_module._find_row = _fast_find_row
    phase10_module.SetNoteAt = _FastSetNoteAt

    # Keep the Block identity from timeline hit-testing alive for the complete
    # click/hold transaction, including SequenceCommand erase/hold operations.
    original_click = window._phase10_click
    original_hold = window._phase10_hold

    def indexed_click(widget, hit):
        global _ACTIVE_BLOCK_ID
        previous = _ACTIVE_BLOCK_ID
        _ACTIVE_BLOCK_ID = hit[0].block.stable_id
        try:
            return original_click(widget, hit)
        finally:
            _ACTIVE_BLOCK_ID = previous

    def indexed_hold(widget, start, end):
        global _ACTIVE_BLOCK_ID
        previous = _ACTIVE_BLOCK_ID
        _ACTIVE_BLOCK_ID = start[0].block.stable_id
        try:
            return original_hold(widget, start, end)
        finally:
            _ACTIVE_BLOCK_ID = previous

    window._phase10_click = indexed_click
    window._phase10_hold = indexed_hold
