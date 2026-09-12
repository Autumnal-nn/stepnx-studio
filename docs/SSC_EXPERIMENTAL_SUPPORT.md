# Experimental SSC support

Status: experimental in StepNX Studio 0.9.6.

StepNX Studio keeps NX20 as its canonical authoring model. SSC is treated as an interoperability format with multiple incompatible dialects, not as a second canonical representation. Import and export therefore use explicit projection layers and surface diagnostics whenever the source semantics cannot be carried with confidence.

## Import

`File > Import charts...` accepts `.ssc` alongside the existing one-way legacy import formats. The importer recognizes the currently implemented parts of ordinary StepMania 5 SSC, StepF2/StepP1 note syntax, and the XSanity/Sanity extensions observed in the supplied corpus.

The current importer projects:

- Pump Single, Couple, Half Double, Double, Double-P, Double-DP, Routine, and the observed single-player variants into canonical NX20 lane geometry;
- `BPMS`, `SCROLLS`, `SPEEDS`, `STOPS`, `DELAYS`, `WARPS`, and `FAKES` timing data where a verified NX20 representation exists;
- ordinary StepMania taps, holds, rolls, mines, lifts, and fakes where their NX representation is known;
- observed StepF2/StepP1 brace syntax, with unsupported ownership/reserved semantics diagnosed rather than guessed;
- observed XSanity note layers, noteskin banks, items, special cells, and Brain Shower braces;
- XSanity's `9999999` frozen-BPM convention as an NX Skip Div (`smooth_speed` bit `0x02`), retaining the preceding real BPM and zero elapsed time for the skipped rows.

Import is one-way. It creates NX files through the normal authoring import review and never overwrites an existing target implicitly. A structurally successful import is not a claim that every engine-specific SSC behavior has a native NX equivalent.

## Export

`File > Export folder as XSanity SSC...` is the public experimental export path. It targets XSanity specifically. Lightmaps are excluded because SSC has no corresponding chart representation in this pipeline.

The export stack has two layers:

1. the low-level XSanity writer projects one selected NX route to SSC timing and note syntax, reports Start Time drift, preserves Scroll magnitude/sign, distinguishes Smooth (`0x01`) from Skip (`0x02`), and refuses unknown notes by default;
2. the runtime compiler sits above that writer and carries the proven subset of NX branch semantics through XSanity helper charts and `DIVISION` behavior, including ordered branch selection, Random pools, supported Division conditions, Random Skin, and the currently verified header/item semantics.

Random charts can require helper pools. The GUI preflights the folder, reports the exact helper count when known, offers supported size/accuracy trade-offs for large pools, estimates output size, and warns about XSanity `DIVISION` pool collisions. Unsupported runtime grammars are rejected rather than flattened silently.

## Loss model

The following statements are intentional product constraints for 0.9.6:

- SSC support is not advertised as universally lossless.
- SM5, StepF2/StepP1, and XSanity/Sanity share the `.ssc` extension but do not share one complete semantic contract.
- The exporter targets XSanity, not generic StepMania 5 or StepF2.
- Import diagnostics describe unsupported or approximated semantics, but an imported NX chart cannot reconstruct source-only syntax that has no canonical NX representation.
- Export diagnostics describe source NX semantics that cannot be represented by the current XSanity compiler.
- Unknown note bytes default to an error. Explicit fallback policies exist for low-level callers, but the normal authoring path should not silently invent mines or empty lanes.
- Runtime validation in the intended target engine remains required.

For these reasons, Issue #26 should not be considered fully satisfied by 0.9.6 if its completion criterion remains a lossless, bidirectional bridge for SM5, StepF2, and Sanity. This release establishes an experimental and testable interoperability layer that can be expanded without weakening the NX20 lossless core.

## PR #27 and attribution

The original one-way XSanity exporter in [PR #27](https://github.com/Autumnal-nn/stepnx-studio/pull/27) provided an important implementation reference. The follow-up review with [th3y](https://github.com/th3y) also led to concrete hardening around Start Time validation, Scroll projection, Smooth/Skip separation, non-smooth speed encoding, warp precision, unknown-note policy, loss reporting, atomic output, and SSC tag escaping.

StepNX Studio's 0.9.6 runtime compiler is broader than the PR's single-route exporter, so PR #27 should not be merged separately after this branch. Its applicable corrections have been integrated into the current SSC stack while the runtime-aware compiler remains the public folder-export path.

## Validation expectations

Before a release or merge that changes SSC behavior:

- run the complete unit suite on Windows and Linux;
- exercise representative ordinary, Random, Division, Smooth, Skip, item, and noteskin cases;
- verify at least one SSC import from each dialect family currently claimed;
- inspect diagnostics instead of treating a generated file as successful merely because it parses;
- keep source NX/SSC material available for comparison;
- test generated XSanity SSC in the target runtime for behavior that cannot be proven from file structure alone.

No proprietary game files are distributed with this documentation or the project.
