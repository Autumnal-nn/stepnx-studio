from __future__ import annotations

from collections.abc import Iterable

from stepnx.preview.events import PreviewEvent


def pair_nx20_holds(
    events: Iterable[PreviewEvent],
) -> tuple[tuple[PreviewEvent, PreviewEvent], ...]:
    """Reconstruct NX20 hold shafts from the resolved non-empty row stream.

    NX20-era runtime evidence from NXA and Prime 2 shows that completely empty
    rows are transparent to a long-note carry, regardless of the size of the
    gap. A globally non-empty row *is* processed: an open lane survives only on
    BODY (0xB), closes on TAIL (0xF), and is cancelled by any other value,
    including an implicit zero in that lane. This differs from the older NX10
    renderer and must not be approximated with a beat/time gap threshold.

    ``RuntimeEventStream.events`` omits globally empty rows entirely, so grouping
    the remaining events by source row gives exactly the state transitions the
    NX20 renderer needs.
    """

    ordered = tuple(events)
    if not ordered:
        return ()

    rows: list[tuple[tuple[int, int, int], list[PreviewEvent]]] = []
    for event in ordered:
        key = (event.split_id, event.block_id, event.row_index)
        if rows and rows[-1][0] == key:
            rows[-1][1].append(event)
        else:
            rows.append((key, [event]))

    open_heads: dict[int, PreviewEvent] = {}
    pairs: list[tuple[PreviewEvent, PreviewEvent]] = []

    for _key, row_events in rows:
        by_lane = {event.lane: event for event in row_events}

        # First advance every carry that existed before this non-empty row.
        # Absence from by_lane is an implicit zero in the lane and therefore
        # cancels the carry even when another lane made the row non-empty.
        for lane, head in tuple(open_heads.items()):
            current = by_lane.get(lane)
            if current is None:
                open_heads.pop(lane, None)
                continue
            if current.note_type == 0xB:
                continue
            if current.note_type == 0xF:
                pairs.append((head, current))
                open_heads.pop(lane, None)
                continue
            open_heads.pop(lane, None)

        # HEADs in the current row establish the carry used by subsequent
        # non-empty rows. A new HEAD naturally replaces an older carry because
        # the previous pass cancels it before this point.
        for event in row_events:
            if event.note_type == 0x7:
                open_heads[event.lane] = event

    return tuple(pairs)
