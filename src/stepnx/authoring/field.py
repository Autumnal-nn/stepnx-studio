from __future__ import annotations

from dataclasses import dataclass, replace

from stepnx.core.errors import ModelInvariantError
from stepnx.core.model import (
    Block,
    EmptyRow,
    LightmapRow,
    NoteCell,
    NoteRow,
    NX20Document,
    PackedNoteRow,
    Split,
)
from stepnx.core.scalars import RawU32


@dataclass(frozen=True, slots=True)
class FieldGeometry:
    """Physical lane window encoded by the NX20 document header."""

    start_column: int
    columns: int

    def __post_init__(self) -> None:
        start = int(self.start_column)
        columns = int(self.columns)
        if not 0 <= start <= 63:
            raise ValueError("Start Column must be between 0 and 63")
        if not 1 <= columns <= 64:
            raise ValueError("Columns must be between 1 and 64")
        if start + columns > 64:
            raise ValueError("Start Column + Columns must not exceed 64")

    @property
    def stop_column(self) -> int:
        return int(self.start_column) + int(self.columns)

    @classmethod
    def single(cls) -> FieldGeometry:
        return cls(0, 5)

    @classmethod
    def double(cls) -> FieldGeometry:
        return cls(0, 10)

    @classmethod
    def half_double(cls) -> FieldGeometry:
        return cls(2, 6)


FIELD_PRESETS: tuple[tuple[str, FieldGeometry], ...] = (
    ("Single", FieldGeometry.single()),
    ("Double", FieldGeometry.double()),
    ("Half Double", FieldGeometry.half_double()),
)


def current_field(document: NX20Document) -> FieldGeometry:
    return FieldGeometry(int(document.start_column.value), int(document.columns.value))


def _row_cells(row: NoteRow | PackedNoteRow) -> tuple[NoteCell, ...]:
    return row.cells


def count_dropped_nonempty_cells(
    document: NX20Document,
    geometry: FieldGeometry,
) -> int:
    """Count note cells that would fall outside a new physical lane window."""

    if document.effective_lightmap:
        return 0
    old = current_field(document)
    if old == geometry:
        return 0
    retained = range(int(geometry.start_column), geometry.stop_column)
    retained_set = set(retained)
    dropped = 0
    for split in document.splits:
        for block in split.blocks:
            for row in block.rows:
                if isinstance(row, EmptyRow):
                    continue
                if isinstance(row, LightmapRow):
                    raise ModelInvariantError(
                        "normal chart contains a Lightmap row while changing field geometry"
                    )
                for lane, cell in enumerate(_row_cells(row)):
                    absolute = int(old.start_column) + lane
                    if absolute not in retained_set and any(cell.raw):
                        dropped += 1
    return dropped


@dataclass(frozen=True, slots=True)
class SetChartField:
    """Change Start Column/Columns while preserving notes by physical panel.

    Existing cells are mapped through their absolute panel index. Expanding a
    field inserts zero cells; shrinking a field refuses to discard nonzero cells
    unless ``allow_note_loss`` is explicitly enabled by the caller.
    """

    geometry: FieldGeometry
    allow_note_loss: bool = False

    def apply(self, document: NX20Document) -> NX20Document:
        if document.effective_lightmap:
            raise ModelInvariantError(
                "Lightmap geometry is fixed; edit a chart document instead of LM.NX"
            )
        # columns == 3 is an NX20 Lightmap discriminator in the canonical model.
        # Do not silently convert an ordinary note chart into the Lightmap row codec.
        if int(self.geometry.columns) == 3:
            raise ValueError(
                "Columns = 3 is reserved for NX20 Lightmap geometry"
            )

        old = current_field(document)
        if old == self.geometry:
            return document

        dropped = count_dropped_nonempty_cells(document, self.geometry)
        if dropped and not self.allow_note_loss:
            raise ModelInvariantError(
                f"field change would discard {dropped} non-empty note cell(s)"
            )

        next_id = int(document.next_stable_id)

        def new_zero_cell() -> NoteCell:
            nonlocal next_id
            cell = NoteCell(next_id, b"\x00\x00\x00\x00", None)
            next_id += 1
            return cell

        def remap_row(row):
            if isinstance(row, EmptyRow):
                return row
            if isinstance(row, LightmapRow):
                raise ModelInvariantError(
                    "normal chart contains a Lightmap row while changing field geometry"
                )

            source = {
                int(old.start_column) + lane: cell
                for lane, cell in enumerate(_row_cells(row))
            }
            cells: list[NoteCell] = []
            for absolute in range(
                int(self.geometry.start_column), self.geometry.stop_column
            ):
                cell = source.get(absolute)
                if cell is None:
                    cells.append(new_zero_cell())
                else:
                    cells.append(replace(cell, span=None))

            if not any(any(cell.raw) for cell in cells):
                return EmptyRow(row.stable_id, b"\x80\x00\x00\x00", None)
            return NoteRow(row.stable_id, tuple(cells), None)

        splits: list[Split] = []
        for split in document.splits:
            blocks: list[Block] = []
            for block in split.blocks:
                rows = tuple(remap_row(row) for row in block.rows)
                blocks.append(replace(block, rows=rows, span=None))
            splits.append(replace(split, blocks=tuple(blocks), span=None))

        return replace(
            document,
            start_column=RawU32.from_value(int(self.geometry.start_column)),
            columns=RawU32.from_value(int(self.geometry.columns)),
            splits=tuple(splits),
            next_stable_id=next_id,
        )
