from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import Enum

from stepnx.core.model import (
    CompactRows,
    EmptyRow,
    EnvelopeKind,
    LightmapRow,
    NoteRow,
    NX20Document,
    OverlayRows,
    PackedNoteRow,
)


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: Severity
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...]

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.WARNING)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def validate(document: NX20Document) -> ValidationReport:
    """Validate the editable model without reparsing or serializing it."""

    issues: list[ValidationIssue] = []
    id_ranges: list[tuple[int, int, str]] = []

    def issue(severity: Severity, code: str, path: str, message: str) -> None:
        issues.append(ValidationIssue(severity, code, path, message))

    def stable(stable_id: int, path: str) -> None:
        if stable_id <= 0:
            issue(Severity.ERROR, "stable-id.invalid", path, "stable ID must be positive")
        id_ranges.append((stable_id, stable_id + 1, path))

    def compact_ids(rows: CompactRows, path: str) -> None:
        bounds = rows.stable_id_bounds
        if bounds is None:
            return
        if bounds[0] <= 0 or not rows.has_contiguous_stable_ids():
            issue(
                Severity.ERROR,
                "stable-id.compact-layout",
                path,
                "compact row IDs do not follow the contiguous cell-then-row layout",
            )
        id_ranges.append((bounds[0], bounds[1], path))

    def count(raw, actual: int, path: str) -> None:
        if int(raw.value) != actual:
            issue(
                Severity.WARNING,
                "count.stale",
                path,
                f"stored count is {int(raw.value)}; writer will emit {actual}",
            )

    stable(document.stable_id, "document")
    columns = int(document.columns.value)
    if not 1 <= columns <= 64:
        issue(
            Severity.ERROR,
            "columns.unsupported",
            "columns",
            f"column count {columns} is outside the structural range 1..64",
        )

    count(document.header_metadata_count, len(document.header_metadata), "header_metadata_count")
    for index, entry in enumerate(document.header_metadata):
        stable(entry.stable_id, f"header_metadata[{index}]")
    count(document.split_count, len(document.splits), "split_count")

    envelope = document.envelope
    if envelope.kind is EnvelopeKind.NONE and envelope.raw:
        issue(Severity.ERROR, "envelope.unexpected-bytes", "envelope", "none envelope contains bytes")
    elif envelope.kind is EnvelopeKind.SIZED_TRAILER:
        if len(envelope.raw) < 4:
            issue(Severity.ERROR, "envelope.missing-size", "envelope", "sized trailer has no u32 marker")
        else:
            marker = struct.unpack_from("<I", envelope.raw, len(envelope.raw) - 4)[0]
            if marker != len(envelope.raw):
                issue(
                    Severity.ERROR,
                    "envelope.size-mismatch",
                    "envelope",
                    f"marker says {marker} bytes; payload occupies {len(envelope.raw)}",
                )

    effective_lightmap = document.effective_lightmap
    for split_index, split in enumerate(document.splits):
        split_path = f"splits[{split_index}]"
        stable(split.stable_id, split_path)
        count(split.metadata_count, len(split.metadata), f"{split_path}.metadata_count")
        for index, entry in enumerate(split.metadata):
            stable(entry.stable_id, f"{split_path}.metadata[{index}]")
        count(split.block_count, len(split.blocks), f"{split_path}.block_count")

        for block_index, block in enumerate(split.blocks):
            block_path = f"{split_path}.blocks[{block_index}]"
            stable(block.stable_id, block_path)
            count(block.division_count, len(block.divisions), f"{block_path}.division_count")
            for index, entry in enumerate(block.divisions):
                stable(entry.stable_id, f"{block_path}.divisions[{index}]")
            count(block.row_count, len(block.rows), f"{block_path}.row_count")

            if isinstance(block.rows, CompactRows):
                compact_ids(block.rows, f"{block_path}.rows")
                if block.rows.columns != columns:
                    issue(
                        Severity.ERROR,
                        "rows.column-mismatch",
                        f"{block_path}.rows",
                        f"compact rows use {block.rows.columns} columns; document uses {columns}",
                    )
                if block.rows.effective_lightmap != effective_lightmap:
                    issue(
                        Severity.ERROR,
                        "rows.lightmap-mismatch",
                        f"{block_path}.rows",
                        "compact row encoding disagrees with document Lightmap state",
                    )
            elif isinstance(block.rows, OverlayRows):
                compact_ids(block.rows.base, f"{block_path}.rows.base")
                if block.rows.base.columns != columns:
                    issue(
                        Severity.ERROR,
                        "rows.column-mismatch",
                        f"{block_path}.rows",
                        f"overlay base uses {block.rows.base.columns} columns; document uses {columns}",
                    )
                if block.rows.base.effective_lightmap != effective_lightmap:
                    issue(
                        Severity.ERROR,
                        "rows.lightmap-mismatch",
                        f"{block_path}.rows",
                        "overlay base encoding disagrees with document Lightmap state",
                    )
                for index, replacement in block.rows.replacements:
                    original = block.rows.base[index]
                    if replacement.stable_id != original.stable_id:
                        issue(
                            Severity.ERROR,
                            "stable-id.replaced",
                            f"{block_path}.rows[{index}]",
                            "overlay replacement changed the row stable ID",
                        )

                    if isinstance(replacement, NoteRow) and isinstance(
                        original, PackedNoteRow
                    ):
                        if tuple(cell.stable_id for cell in replacement.cells) != tuple(
                            cell.stable_id for cell in original.cells
                        ):
                            issue(
                                Severity.ERROR,
                                "stable-id.replaced-cell",
                                f"{block_path}.rows[{index}]",
                                "overlay replacement changed one or more cell stable IDs",
                            )

            rows_to_check = (
                block.rows.replacements
                if isinstance(block.rows, OverlayRows)
                else enumerate(block.rows)
                if not isinstance(block.rows, CompactRows)
                else ()
            )
            for row_index, row in rows_to_check:
                row_path = f"{block_path}.rows[{row_index}]"
                if not isinstance(block.rows, OverlayRows):
                    stable(row.stable_id, row_path)
                if isinstance(row, EmptyRow):
                    continue
                if effective_lightmap:
                    if not isinstance(row, LightmapRow):
                        issue(
                            Severity.ERROR,
                            "row.wrong-kind",
                            row_path,
                            "effective Lightmap requires LightmapRow or EmptyRow",
                        )
                    continue
                if not isinstance(row, (NoteRow, PackedNoteRow)):
                    issue(
                        Severity.ERROR,
                        "row.wrong-kind",
                        row_path,
                        "normal chart requires NoteRow, PackedNoteRow, or EmptyRow",
                    )
                    continue
                if row.cell_count != columns:
                    issue(
                        Severity.ERROR,
                        "row.width",
                        row_path,
                        f"row has {row.cell_count} cells; expected {columns}",
                    )
                for cell_index, cell in enumerate(row.cells):
                    if not isinstance(block.rows, OverlayRows):
                        stable(cell.stable_id, f"{row_path}.cells[{cell_index}]")

    id_ranges.sort(key=lambda item: (item[0], item[1]))
    for previous, current in zip(id_ranges, id_ranges[1:]):
        if current[0] < previous[1]:
            issue(
                Severity.ERROR,
                "stable-id.duplicate",
                current[2],
                f"stable ID range {current[0]}..{current[1] - 1} overlaps {previous[2]}",
            )

    highest_id = max((end - 1 for _, end, _ in id_ranges), default=0)
    if document.next_stable_id <= highest_id:
        issue(
            Severity.ERROR,
            "stable-id.watermark",
            "next_stable_id",
            f"next stable ID {document.next_stable_id} must be greater than "
            f"existing ID {highest_id}",
        )

    return ValidationReport(tuple(issues))
