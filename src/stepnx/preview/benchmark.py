from __future__ import annotations

import argparse
import os
from pathlib import Path
from time import perf_counter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure the actual Qt gameplay-preview paint path"
    )
    parser.add_argument("chart", type=Path)
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--minimum-fps", type=float, default=30.0)
    parser.add_argument("--noteskin", type=Path)
    args = parser.parse_args(argv)
    if min(args.frames, args.width, args.height) <= 0 or args.minimum_fps <= 0:
        parser.error("frames, dimensions, and minimum FPS must be positive")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen" if os.name != "nt" else "windows")
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from stepnx.authoring.noteskin import load_noteskin_pack
    from stepnx.codecs.nx20 import load
    from stepnx.gui.preview_widget import GameplayPreviewWidget
    from stepnx.preview.commands import parse_gameplay_command
    from stepnx.preview.events import build_event_stream
    from stepnx.preview.routes import RoutePolicy, resolve_route
    from stepnx.preview.snapshot import create_preview_snapshot

    application = QApplication.instance() or QApplication([])
    snapshot = create_preview_snapshot(load(args.chart, row_storage="compact"))
    manual = {
        split.stable_id: split.blocks[0].stable_id
        for split in snapshot.splits
        if split.blocks
    }
    route = resolve_route(snapshot, RoutePolicy.MANUAL, manual=manual)
    stream = build_event_stream(snapshot, route)
    widget = GameplayPreviewWidget(
        stream,
        columns=snapshot.columns,
        start_column=snapshot.start_column,
        command=parse_gameplay_command("4"),
    )
    widget.resize(args.width, args.height)
    if args.noteskin is not None:
        widget.set_noteskin_pack(load_noteskin_pack(args.noteskin))
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    duration = max(1.0, stream.duration_ms)
    started = perf_counter()
    try:
        for frame in range(args.frames):
            chart_time = duration * frame / max(1, args.frames - 1)
            widget.set_playback_time(chart_time)
            widget.render(painter, QPoint())
    finally:
        painter.end()
        widget.close()
        application.processEvents()
    seconds = perf_counter() - started
    fps = args.frames / seconds if seconds else float("inf")
    print(
        f"{fps:.1f} fps; {seconds:.3f}s; {args.frames} frames; "
        f"{len(stream.events)} events; last paint {widget._paint_cost_ms:.2f} ms"
    )
    return 0 if fps >= args.minimum_fps else 1


if __name__ == "__main__":
    raise SystemExit(main())
