from __future__ import annotations

from types import SimpleNamespace

from stepnx.authoring.snapshot import AuthoringSnapshot, BlockSnapshot, SplitSnapshot
from stepnx.exporters.ssc_style_labels import _style_events, inject_steps_labels


def _block(split_id: int, stable_id: int, index: int, rows: int, style: int | None) -> BlockSnapshot:
    divisions = () if style is None else (SimpleNamespace(meta_id=200, value=style),)
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
        rows=tuple(None for _ in range(rows)),
        divisions=divisions,
    )


def _snapshot(spec: tuple[tuple[int, int], ...], *, start_column: int = 0) -> AuthoringSnapshot:
    splits = []
    active = []
    for index, (rows, style) in enumerate(spec):
        split_id = 100 + index
        block = _block(split_id, 1000 + index, 0, rows, style)
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
        source_name="EF1329/D.NX",
        profile="fiesta2-native",
        role="chart",
        start_column=start_column,
        columns=10,
        effective_lightmap=False,
        header_metadata=(),
        splits=tuple(splits),
        active_blocks=tuple(active),
        diagnostics=(),
    )


def test_ef1329_style_sequence_matches_official_offset_labels() -> None:
    snapshot = _snapshot(
        (
            (740, 3),   # beat 0.00 -> CENTERED / OFFSET00
            (10, 0),    # beat 92.50 -> SINGLE P1 / OFFSET01
            (12, 3),    # beat 93.75 -> CENTERED / OFFSET00
            (40, 0),    # beat 95.25 -> SINGLE P1 / OFFSET01
            (8, 3),     # beat 100.25 -> CENTERED / OFFSET00
        )
    )

    assert tuple((event.beat, event.label) for event in _style_events(snapshot)) == (
        (0.0, "OFFSET00"),
        (92.5, "OFFSET01"),
        (93.75, "OFFSET00"),
        (95.25, "OFFSET01"),
        (100.25, "OFFSET00"),
    )


def test_repeated_div200_state_emits_only_one_label() -> None:
    snapshot = _snapshot(((8, 2), (8, 2), (8, 2), (8, 3)))
    assert tuple((event.beat, event.label) for event in _style_events(snapshot)) == (
        (0.0, "OFFSET01"),
        (3.0, "OFFSET00"),
    )


def test_single_p2_projects_to_right_offset() -> None:
    snapshot = _snapshot(((8, 0),), start_column=5)
    assert tuple((event.beat, event.label) for event in _style_events(snapshot)) == (
        (0.0, "OFFSET02"),
    )


def test_generated_labels_follow_division_metadata_and_precede_notes() -> None:
    text = "\n".join(
        (
            "#NOTEDATA:;",
            "#SPEEDS:0=1=1=1,;",
            "#DIVISION:;",
            "#SPECIALDIVISION:;",
            "#NOTES:",
            "0000000000",
            ";",
        )
    ) + "\n"
    rendered = inject_steps_labels(
        text,
        (("0.000000=OFFSET00", "92.500000=OFFSET01"),),
    )

    assert rendered.index("#DIVISION:") < rendered.index("#LABELS:")
    assert rendered.index("#LABELS:") < rendered.index("#NOTES:")
    assert ",92.500000=OFFSET01" in rendered
