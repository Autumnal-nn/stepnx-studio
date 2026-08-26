from __future__ import annotations

import math
from dataclasses import replace

from stepnx.core.scalars import RawF32
from stepnx.gui.phase10_install import _resize_split_to_reference_rows


def resize_split_boundary_cascade_document(
    document,
    split_id: int,
    reference_block_id: int,
    requested_rows: int,
):
    """Resize one Split boundary and shift every downstream Block by the same delta.

    Moving the boundary between Split N and Split N+1 changes the absolute chart
    position of the entire suffix beginning at N+1. Therefore every Block in
    every later Split receives the exact same millisecond delta; only the upper
    Split's row count changes.
    """

    # Import lazily to avoid an import cycle while phase11_feedback installs its
    # own widget adapters.
    from stepnx.gui.phase11_feedback import _nearest_representable_rows

    split_index = next(
        i for i, item in enumerate(document.splits) if item.stable_id == split_id
    )
    if split_index + 1 >= len(document.splits):
        raise ValueError("the final Split has no lower boundary to move")

    upper = document.splits[split_index]
    reference = next(
        item for item in upper.blocks if item.stable_id == reference_block_id
    )
    old_rows = len(reference.rows)
    new_rows = _nearest_representable_rows(
        document, split_id, reference_block_id, requested_rows
    )
    if new_rows == old_rows:
        return document, new_rows

    bpm = float(reference.bpm.value)
    beat_split = int(reference.beat_split.value)
    if not math.isfinite(bpm) or bpm <= 0.0 or beat_split <= 0:
        raise ValueError("reference Block has invalid BPM or Beat Split")
    delta_ms = (new_rows - old_rows) * 60_000.0 / (bpm * beat_split)

    resized = _resize_split_to_reference_rows(
        document, split_id, reference_block_id, new_rows
    )

    shifted_splits = []
    for index, split in enumerate(resized.splits):
        if index <= split_index:
            shifted_splits.append(split)
            continue
        shifted_splits.append(
            replace(
                split,
                blocks=tuple(
                    replace(
                        block,
                        start_time=RawF32.from_value(
                            float(block.start_time.value) + delta_ms
                        ),
                        span=None,
                    )
                    for block in split.blocks
                ),
                span=None,
            )
        )

    return replace(resized, splits=tuple(shifted_splits)), new_rows


def install_phase11_split_cascade(window) -> None:
    """Patch the feedback boundary handler with suffix-wide timing semantics."""

    if getattr(window, "_phase11_split_cascade_installed", False):
        return
    window._phase11_split_cascade_installed = True

    import stepnx.gui.phase11_feedback as feedback_module

    feedback_module._resize_split_boundary_document = (
        resize_split_boundary_cascade_document
    )

    original_commit = getattr(window, "_phase11_commit_split_boundary", None)
    if not callable(original_commit):
        return

    def commit_with_suffix_message(widget, split_id: int, block_id: int, rows: int):
        result = original_commit(widget, split_id, block_id, rows)
        window.statusBar().showMessage(
            "Moved Split boundary; all downstream Block Start Times were shifted equally",
            5000,
        )
        return result

    window._phase11_commit_split_boundary = commit_with_suffix_message
