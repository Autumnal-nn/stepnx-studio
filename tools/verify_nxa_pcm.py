#!/usr/bin/env python3
"""Optional local corpus gate. Requires NumPy/SciPy for correlation only.

The optional external oracle must accept INPUT_MP3 OUTPUT_S16LE OUTPUT_CSV.
It must use NXA's observed decode/recover/synthesize call policy. Neither that
executable, libmad, nor proprietary corpus bytes are part of the product.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import tempfile
from pathlib import Path

from stepnx.authoring.audio import decode_aud
from stepnx.authoring.pcm import decode_mp3_pcm, load_nxa_pcm


def compare(pcm, reference):
    import numpy as np
    from scipy.signal import correlate

    actual = np.frombuffer(pcm.samples, dtype="<i2").reshape(-1, 2).mean(axis=1)
    reference = np.frombuffer(reference, dtype="<i2").reshape(-1, 2).mean(axis=1)
    lead = pcm.startup.net_source_lead_samples
    width, margin = 12_000, 2048
    end = min(len(reference), len(actual) - lead) - width - margin
    windows = []
    for start in sorted(set(int(end * fraction) for fraction in (0.05, 0.25, 0.5, 0.75, 0.95))):
        if start + lead < margin or start < 0:
            continue
        expected = reference[start:start + width]
        if np.std(expected) < 0.5:
            continue
        candidate = actual[start + lead - margin:start + lead + width + margin]
        expected = expected - expected.mean()
        scores = correlate(candidate, expected, mode="valid", method="fft")
        square_prefix = np.concatenate(([0.0], np.cumsum(candidate * candidate)))
        sum_prefix = np.concatenate(([0.0], np.cumsum(candidate)))
        energy = square_prefix[width:] - square_prefix[:-width]
        sums = sum_prefix[width:] - sum_prefix[:-width]
        energy -= sums * sums / width
        scores /= np.sqrt(np.maximum(energy, 1e-30) * np.dot(expected, expected))
        peak = int(scores.argmax())
        windows.append({
            "reference_start_frame": start,
            "residual_samples": peak - margin,
            "correlation": float(scores[peak]),
        })
    return windows


def compare_full_overlap(pcm, reference):
    """Check every overlapping stereo frame at the predicted displacement."""
    import numpy as np

    actual = np.frombuffer(pcm.samples, dtype="<i2").reshape(-1, 2)
    expected = np.frombuffer(reference, dtype="<i2").reshape(-1, 2)
    lead = pcm.startup.net_source_lead_samples
    begin, end = max(0, -lead), min(len(expected), len(actual) - lead)
    maximum, squared, count = 0, 0.0, 0
    for start in range(begin, end, 48_000):
        stop = min(end, start + 48_000)
        delta = (actual[start + lead:stop + lead].astype(np.int32) -
                 expected[start:stop].astype(np.int32))
        maximum = max(maximum, int(np.abs(delta).max()))
        squared += float(np.sum(delta.astype(np.float64) ** 2))
        count += delta.size
    return {"reference_first_frame": begin, "reference_end_frame": end,
            "compared_stereo_frames": count // 2, "max_absolute_s16_difference": maximum,
            "rms_s16_difference": (squared / count) ** 0.5 if count else None,
            "reference_prefix_outside_source_mapping": begin,
            "reference_tail_outside_source_mapping": len(expected) - end}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = sorted({
        file.resolve() for path in args.paths
        for file in ([path] if path.is_file() else path.rglob("*"))
        if file.is_file() and file.suffix.casefold() in {".aud", ".a", ".mp3"}
    })
    results = []
    for path in files:
        item = {"source_name": path.name}
        try:
            pcm = load_nxa_pcm(path)
            again = load_nxa_pcm(path)
            if pcm.samples != again.samples or pcm.report() != again.report():
                raise ValueError("repeat decode differs")
            del again
            item.update(pcm.report())
            item["repeat_verified"] = True
            if args.oracle is not None:
                payload = decode_aud(path) if path.suffix.casefold() in {".aud", ".a"} else path.read_bytes()
                with tempfile.TemporaryDirectory(prefix="stepnx-oracle-") as directory:
                    directory = Path(directory)
                    source, raw, log = (directory / name for name in ("source.mp3", "reference.raw", "frames.csv"))
                    source.write_bytes(payload)
                    subprocess.run([str(args.oracle.resolve()), str(source), str(raw), str(log)], check=True, timeout=120)
                    reference = raw.read_bytes()
                    windows = compare(pcm, reference)
                    item["oracle_windows"] = windows
                    overlap = compare_full_overlap(pcm, reference)
                    item["oracle_full_overlap"] = overlap
                    if not overlap["compared_stereo_frames"] or overlap["max_absolute_s16_difference"] > 8:
                        raise ValueError("full aligned PCM comparison exceeds the 8-LSB research tolerance")
                    with log.open() as trace:
                        events = list(csv.DictReader(trace))
                    item["oracle_frames"] = sum(int(row["length"]) for row in events)
                    first = next((i for i, row in enumerate(events) if row["error"] == "0"), None)
                    if first is None:
                        raise ValueError("oracle never accepted a frame")
                    item["oracle_first_decoded_offset"] = int(events[first]["offset"])
                    item["oracle_startup_samples"] = sum(int(row["length"]) for row in events[:first])
                    if (item["oracle_first_decoded_offset"] != pcm.startup.first_decoded_offset or
                            item["oracle_startup_samples"] != pcm.startup.synthesized_samples_before_first_decoded):
                        raise ValueError("startup ledger disagrees with the oracle")
                    if len(windows) < 3 or any(w["residual_samples"] != 0 or w["correlation"] < 0.999 for w in windows):
                        raise ValueError("reference correlation gate failed")
            item["passed"] = True
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            item.update(passed=False, error=str(exc))
        results.append(item)
        print(path.name, "PASS" if item["passed"] else item["error"], flush=True)
    args.output.write_text(json.dumps({"files": results}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if results and all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
