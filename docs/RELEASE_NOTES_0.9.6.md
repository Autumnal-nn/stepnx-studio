# StepNX Studio 0.9.6

This update focuses on NXA audio/timing correctness and experimental SSC interoperability.

## NXA audio and editor playback

- FIX: NXA compressed audio now uses one canonical PCM timeline for playback, waveform analysis, seeking, and metronome scheduling, removing backend-dependent MP3 clock drift from the editor.
- FIX: Canonical PCM playback is driven by the device-processed sample clock instead of compressed-file or GUI-timer timing.
- FIX: PCM buffering, waveform projection, and playback rendering were hardened so practical editor zoom levels, including maximum timing-precision zoom, remain smooth during playback.
- ADD: Loading an MP3 stream whose source sample rate is not 48,000 Hz now shows an explicit compatibility warning. This also covers MP3 payloads decoded from legacy AUD containers.
- CHANGE: Ctrl+wheel timing-precision zoom now stops before the pathological ultra-dense view that could overload rendering without providing useful authoring detail.
- CHANGE: R!SE charts opened under the Prime+ profile retain the documented -24 ms session calibration instead of receiving a hidden format-wide timing correction.

## Experimental SSC interoperability

- ADD: Experimental `.ssc` import through the existing chart-import workflow, covering the currently recognized StepMania 5, StepF2/StepP1, and XSanity/Sanity conventions.
- ADD: Experimental folder export targeting XSanity SSC.
- ADD: Runtime-aware SSC compilation for the proven NX branch, Random, Division, noteskin, item, and timing semantics currently modeled by StepNX Studio.
- FIX: XSanity export handling was hardened for Smooth/Skip flags, scroll magnitude and sign, Start Time drift reporting, warp precision, unknown-note handling, and escaped tag values.
- CHANGE: SSC conversion is deliberately loss-aware. Unsupported or unproven semantics are diagnosed or rejected rather than silently flattened, and 0.9.6 does not claim a universal lossless SSC round trip.

Special thanks to [th3y](https://github.com/th3y) for [PR #27](https://github.com/Autumnal-nn/stepnx-studio/pull/27) and the follow-up review and fixes that helped validate and harden the XSanity SSC export path, and an anonymous contributor for providing the R!SE files used for validation.

SSC support is **experimental** in 0.9.6. Keep the original source charts and validate exported content in the target engine before relying on it for production use.
