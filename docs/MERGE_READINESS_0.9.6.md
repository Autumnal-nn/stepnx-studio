# StepNX Studio 0.9.6 merge readiness

This document is the merge handoff for `feat/ssc-random-compiler`. It records what the release candidate contains, what is deliberately experimental, and what still must be checked before the branch is merged to `main` and published as 0.9.6.

## Release scope

The branch combines three previously separate work tracks:

1. NXA canonical PCM and audio/timing reproducibility;
2. experimental SSC import/export and runtime-aware XSanity compilation;
3. editor playback/render hardening required by canonical PCM and very dense Timeline views.

The NX20/NFO lossless core remains the canonical product contract. SSC is an interoperability layer above or beside that core, not a replacement serialization model.

## NXA audio/timing state

The canonical PCM path is the release implementation for NXA compressed audio. Playback, waveform analysis, seeking, and metronome scheduling share the same decoded PCM coordinate, while the transport position continues to use the device-processed sample clock.

The earlier NXA timing investigation is considered resolved within the documented scope:

- NXA charts use NXA timing behavior under the NXA profile;
- Fiesta/Prime-family charts use their corresponding modern profile behavior;
- R!SE charts opened under Prime+ retain the documented `-24 ms` session calibration rather than receiving an implicit format-wide correction;
- the canonical PCM path does not claim bit-identical synthesis with the original cabinet decoder or eliminate physical device/driver latency.

See `NXA_PCM_CONTRACT.md`, ADR 0016, and `validation/rise-audio-calibration.md`.

## Editor playback/render state

The canonical PCM regression exposed rendering pressure rather than a new timing error. The branch now:

- uses a 100 ms PCM output ringbuffer while retaining `processedUSecs()` as the transport clock;
- refreshes the PCM UI at roughly 60 Hz rather than 100 Hz;
- clips waveform projection to the physical viewport;
- avoids one-frame-lifetime waveform `QPicture` caching during follow-playback;
- reuses playback tiles for sub-pixel row regions;
- clamps interactive Ctrl+wheel timing zoom at 12 pixels per encoded row, removing the pathological ultra-dense view while leaving maximum precision zoom unchanged.

Manual authoring validation before the 12-pixel clamp found practical zoom levels and maximum precision zoom stable, with stutter confined to the former 4-pixel extreme. The new floor still needs to be covered by the normal pre-release Windows smoke together with the automated suite.

## Experimental SSC state

The public SSC path is experimental in 0.9.6. See `SSC_EXPERIMENTAL_SUPPORT.md` for the full contract.

In summary:

- `.ssc` import is available through `File > Import charts...`;
- the importer recognizes the currently implemented SM5, StepF2/StepP1, and XSanity/Sanity syntax and emits diagnostics for unsupported semantics;
- folder export targets XSanity through `File > Export folder as XSanity SSC...`;
- the runtime compiler carries the proven NX branch/Random/Division/timing/item/noteskin semantics rather than flattening every chart to the currently visible route;
- unknown or unproven runtime semantics are diagnosed or rejected;
- Lightmap has no SSC projection and is excluded;
- no universal lossless SSC round trip is claimed.

Issue #26 should therefore remain open, or be narrowed after release, if its completion criterion continues to require bidirectional and lossless support across SM5, StepF2, and Sanity.

## PR #27 integration

PR #27 should not be merged independently after this branch. Its useful low-level XSanity corrections have been incorporated while StepNX's runtime-aware compiler remains the public export architecture.

The integrated review points include Start Time drift validation, Scroll magnitude/sign, independent Smooth/Skip flags, non-smooth speed encoding, float warp timing, explicit unknown-note policy, loss diagnostics, atomic output, and SSC tag escaping.

Special thanks are retained in the 0.9.6 release notes for th3y's implementation and follow-up review.

## Pre-merge automated gate

The feature branch currently has no attached GitHub Actions status for the latest release-preparation commits. Do not treat documentation preparation as a green CI gate.

Before merge:

- run `python tools/run_windows_test_gate.py` with the GUI dependencies installed on Windows;
- run the full Linux suite on the glibc 2.31 baseline used by the release workflow;
- confirm the canonical PCM extension builds on both release platforms;
- run the public-documentation language test;
- run the focused SSC import/export tests, including PR #27 integration coverage;
- run the timing/Skip/Smooth and canonical PCM GUI tests;
- verify that the new interactive zoom-floor regression passes.

Any test-floor/count value in older 0.9.5 status documents is historical and must not be reused as proof that the 0.9.6 branch passed.

## Pre-merge manual smoke

At minimum, the release candidate should be exercised on Windows with:

- NXA AUD/MP3 load, play, pause, seek, waveform, and metronome under canonical PCM;
- Ctrl+wheel near the new minimum and at maximum precision while playback follows the chart;
- an ordinary Fiesta/Prime audio source to confirm non-NXA transport remains unaffected;
- one R!SE chart using the documented Prime+ calibration procedure;
- one ordinary SSC import, one StepF2/StepP1-style import, and one XSanity/Sanity import;
- one ordinary XSanity export plus representative Random and Division exports;
- Save/reopen of an untouched native NX chart to confirm the byte-preservation contract remains unchanged.

## Release mechanics after the gate

Once the automated and manual gates are green:

1. update the public version to `0.9.6`;
2. update README and current STATUS wording to the 0.9.6 truth set;
3. add or activate the 0.9.6 release workflow using `docs/RELEASE_NOTES_0.9.6.md`;
4. compare `main...feat/ssc-random-compiler` one final time for unexpected drift;
5. merge the branch;
6. publish/tag only from the tested merge/release commit;
7. close or respond to PR #27 with attribution and an explanation that its applicable fixes landed through the integrated SSC stack;
8. update Issue #26 without claiming the experimental 0.9.6 layer is a universal lossless solution.

No release tag should be created from this preparation document alone.
