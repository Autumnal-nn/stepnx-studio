#!/usr/bin/env python3
"""Join a phase-3 mixer capture to source PCM before comparing chart clocks.

No offset is fitted to chart-time observations. The source/mixer displacement
is found independently by audio correlation, then the startup sample ledger
and mix.index locate it in the output device's cumulative frame coordinate.
Requires NumPy/SciPy and the original local capture ZIP; no game assets ship.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import statistics
import struct
import zipfile

from stepnx.authoring.pcm import load_nxa_pcm


def fields(line):
    return dict(re.findall(r"(\w+)=([^ ]+)", line))


def read_member(archive, basename):
    names = [name for name in archive.namelist() if name.endswith("/" + basename) or name == basename]
    if len(names) != 1:
        raise ValueError(f"capture needs exactly one {basename}")
    if archive.getinfo(names[0]).file_size > 128 * 1024 * 1024:
        raise ValueError(f"capture member exceeds the size limit: {basename}")
    return archive.read(names[0])


def elf_bytes(data, address, size):
    if data[:6] != b"\x7fELF\x01\x01":
        raise ValueError("clock comparison expects ELF32 little-endian")
    offset = struct.unpack_from("<I", data, 28)[0]
    stride, count = struct.unpack_from("<HH", data, 42)
    for index in range(count):
        kind, position, virtual, _, length, *_ = struct.unpack_from("<8I", data, offset + index * stride)
        if kind == 1 and virtual <= address and address + size <= virtual + length:
            begin = position + address - virtual
            return data[begin:begin + size]
    raise ValueError("clock address is outside executable file segments")


def align_samples(pcm, raw):
    import numpy as np
    from scipy.signal import correlate

    source = np.frombuffer(pcm.samples, dtype="<i2").reshape(-1, 2).mean(axis=1)
    captured = np.frombuffer(raw, dtype="<i2").reshape(-1, 2).mean(axis=1)
    width = 12_000
    if len(captured) < 2 * width or len(source) < len(captured):
        raise ValueError("capture is too short or source shorter than capture")
    sums = np.concatenate(([0.0], np.cumsum(source)))
    squares = np.concatenate(([0.0], np.cumsum(source * source)))
    energy = squares[width:] - squares[:-width] - (sums[width:] - sums[:-width]) ** 2 / width
    windows = []
    for fraction in (0.1, 0.3, 0.5, 0.7, 0.9):
        begin = min(int(len(captured) * fraction), len(captured) - width)
        reference = captured[begin:begin + width]
        reference = reference - reference.mean()
        if np.std(reference) < 0.5:
            raise ValueError("capture alignment window has insufficient signal")
        scores = correlate(source, reference, mode="valid", method="fft")
        scores /= np.sqrt(np.maximum(energy, 1e-30) * np.dot(reference, reference))
        peak = int(scores.argmax())
        windows.append({"capture_start_frame": begin, "source_start_frame": peak,
                        "source_minus_capture_frames": peak - begin, "correlation": float(scores[peak])})
    offsets = {window["source_minus_capture_frames"] for window in windows}
    if len(offsets) != 1 or min(window["correlation"] for window in windows) < 0.999:
        raise ValueError("audio alignment is not a single verified displacement")
    return windows, offsets.pop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--native", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inputs = [args.capture, args.source] + ([args.native] if args.native is not None else [])
    if args.output.exists() or args.output.resolve() in {path.resolve() for path in inputs}:
        raise ValueError("output must be new and distinct from capture, source and executable")
    pcm = load_nxa_pcm(args.source)
    with zipfile.ZipFile(args.capture) as archive:
        matching_streams = []
        for name in archive.namelist():
            if re.fullmatch(r"mad_stream_\d+\.bin", Path(name).name):
                data = read_member(archive, Path(name).name)
                if hashlib.sha256(data).hexdigest() == pcm.payload_sha256:
                    matching_streams.append(Path(name).name)
        if not matching_streams:
            raise ValueError("source payload is not one of the captured compressed streams")
        raw = read_member(archive, "mix.raw")
        index = [fields(line) for line in read_member(archive, "mix.index").decode().splitlines() if line.strip()]
        logs = [fields(line) for line in read_member(archive, "timing.log").decode().splitlines()]
        cursor = 0
        starts = set()
        for row in index:
            offset, length, frames = (int(row[key]) for key in ("raw_off", "bytes", "frames"))
            if offset != cursor or length != 4 * frames or int(row["frame_bytes"]) != 4:
                raise ValueError("mix.index is not contiguous stereo S16")
            starts.add(int(row["start_frame"]) - offset // 4)
            cursor += length
        if len(starts) != 1 or cursor != len(raw):
            raise ValueError("capture crosses output discontinuities or has missing bytes")
        global_start = starts.pop()
        windows, source_minus_capture = align_samples(pcm, raw)
        source_minus_global = source_minus_capture - global_start
        by_event = defaultdict(list)
        for row in logs:
            if "played" not in row or "chart_us" not in row:
                continue
            played = int(row["played"])
            if not global_start <= played < global_start + len(raw) // 4:
                continue
            predicted_us = (played + source_minus_global - pcm.startup.net_source_lead_samples) * 1_000_000 / 48_000
            by_event[row["event"]].append(predicted_us - int(row["chart_us"]))
        summary = {}
        for event, values in sorted(by_event.items()):
            summary[event] = {"observations": len(values), "min_us": min(values),
                              "median_us": statistics.median(values), "max_us": max(values),
                              "histogram_us": dict(sorted(Counter(round(value, 6) for value in values).items()))}
        comparisons = {}
        if args.native is not None:
            native = args.native.read_bytes()
            for name, address in (("clock_core.bin", 0x08087240), ("clock_public.bin", 0x080873B0)):
                captured = read_member(archive, name)
                comparisons[name] = {"address": hex(address), "size": len(captured),
                                     "sha256": hashlib.sha256(captured).hexdigest(),
                                     "identical_to_native": captured == elf_bytes(native, address, len(captured))}
            comparisons["native_sha256"] = hashlib.sha256(native).hexdigest()
        report = {"capture_sha256": hashlib.sha256(args.capture.read_bytes()).hexdigest(),
                  "captured_executable_sha256": read_member(archive, "executable.sha256").decode().split()[0],
                  "source_sha256": pcm.source_sha256, "pcm_sha256": pcm.report()["pcm_sha256"],
                  "matching_compressed_streams": matching_streams,
                  "capture_first_global_frame": global_start, "capture_frames": len(raw) // 4,
                  "source_minus_capture_frames": source_minus_capture,
                  "source_minus_global_frames": source_minus_global,
                  "startup_lead_frames": pcm.startup.net_source_lead_samples,
                  "audio_alignment_windows": windows, "event_residuals": summary,
                  "clock_binary_comparison": comparisons,
                  "residual_definition": "PCM-predicted chart time minus recorded chart time; no fitted chart offset",
                  "limitations": ["Breakpoint events use the probe's cached ALSA delay estimate, not a DAC measurement",
                                  "Captured executable is patched; identical clock bytes do not prove whole-runtime equivalence",
                                  "Results apply to this capture and observed phase, not all startup/seek/device conditions"]}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({event: {key: row[key] for key in ("observations", "min_us", "median_us", "max_us")}
                      for event, row in summary.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
