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
- atomic single-file and staged multi-file saves with stale-target checks;
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
- staged writes, stale-target detection and catchable-failure rollback;
- rollback-failure preservation of the original backup;
- valid `LM.NX` publication gate and explicit blank Lightmap creation;
- NX file create/duplicate/delete tools;
- explicit NX10 materialization instead of implicit overwrite;
- recovery snapshots outside chart folders with hidden pre-publication staging;
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
- source-backed rectangle selection reuses compact stable-row IDs instead of
  decoding the complete Block before the operation starts;
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

### 1. Documentation truth pass — complete

- README, STATUS and ROADMAP synchronized with the implemented tree;
- stale "not implemented" claims removed for completed import/trailer work;
- obsolete Phase 11 active-branch language converted to historical records;
- gameplay preview documented as implemented rather than pending;
- remaining implementation separated from open reverse-engineering research;
- old validation documents marked as historical snapshots where appropriate.

### 2. Performance regression suite — complete

The sparse selection paths introduced/fixed for 0.9.4 are now release-gated.
The deterministic fixture uses a 200,000-row compact/source-backed chart and
executes 50, 500 and 5,000-cell cases for:

- copy/cut/paste;
- horizontal/vertical flip;
- StepEdit-compatible mirror;
- erase;
- filtered replace;
- bulk placement;
- source-backed rectangle-selection row-ID acquisition.

The primary contract rejects full `CompactRows`/`OverlayRows` iteration and caps
indexed row materialization as a function of selected work, not total chart
size. The existing 50-note / 200,000-row one-second test remains a secondary
wall-clock alarm.

The audit also found and removed one transaction-prefix O(chart) path: Shift-drag
selection previously decoded every row in the active Block merely to collect
stable IDs. The installed timeline path now reuses the compact row-ID array.

See `PERFORMANCE_REGRESSION_GATE.md`.

### 3. Save/recovery torture tests — complete

The save/recovery layer now has an explicit fault-injection matrix rather than
only happy-path and ordinary rollback coverage.

Save-side torture cases cover:

- temporary stage creation failure;
- `ENOSPC`/`fsync` failure while staging a payload;
- original-backup copy failure;
- Python-level interruption after an earlier file has already been replaced;
- later replacement failure and rollback of earlier commits;
- rollback of a newly created target;
- rollback replacement failure;
- successful transaction cleanup.

The resulting durability rules are:

- stage and backup paths are registered before I/O that may fail;
- catchable interruptions run rollback before propagating;
- successful rollback restores prior targets and removes transaction debris;
- if rollback itself cannot restore an existing target, the
  `.stepnx-original` backup is retained and its filename is surfaced in the
  error rather than being deleted by cleanup.

Recovery-side torture cases cover:

- recovery staging creation failure;
- payload/manifest write and `fsync` failure;
- interruption during manifest publication;
- final staging-to-snapshot rename failure;
- orphan hidden staging after an uncatchable crash;
- SHA/path/provenance rejection from the existing recovery suite;
- structurally corrupt NX20 whose manifest hash nevertheless matches the bad
  bytes.

`RecoveryStore.list()` exposes only finalized 32-character lowercase-hex
snapshot directories containing a manifest, so crash staging is never presented
as a valid recovery point.

Validation checkpoint for the combined 0.9.5 gates:

- Linux/glibc 2.31: 573 tests in 5.064 s, OK;
- Windows: strict gate accepted 573 tests in 6.645 s with one expected
  case-collision skip;
- the Windows discovery floor is 573: 551 tests from the 0.9.4 release, nine
  selection-performance regressions, and thirteen save/recovery torture tests.

A deliberate boundary remains: ordinary filesystem renames cannot make an
entire multi-file `Save All` physically atomic against hard power loss or an
uncatchable process kill between target renames. Catchable failures are rolled
back, but ACID-like restart recovery across that boundary would require a
persistent transaction journal and startup reconciliation. 0.9.5 does not claim
that stronger guarantee.

See `SAVE_RECOVERY_TORTURE.md`.

### 4. Keyboard workflow audit — next

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

## Remaining implementation after completed 0.9.5 items 1-3

The remaining implementation backlog is keyboard/high-DPI validation, editor UX
cleanup, and low-risk maintenance found while exercising those gates. No new
NX20 format family, legacy importer, trailer encoding, gameplay-debug subsystem,
selection-performance subsystem, or catchable-failure save/recovery subsystem is
currently required to complete the 0.9.5 scope.

A later 1.0 hardening phase should continue:

- deeper parser/writer/importer/command fuzzing;
- crash-recovery coverage beyond the 0.9.5 fault matrix, including evaluating a
  persistent multi-file transaction journal and restart-time reconciliation;
- broader corpus performance regression budgets outside ordinary selection
  transforms;
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
- importer conversion reports;
- deterministic source-backed selection/materialization budgets;
- save/recovery fault injection and rollback invariants.

### Corpus gates

- 12,909 known NX20/NFO files remain byte-exact;
- all 2,125 supplied NX2 NX10 charts remain inside the frozen observed importer
  domain;
- 2,111 official successors remain recorded as semantic evidence rather than
  repository payloads;
- large-chart parse/memory/viewport and selection-transform performance remain
  within regression budgets.

### Release gates

- strict Windows test gate with a 573-test minimum discovery floor;
- Linux full-suite/package gate on the glibc 2.31 baseline;
- packaged smoke tests for authoring, audio, preview and save/recovery workflows;
- documentation version/state consistency check before tagging.
