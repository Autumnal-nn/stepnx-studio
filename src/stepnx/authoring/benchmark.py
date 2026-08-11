from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

from stepnx.authoring.snapshot import AuthoringSnapshot, create_authoring_snapshot
from stepnx.authoring.timeline import TimelineGeometry, TimelineLayout
from stepnx.codecs.nx20 import load


@dataclass(frozen=True, slots=True)
class ViewportBenchmark:
    frames: int
    seconds: float
    frames_per_second: float
    rows_touched: int
    maximum_rows_per_frame: int


def benchmark_viewport(
    snapshot: AuthoringSnapshot,
    *,
    frames: int = 600,
    viewport_height: float = 900.0,
) -> ViewportBenchmark:
    if frames <= 0 or viewport_height <= 0:
        raise ValueError("frames and viewport height must be positive")
    geometry = TimelineGeometry()
    layout = TimelineLayout(snapshot, geometry)
    scroll_span = max(0.0, layout.content_height - viewport_height)
    touched = 0
    maximum = 0
    started = time.perf_counter()
    for frame in range(frames):
        if frame and frame % 60 == 0:
            geometry = geometry.zoomed(1.1 if (frame // 60) % 2 else 1 / 1.1)
            layout = TimelineLayout(snapshot, geometry)
            scroll_span = max(0.0, layout.content_height - viewport_height)
        phase = (frame % 120) / 119 if frames > 1 else 0.0
        top = scroll_span * (phase if (frame // 120) % 2 == 0 else 1.0 - phase)
        frame_rows = 0
        for visible in layout.visible_segments(top, viewport_height):
            for row_index in range(visible.first_row, visible.last_row):
                visible.segment.block.rows[row_index]
                frame_rows += 1
        touched += frame_rows
        maximum = max(maximum, frame_rows)
    seconds = time.perf_counter() - started
    return ViewportBenchmark(
        frames=frames,
        seconds=seconds,
        frames_per_second=frames / seconds if seconds else float("inf"),
        rows_touched=touched,
        maximum_rows_per_frame=maximum,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark StepNX timeline culling")
    parser.add_argument("chart", type=Path)
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--viewport-height", type=float, default=900.0)
    args = parser.parse_args(argv)
    snapshot = create_authoring_snapshot(load(args.chart, row_storage="compact"))
    result = benchmark_viewport(
        snapshot,
        frames=args.frames,
        viewport_height=args.viewport_height,
    )
    print(
        f"{result.frames_per_second:.1f} fps; {result.seconds:.3f}s; "
        f"max {result.maximum_rows_per_frame} rows/frame"
    )
    return 0 if result.frames_per_second >= 30.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
