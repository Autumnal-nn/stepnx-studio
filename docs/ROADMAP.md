# StepNX Studio technical roadmap

Revision: 2026-09-02

Current target: **0.9.5 pre-alpha hardening**

Long-term target: a lossless native NX20 desktop editor with dependable
publication, authoring, import and preview workflows.

## Product boundary

StepNX Studio uses a canonical NX20 model. NX and NFO are native documents;
NX10 and other legacy formats are one-way imports. A folder is the workspace
unit. No NXP sentinel or project sidecar exists.

The Qt application, authoring viewport, audio system and gameplay preview are
consumers of the same canonical document. They do not parse or serialize chart
files independently.

## Non-negotiable engineering rules

1. No-edit round-trip is byte-exact.
2. Unknown means preserved, not zeroed, discarded or guessed.
3. Metadata remains ordered and may contain duplicates.
4. Float bits remain authoritative until explicitly edited.
5. Semantics are contextual: Header, Split and Division metadata are distinct.
6. Engine behavior belongs to explicit engine-family profiles.
7. Imports never silently replace or convert their source.
8. The canonical document is the only source of truth.
9. Every edit uses the command/validation/undo infrastructure.
10. Public documentation and contributor-facing text are English.

## Architecture

```text
Binary codecs/importers
        |
        v
Canonical NX20 document
        |
        +-- structural validator
        +-- command stack / undo / redo
        +-- structural diff
        +-- engine-family semantics
        |
        +-- AuthoringSnapshot --> Qt vertical timeline
        +-- PreviewSnapshot --> RouteResolver --> gameplay preview
```

The canonical model retains raw scalars, source spans, stable IDs, ordered
metadata, Splits, Blocks, rows, cells and envelope data. Compact source-backed
row tables are the default; sparse overlays promote only edited rows.

## Completed foundation

### Format laboratory and lossless core

Complete for the supplied corpus:

- NX20/NFO envelope classification and shared codec;
- 12,909-file byte-exact round-trip gate;
- compact/lazy row model and sparse overlays;
- raw scalar/source-span preservation;
- immutable commands and stable-ID allocation;
- structural validator and structural diff;
- atomic saves and parser/command mutation testing;
- Lightmap identification and publication handling.

Ongoing hardening, rather than missing format support, remains appropriate for
malformed-model and writer fuzzing.

### Importers and engine-family semantics

Implemented:

- NX10 importer with structured conversion diagnostics;
- complete supplied NX2 NX10 source-domain validation over 2,125 charts;
- 2,111 same-path official NXA NX20 successors used as semantic conversion
  evidence;
- all 110 observed nonzero NX10 note codes backed by successor evidence;
- exact Division projection across 18,769 aligned successor Blocks;
- one-way STF/ST2, NOT/NOT5, STX, SEE, KSF and UCS authoring imports;
- public authoring profiles for NXA, Fiesta and Prime+;
- scope-aware metadata registries with evidence labels;
- finalized Fiesta-and-later Header `1000..1008` semantics;
- guarded UTF-8 trailer-string editing and relocation for proven offset fields;
- raw preservation for unresolved or ambiguous values.

The NX10 full-corpus validation and SEE importer are therefore completed work,
not roadmap items.

### Folder/workspace layer

Implemented:

- non-recursive folder discovery with isolated failures;
- individual Save and guarded `Save All` planning;
- staged writes, stale-target detection and rollback;
- valid `LM.NX` publication gate and explicit blank Lightmap creation;
- NX file create/duplicate/delete tools;
- explicit NX10 materialization instead of implicit overwrite;
- recovery snapshots outside chart folders;
- NX/NFO mirror compare/export;
- automatic and manual audio discovery.

### Authoring viewport

Implemented:

- Qt vertical timeline with visible-row culling and stable geometry;
- note placement/deletion/drag editing;
- Tap, Hold, Roll, Item and Division tools;
- Split/Block insertion, removal, reordering and boundary resize;
- typed Block timing edits and chart-wide Start Time shifting;
- rectangular stable-ID selection;
- copy, cut, paste, erase, filtered replace, horizontal/vertical flip and
  StepEdit-compatible mirror;
- sparse bulk-note execution for responsive transforms;
- typed Split selection-byte editing and decoded mode/bank display;
- Hidden, Invisible, Appear, Vanish, VanishLow and AppearLow visualization;
- audio transport, compressed/staged waveform rendering and metronome;
- guarded `Save All` with validation and structural-diff preview.

### Advanced NX20 authoring

Implemented:

- ordered duplicate-preserving metadata editing;
- Brain Shower projection/editing for supported native fields;
- Split-selection and Division-condition route projection;
- mission-condition parser validated against supplied official NX2/NXA
  condition material;
- typed trailer-string editing where offsets/encoding are proven;
- previewed folder metadata/timing batches;
- explicit NX/NFO deployment mirror workflow.

Unknown metadata is intentionally raw-preserved. An unidentified field is not a
missing implementation merely because no safe typed editor exists.

### Gameplay preview

The gameplay preview is implemented and packaged. It is no longer an
"implementation candidate".

Delivered behavior includes:

- immutable `PreviewSnapshot` and route resolver;
- manual and internally randomized routes;
- synchronized external native Qt preview;
- Single/Half Double/Double field geometry;
- noteskin animation, STEPFX and pad input;
- runtime timing projection for Start Time/BPM/Beat Split/Scroll/Smooth/Skip;
- source-backed judgment timing, score, combo, grade and normal-mode gauge
  behavior for the audited runtime path;
- supported legacy modifier compatibility projections;
- F6 debug overlay with per-bank judgments, combo/MissCombo maxima, score,
  grade, gauge, clear state and item counters;
- deterministic local RNG where matching hidden engine-global RNG state is not
  required for authoring or diagnostic reproducibility;
- blocking diagnostics when a route/runtime state cannot be interpreted safely.

Pixel-perfect reproduction of asset-driven Animator/material effects is not a
product requirement when the corresponding official assets are unavailable.

## 0.9.5 hardening cycle

The current release scope is deliberately narrower than the preceding feature
cycles.

### 1. Documentation truth pass

- keep README, STATUS and ROADMAP synchronized with the actual tree;
- remove stale "not implemented" claims for completed import/trailer work;
- remove obsolete Phase 11 active-branch language;
- describe the gameplay preview as implemented rather than pending;
- separate remaining implementation from open reverse-engineering research;
- remove obsolete documentation for unsupported/non-public engine variants.

### 2. Performance regression suite

Especially protect the sparse selection paths introduced for 0.9.4:

- copy/cut/paste;
- horizontal/vertical flip;
- mirror;
- erase;
- filtered replace;
- bulk placement;
- selections spanning large source-backed charts.

Regression gates should detect accidental full-row/full-document
materialization, not only catastrophic wall-clock slowdowns.

### 3. Save/recovery torture tests

Add fault injection around:

- temporary-file creation;
- replacement/rename;
- multi-file staged writes;
- external modification between preflight and commit;
- partial/corrupt recovery payloads;
- permission failures and insufficient disk space where practical;
- interrupted save/recovery sequences.

### 4. Keyboard workflow audit

Frequent authoring operations should be practical without a mouse. Audit
navigation, selection, placement, transform, structure, metadata and preview
controls rather than merely counting how many shortcuts exist.

### 5. High-DPI/scaling pass

Validate at 100%, 125%, 150% and 200%, with particular attention to:

- timeline geometry and hit testing;
- noteskin rendering;
- dialogs and Inspector layouts;
- Split/Block gutters;
- external gameplay preview ownership/scaling;
- toolbar overflow and text clipping.

### 6. Editor UX cleanup

Review:

- context menus;
- selection feedback;
- Inspector state;
- redundant actions;
- disabled/enabled action logic;
- destructive-action confirmations;
- diagnostics and error messages.

## Remaining implementation after the 0.9.5 truth pass

The remaining implementation backlog is the hardening work above plus ongoing
low-risk maintenance discovered during testing. No new NX20 format family,
legacy importer, trailer encoding, or gameplay-debug subsystem is currently
required to complete the 0.9.5 scope.

A later 1.0 hardening phase should continue:

- deeper parser/writer/importer/command fuzzing;
- crash-recovery and interrupted-save coverage;
- corpus performance regression budgets;
- reproducible packaging/update policy;
- accessibility and keyboard-only workflows;
- high-DPI and localization infrastructure;
- documentation, original example files and release checklist.

## Open research, not implementation blockers

These items remain deliberately source-gated rather than guessed:

- NXA Brain Division 43..49 individual semantics;
- Fiesta 2 Brain Split metadata 11/12;
- discarded Prime 2 placeholder Split/Division fields;
- exact modern ZigZag consumer path beyond the validated historical projection;
- exact Animator/asset movement for modern Throw;
- exact Unity RNG stream for Random Velocity;
- exact Animator/material curves for Appear/Vanish;
- producer of `CommonModifier.SpeedBoost`;
- challenge-mode `HPBar.Add` branch;
- forced-judgment Division 999 consumer;
- any Split-level modifier dispatcher if one is eventually demonstrated;
- physical cabinet-light actuation from `LM.NX`.

These questions may improve runtime fidelity or historical understanding later.
They are not reasons to fabricate editor semantics and are not 0.9.5 release
blockers.

## Explicit non-goals

- World Max `mission.txt` editing. Mission files may serve as evidence for
  condition syntax, but mission topology/configuration is outside the NX/NFO
  document model.
- A dedicated cabinet-light visualizer. `LM.NX` remains a native publication
  document; hardware output research is separate.
- Redistribution of proprietary charts, executables, noteskins or game assets.

## Test strategy

### Unit/property tests

- raw scalar and source-span invariants;
- parser limits and diagnostics;
- rich/compact identity;
- sparse promotion and stable-ID preservation;
- command apply/undo/redo sequences;
- validator issue codes and paths;
- structural diff paths;
- timing/profile rules;
- importer conversion reports.

### Corpus gates

- 12,909 known NX20/NFO files remain byte-exact;
- all 2,125 supplied NX2 NX10 charts remain inside the frozen observed importer
  domain;
- 2,111 official successors remain recorded as semantic evidence rather than
  repository payloads;
- large-chart parse/memory/viewport and selection-transform performance remain
  within regression budgets.

### Release gates

- strict Windows test gate;
- Linux test/package gate;
- packaged smoke tests for authoring, audio, preview and save/recovery workflows;
- documentation version/state consistency check before tagging.
