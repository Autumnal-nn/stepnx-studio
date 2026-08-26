from __future__ import annotations

from dataclasses import replace

from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import EmptyRow, LightmapRow, NoteCell, NoteRow, PackedNoteRow


# Values are structural coordinates only, never object references. The cache is
# therefore safe across immutable note-edit document snapshots. Every hit is
# validated against the current document before use; structure edits that move
# a row simply cause a rebuild on the next access.
_ROW_LOCATIONS: dict[tuple[object, ...], dict[int, tuple[int, int, int]]] = {}


def _document_key(document) -> tuple[object, ...]:
    return (
        document.source_name,
        document.stable_id,
        int(document.columns.value),
        len(document.splits),
    )


def _build_row_locations(document) -> dict[int, tuple[int, int, int]]:
    locations: dict[int, tuple[int, int, int]] = {}
    for split_index, split in enumerate(document.splits):
        for block_index, block in enumerate(split.blocks):
            for row_index, row in enumerate(block.rows):
                locations[row.stable_id] = (split_index, block_index, row_index)
    _ROW_LOCATIONS[_document_key(document)] = locations
    return locations


def _cached_location(document, row_id: int) -> tuple[int, int, int] | None:
    locations = _ROW_LOCATIONS.get(_document_key(document))
    location = None if locations is None else locations.get(row_id)
    if location is None:
        return None
    split_index, block_index, row_index = location
    try:
        row = document.splits[split_index].blocks[block_index].rows[row_index]
    except IndexError:
        return None
    return location if row.stable_id == row_id else None


def _locate_row(document, row_id: int) -> tuple[int, int, int]:
    location = _cached_location(document, row_id)
    if location is not None:
        return location
    locations = _build_row_locations(document)
    try:
        return locations[row_id]
    except KeyError as exc:
        raise ModelInvariantError(f"row stable ID {row_id} was not found") from exc


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


class _FastSetNoteAt:
    """Interactive SetNoteAt using a validated row-location index.

    The public/core SetNoteAt deliberately remains generic and search-based.
    This adapter is installed only into the Phase10 interactive layer, where
    mouse hit-testing already gives us a stable row identity and latency matters.
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

        rows = list(block.rows)
        rows[row_index] = replacement
        block = replace(block, rows=tuple(rows))
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
