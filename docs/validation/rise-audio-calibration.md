# Rise audio calibration and NXA branch acceptance

## Accepted scope

The maintainer considers `fix/nxa-canonical-pcm` resolved after the reported
manual tests. This is acceptance of the branch's scope, not a claim that every
chart has perfect authored synchronization or that device latency is zero.

| Content | Studio profile | Reported result |
|---|---|---|
| NXA | NXA | Correct alignment in the maintainer's tests. |
| Fiesta 2 | Fiesta | Correct alignment or tolerable individual discrepancies. |
| Prime 2 | Prime+ | Correct alignment or tolerable individual discrepancies; no common -24 ms residual. |
| Rise | Prime+ | The tested charts require session-only Audio Offset of **-24 ms**. |

The maintainer suspects remaining individual Fiesta 2/Prime 2 discrepancies
are chart-authoring synchronization errors. This has not been established for
every affected chart and is not a reason to apply a global correction.

## Working with Rise charts

Use the **Prime+** profile and set the session-only audio calibration to
**-24 ms** for the tested Rise material. This aligns both waveform/grid and
audio/metronome in the reported comparisons. It does not edit the NX chart or
the source audio. Reset the calibration to the appropriate value (normally
0 ms for these tests) before returning to Fiesta 2 or Prime 2 material; do not
assume this session setting is automatically scoped to the source game.

No automatic Rise detection, new preset, per-profile calibration storage, or
global -24 ms compensation was added. The value is an observed calibration
for the tested Rise chart/audio pairs, not a proven universal decoder rule.

## Recorded comparisons

Each row compares the same chart/audio pair while changing Studio profiles.
Values are the manual calibration required by the maintainer.

| Rise song | NXA profile | Prime+ profile |
|---|---:|---:|
| A03 | 0 ms | -24 ms |
| 811 | 0 ms | -24 ms |
| 18A3 | -24 ms | -24 ms |
| 18B3 | -24 ms | -24 ms |

NXA startup mapping is appropriate to the NXA target. An apparently aligned
Rise chart under that profile does not establish Rise runtime equivalence.

## Evidence and limits

- A03 has a 169-byte ID3v2.3 prefix. The NXA startup model counts a recovery
  of 1152 samples, yielding -24 ms effective offset at 48 kHz. 18A3 begins
  with MPEG audio and has no such recovery.
- In temporary copies, removing A03's ID3 changed startup from -24 to 0 ms;
  adding that prefix to 18A3 changed startup from 0 to -24 ms. Canonical PCM
  remained byte-identical to the corresponding original in both experiments.
  This demonstrates the Studio startup-model trigger, not a new cabinet test.
- Six Qt/canonical report pairs (A03, 18A3, 705, F24, 1132, 1734) had matching
  source hashes and decoded frame counts. Qt timestamps had no gaps and its
  waveform duration matched sample duration. The bitrate-duration warning
  did not explain the residual in these cases.
- Rise's supplied FMOD 2.02.24 library was exercised on Windows with the
  observed memory-load mode 0x900. A03 and 18A3 each decoded reproducibly.
  Against canonical PCM, five content-correlation windows per song (2, 10,
  30, 60, 90 seconds) all measured zero sample displacement. FMOD returned
  1152 additional frames for each song, all zero and trailing the canonical
  buffer. The extra 24 ms of duration is not a measured 24 ms music delay.
- PCM amplitudes are not identical across decoders. These tests do not measure
  gameplay clocks, the music DSP chain or physical output latency. The root
  cause of Rise's reported absolute -24 ms calibration remains unresolved.

The observed Rise residual does not block acceptance of this branch. It must
not be generalized to Prime 2, and it does not justify changing the validated
NXA startup rules. Further Rise investigation is optional follow-up work.

## Integration status

Documentation-only closure: keep the branch separate. Squash, merge and
release remain deferred at the maintainer's request. A future release may
combine this work with the SSC module; this does not claim SSC is implemented
or ready. No version bump or release tag is part of this closure.
