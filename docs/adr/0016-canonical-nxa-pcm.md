# ADR 0016: A canonical PCM timeline for NXA audio analysis

Status: Proposed for `fix/nxa-canonical-pcm`.

## Context

The `experiment/nxa-libmad-startup` branch demonstrated file-dependent timing
displacements, including F08's positive lead. Applying a startup correction to
Qt-decoded MP3 still depends on the backend's metadata/gapless policy, its seek
behavior, a separate waveform decode, and GUI-timer-driven metronome clicks.
An offset-analysis tool needs an inspectable, repeatable sample coordinate.

## Decision

For NXA profiles and MP3/AUD/A sources, decode once with a pinned, scalar
minimp3 frame decoder. Its CC0 license and exact upstream revision are recorded
under `src/stepnx/_vendor/minimp3`. The original Apache-2.0 native bridge retains
every source frame, duplicates mono channels, and produces stereo S16LE.
There is no gapless trimming or resampling. The observed NXA output contract
consumes samples at 48 kHz; original MPEG sample rate remains in the report.

Playback, waveform summaries and seek share this immutable source PCM. A
clean-room startup state machine maps its sample index to chart time. Clicks
are mixed at scheduled sample indices before playback. Device-processed frames
drive the transport; UI timers only refresh presentation. Manual Audio Offset
is additive and session-only. NX parsing, NX writing and the default engine
profile are unchanged.

Unsupported or ambiguous decode/recovery paths fail explicitly in the NXA
compressed-audio path. They do not silently select Qt's compressed decoder.
Other engine profiles retain the existing transport. Profile transitions reload
the original source rather than reusing a previous profile's staged audio.

## Consequences

- Source builds need a C compiler. Release bundles must include the extension
  and its permissive attribution. The product has no libmad dependency.
- Playback and waveform construction use additional memory for decoded PCM;
  loading is bounded to 64 MiB of compressed input and 128 million PCM frames.
- Changing the metronome schedule rebuilds its mix and resets queued playback
  at the processed position. Click placement no longer depends on UI polling.
- Sample timing parity is distinct from bit-identical reconstruction of NXA's
  synthesis, startup/tail error waveform, or DAC/driver latency. Those are not
  promised by this decision.
- Reproducibility is enforced by a PCM golden hash, independent repeated
  decoding, external-oracle startup regressions, and optional full-corpus
  comparisons. Supported release platforms must pass the golden check.

See [the contract and validation procedure](../NXA_PCM_CONTRACT.md).
