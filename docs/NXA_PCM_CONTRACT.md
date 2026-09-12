# NXA PCM timing contract and reproducible validation

This branch replaces the compressed-audio presentation path used by the NXA
experiment. It establishes a deterministic sample coordinate for offset
analysis. It does **not** claim universal, bit-exact emulation of the NXA audio
subsystem or a measured constant latency at the physical output.

## What changed

MP3/AUD/A in `nxa-native` and `nxa-step5-patched` use one pinned minimp3 decode.
Waveform construction consumes those exact music bytes; QAudioSink plays them
directly. Seek addresses the same decoded array and discards the old device
queue. MPEG metadata frames, encoder priming and trailing source frames remain
on the timeline. FFmpeg/LAME trim compensation is not applied to this path.

The metronome is an optional overlay on that array, scheduled from the active
NX route's beat or native judgment times. Coincident events produce one click.
Clicks and music enter the same output queue, and seeking into a click retains
its correct tail. The waveform/export still describe the unmodified music PCM.
Event times round to the nearest 48 kHz frame (at most half a frame of rounding).
The old Linux metronome queue lookahead does not alter these scheduled times.

The output clock uses QAudioSink's processed time, converted to frame indices.
The GUI refreshes periodically and retains millisecond transport controls;
its visible playhead is not a sample-accurate external DAC measurement.

## Coordinates and sign

Let `n` be the source PCM frame index, `L` the modeled net source lead in
frames, and `M` the manual Audio Offset in milliseconds:

```text
chart_ms = n * 1000 / 48000 - L * 1000 / 48000 - M
```

Positive `L` means NXA reaches source content earlier. For the supplied F08
runtime stream, nine source frames precede the first accepted frame:

| Quantity | Frames / bytes |
| --- | ---: |
| Source MPEG start | byte 2,048 |
| First frame accepted by the reference | byte 7,232 |
| Source samples before acceptance | 10,368 stereo frames |
| Samples synthesized during preceding recoveries | 3,456 stereo frames |
| Net source lead | 6,912 stereo frames = +144 ms |

The mapping is virtual: the exported WAV is source-frame PCM, with its chart
origin in the JSON report. It is not an NXA mixer dump with startup silence
prepended and skipped source frames physically removed. Startup/tail error
synthesis waveforms are not separately emulated.

The supplied executable's ALSA setup requests 48 kHz stereo S16. The observed
copy loop consumes synthesized samples without a resampling stage. Therefore
this compatibility path consumes even non-48 kHz MPEG samples at 48 kHz;
their original sample rate is reported. This models the observed output path,
not ordinary media-player playback at the MPEG header rate.

## Startup recovery corrections

The NXA caller synthesizes after successful decoding **and** recoverable
errors. A rejected header can mutate the next synthesis block length. The
revised model retains this state, follows observed reserved-version/layer/
bitrate/frequency error ordering, and does not reject the emphasis field ahead
of those errors. Layer-II synthesis length is 1,152 samples, including MPEG-2.

Free-format Layer-I inference requires bitrate quantization to 1 kbit/s followed
by the four-byte MPEG slot calculation. Rounding a byte distance alone was
insufficient. Resynchronization tests the next syncword rather than requiring
the next header to have the same format. Layer-I recovery is accepted only when
CRC/allocation bytes prove a modeled failure; potentially decodable Layer-I or
Layer-II startup is refused. Valid protected Layer-III frames have their CRC
checked rather than being assumed invalid.

The source path requires a continuous, fixed-format, non-free-format Layer-III
chain. Unsupported format transitions, detected corruption, truncated frames,
unrecognized trailers, and ambiguous startup stop NXA PCM loading. This is not
a general corruption-repair decoder. Passing these checks alone is not proof
that an arbitrary, untested file matches every libmad recovery behavior.

## Results from the supplied material

See [the machine-readable evidence](validation/nxa-pcm-20260909.json), containing
hashes and measurements, not proprietary audio or executable bytes.

- All 20 AUD files available from `AUD_Corpus-3.zip` and the F08 compressed
  stream recovered from the prior runtime capture passed independent repeated
  PCM/report equality.
- All 105 correlation windows had zero residual samples after the predicted
  startup displacement. Minimum correlation was 0.9999999989870593.
- Every overlapping frame was also compared directly: 192,439,296 stereo
  frames in total. The maximum absolute sample difference was 5 S16 units.
  The research gate's limit is 8 units. This is numerical agreement within
  tolerance, not byte equality between different decoders.
- The startup oracle's first accepted offset and preceding synthesized sample
  count matched for every tested file. Unpaired reference prefix/tail lengths
  are reported explicitly; no claim is made that total output lengths match.
- An additional deterministic 1,000-case false-header probe had 985 exact
  startup traces and 15 explicit refusals, with no accepted mismatches.
  These cases are retained as generated regression fixtures.
- Twelve generated mono/stereo cases at 16, 22.05, 24, 32, 44.1 and 48 kHz
  had zero measured lag against the local oracle. This is an offline check of
  the 48 kHz consumption contract, not an original-cabinet hardware test.
- The existing F08 mixer capture also supports an independently reconstructed
  chart coordinate: at the post-update gameplay call, 174/180 residuals are
  zero and six are +1 ms. The pre-update clock breakpoint instead has a +12 ms
  median because it reads the previous chart value. See
  [the clock-phase analysis](NXA_CLOCK_CAPTURE_ANALYSIS.md). This is a patched
  runtime's cached ALSA estimate, not a physical DAC latency measurement.
- Full Qt integration was exercised offscreen for load, manual offset,
  metronome mode and NXA/Fiesta2/NXA source reload. No physical audio output was
  available in the test environment.
- The full Python suite passed 661 tests. The external NX corpus had 12,354
  exact round trips and 12 NX10 imports, with no errors across 12,366 files.
- The Linux wheel was built and its decoder imported outside the source tree.
  GCC builds at `-O0` and the normal optimized setting produced the same golden
  PCM hash. Windows/native hardware validation remains a release gate.

`AUD-Corpus-2.zip` and `AUD_Corpus_1.zip` were not accessible and are not included
in these results. Older corpus summaries cannot substitute for decoding those
original bytes with this implementation.

## Reproduce the product path

Build/install from this branch with a C compiler available:

```sh
python -m pip install -e '.[gui]'
PYTHONPATH=src python -m unittest discover -s tests -v
stepnx-audio /path/to/track.AUD --verify-repeat --wav /new/path/track.wav --report /new/path/track.json
```

`python -m stepnx.authoring.pcm_cli` is equivalent to `stepnx-audio`. Output paths
must be new and distinct from the source. The report includes source/payload/
PCM SHA-256, decoder revision, sample/frame counts, startup ledger, format and
the exact chart mapping. The source is read once for hashing and AUD decoding.

## Reproduce the external reference checks

The original research harness in `tools/nxa_pcm_oracle.c` invokes the public
libmad API with the observed NXA caller policy. It does not ship a decoder
implementation. Build it locally against a separately supplied libmad; never
link or bundle it into the Apache-2.0 Studio product. The recorded run used
Debian libmad 0.15.1b-10.1+b1 and GCC on Linux x86-64. Its archive fingerprint is
in the evidence report.

```sh
cc -O2 tools/nxa_pcm_oracle.c -lmad -o /tmp/nxa-pcm-oracle
python -m pip install numpy scipy
PYTHONPATH=src python tools/verify_nxa_pcm.py /path/to/audio --oracle /tmp/nxa-pcm-oracle --output /new/path/corpus.json
PYTHONPATH=src python tools/verify_nxa_startup.py --oracle /tmp/nxa-pcm-oracle --output /new/path/startup.json
```

The first gate checks repeatability, startup coordinates, whole-overlap sample
differences, and five independent lag searches per sufficiently long file.
Quiet/short files without three usable windows fail that correlation gate;
they are not silently declared timing-equivalent. The startup gate reports
refusals separately from accepted mismatches. Its default fixture is original
generated audio, with deterministic pseudo-random prefix bytes.

## What remains before claiming a fixed physical residual

Run the existing [NXA runtime probe](NXA_AUDIO_PROBE.md) on the target executable
and audio configuration. Record executable/input hashes, actual ALSA format,
the chart-clock zero, mixer sample indices and queue depth. Repeat cold starts,
play/pause and Studio seeks across files, and compare early/middle/late content.
Use one predefined common residual tolerance; do not fit a correction per song.

The offline evidence removes measured file-dependent displacement for the
available files. A constant *physical* residual is a separate hypothesis: it
requires simultaneous runtime/clock/output observations and cannot be inferred
from a successful deterministic decode or a single device configuration.
