from __future__ import annotations

from types import SimpleNamespace

from stepnx.authoring.snapshot import AuthoringSnapshot, BlockSnapshot, SplitSnapshot
from stepnx.exporters.ssc_autoplay_labels import (
    _autoplay_events,
    merge_control_label_tables,
)


def _block(split_id: int, stable_id: int, index: int, *, rows: int = 8, autoplay=None):
    divisions = ()
    if autoplay is not None:
        divisions = (SimpleNamespace(meta_id=999, value=autoplay),)
    return BlockSnapshot(
        stable_id=stable_id,
        split_id=split_id,
        index=index,
        start_time=0.0,
        bpm=120.0,
        scroll=1.0,
        offset_or_delay=0.0,
        speed_or_freeze=1.0,
        beat_split=8,
        beat_measure=4,
        smooth_speed=0,
        raw_flag=0,
        rows=tuple(SimpleNamespace() for _ in range(rows)),
        divisions=divisions,
    )


def _snapshot(states) -> AuthoringSnapshot:
    splits = []
    active = []
    for index, state in enumerate(states):
        split_id = 100 + index
        block = _block(split_id, 1000 + index, 0, autoplay=state)
        splits.append(
            SplitSnapshot(
                stable_id=split_id,
                index=index,
                raw_select=0,
                raw_brain=0,
                raw_padding=0,
                metadata=(),
                blocks=(block,),
            )
        )
        active.append((split_id, block.stable_id))
    return AuthoringSnapshot(
        document_stable_id=1,
        source_name="fixture.NX",
        profile="fiesta2-native",
        role="chart",
        start_column=0,
        columns=5,
        effective_lightmap=False,
        header_metadata=(),
        splits=tuple(splits),
        active_blocks=tuple(active),
        diagnostics=(),
    )


def test_id999_state_changes_become_delayed_autoplay_labels() -> None:
    events = _autoplay_events(_snapshot((None, 1, None)))

    assert [(event.beat, event.label) for event in events] == [
        (1.25, "AUTOPLAYON"),
        (2.25, "AUTOPLAYOFF"),
    ]


def test_nonzero_id999_values_share_sanity_binary_on_state() -> None:
    for value in (1, 3, 4, 999):
        events = _autoplay_events(_snapshot((value, None)))
        assert [(event.beat, event.label) for event in events] == [
            (0.25, "AUTOPLAYON"),
            (1.25, "AUTOPLAYOFF"),
        ]


def test_repeated_autoplay_state_does_not_emit_duplicate_labels() -> None:
    events = _autoplay_events(_snapshot((1, 1, 1, None)))
    assert [(event.beat, event.label) for event in events] == [
        (0.25, "AUTOPLAYON"),
        (3.25, "AUTOPLAYOFF"),
    ]


def test_control_label_merge_orders_by_beat_and_keeps_feature_tie_order() -> None:
    offsets = (("0.000000=OFFSET00", "2.000000=OFFSET01"),)
    autoplay = (("1.250000=AUTOPLAYON", "2.000000=AUTOPLAYOFF"),)

    assert merge_control_label_tables(offsets, autoplay) == ((
        "0.000000=OFFSET00",
        "1.250000=AUTOPLAYON",
        "2.000000=OFFSET01",
        "2.000000=AUTOPLAYOFF",
    ),)
