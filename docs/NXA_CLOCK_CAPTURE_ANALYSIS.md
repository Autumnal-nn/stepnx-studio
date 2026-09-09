# NXA clock observation phase: the F08 capture

The available phase-3 capture supports a stronger conclusion than PCM
correlation alone: the apparent 12 ms residual at the pre-clock breakpoint is
not present at the subsequent gameplay call using the updated chart time.
Do not add a 12 ms decoder compensation based on that earlier observation.

## Independent coordinate reconstruction

The source MP3 is byte-identical to the capture's `mad_stream_2.bin`. Five
correlation windows independently place captured raw frame zero at source PCM
frame 393,984. `mix.index` is contiguous and places that same frame at cumulative
ALSA-submitted frame 1,580,544. Thus:

```text
source_frame = global_output_frame - 1,186,560
predicted_chart_us = (source_frame - 6,912) * 1,000,000 / 48,000
```

The 6,912-frame term comes from the independently verified startup ledger.
No constant was fitted to chart timestamps. `played` in the probe is its cached
`submitted - snd_pcm_delay` estimate, not an external measurement of the DAC.

## Observations

Residual below means PCM-predicted chart time minus logged chart time. The
breakpoint records cover chart time 9.011–11.994 seconds, within the approximately
five-second mixer capture.

| Observation | Count | Minimum | Median | Maximum |
| --- | ---: | ---: | ---: | ---: |
| `clock_consumer`, before querying/updating chart time | 180 | +6.667 ms | +12 ms | +16 ms |
| `gameplay_hook`, after the update | 180 | 0 ms | 0 ms | +1 ms |
| `timing_select`, calls from multiple phases | 540 | −5.333 ms | 0 ms | +16 ms |

At `gameplay_hook`, 174 observations were exactly zero and six were +1 ms.
Pooling all event kinds would manufacture a broad residual distribution from
observations of different ages. `timing_select` is called more than once per
frame, so its event name alone does not identify a unique timing phase.

An example from the log makes the order explicit:

1. Before the clock call, the chart global still contains 9,011 ms while the
   cached PCM position predicts 9,020 ms.
2. The clock routine queries ALSA delay again.
3. At the subsequent gameplay call, the chart global contains 9,028 ms and the
   refreshed PCM position independently predicts 9,028 ms.

This establishes a stale-observation effect in this probe. It does not prove
that every historical subjective/visual offset in Studio had the same cause.

## Static corroboration in the supplied native executable

The call at `0x0808d341` obtains the audio clock. The chart global is written at
`0x0808d34c`, and later read/passed to the call at `0x0808d3f2`. A breakpoint on
the first call therefore sees the previous value of that global.

The clock core at `0x08087240` combines elapsed `gettimeofday` time with a
queue-corrected mixer cursor. It divides sample counts by the constant 48.0 to
obtain milliseconds. An internal correction approaches the clock difference by
one millisecond per call. The applied correction updates on every call while
the integer-second difference from initialization is at most two, then on a
change of the wall-clock second. The returned value is clamped nonnegative.
This is a smoothed, stateful clock, not a mathematical identity between a wall
timer and the audio sample cursor under every possible runtime condition.

The captured 512-byte core segment and 256-byte public-wrapper segment are
byte-identical to the corresponding regions of the supplied native executable.
Only their addresses, sizes and hashes are recorded in the repository. The
capture's executable as a whole is patched and has a different SHA-256; identical
clock segments do not establish equivalence of the entire runtime.

## Reproduce

With the original local capture ZIP, its exact source MP3, and the native ELF:

```sh
PYTHONPATH=src python tools/analyze_nxa_clock_capture.py /path/to/out-20260906-111721.zip /path/to/F08-runtime.mp3 --native /path/to/piu_nxa --output /new/path/clock-report.json
```

The tool verifies the compressed-stream fingerprint, rejects discontinuous
capture indices, discovers the audio displacement independently, groups clock
residuals by observation phase and compares the captured clock segments with
the native ELF. It does not execute or modify the game. NumPy/SciPy are required
for correlation. [The recorded report](validation/nxa-clock-capture-20260909.json)
contains the input hashes, all five alignments and residual histograms.

The remaining validation is repeated captures across files, start conditions
and target devices, plus an external output-latency measurement if physical
speaker/display timing is the claim. Matching a musical onset by eye is not an
independent decoder-clock calibration: chart authoring and onset choice can
also contribute an offset.
