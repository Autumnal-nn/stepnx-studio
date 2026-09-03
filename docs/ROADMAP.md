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

The NX10 full-corpus validation and SEE importer are completed work, not roadmap
items.

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
- cross-Block/Split rectangular selection and bulk clipboard/transform behavior
  on the active Timeline route, using encoded row count rather than tick density
  as the row axis;
- sparse bulk-note execution for responsive transforms;
- source-backed selection reuses compact stable-row IDs instead of decoding
  complete Blocks before the operation starts;
- typed Split selection-byte editing and decoded mode/bank display;
- Hidden, Invisible, Appear, Vanish, VanishLow and AppearLow visualization;
- audio transport, compressed/staged waveform rendering and metronome;
- guarded `Save All` with validation and structural-diff preview;
- keyboard-first Timeline navigation, selection, placement and transforms with
  editor-context shortcut scoping;
- keyboard Workspace/Routes activation, structure/metadata access, pane focus,
  playback and shortcut help;
- native Qt `Ctrl+Tab` / `Ctrl+Shift+Tab` chart-tab behavior without a redundant
  StepNX `Ctrl+PageUp/PageDown` mapping;
- three-channel `LM.NX` Toggle/Select authoring with Cut/Copy/Paste/Delete and
  lossless preservation of the fourth raw row byte;
- Timeline/editor-field zoom presets from 100% through 300% in 25% increments,
  with Shift+wheel preset stepping and independent Ctrl+wheel precision zoom.

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

README, STATUS and ROADMAP were synchronized with the implemented tree; stale
"not implemented" claims and obsolete active-phase language were removed;
historical validation records remain explicitly historical.

### 2. Performance regression suite — complete

The sparse selection paths introduced/fixed for 0.9.4 are release-gated. The
deterministic fixture uses a 200,000-row compact/source-backed chart and executes
50, 500 and 5,000-cell cases for copy/cut/paste, horizontal/vertical flip,
StepEdit mirror, erase, filtered replace and bulk placement.

The primary contract rejects full `CompactRows`/`OverlayRows` iteration and caps
indexed row materialization as a function of selected work, not total chart
size. Shift-drag selection also reuses compact row IDs rather than decoding a
whole source-backed Block merely to build selection identity.

See `PERFORMANCE_REGRESSION_GATE.md`.

### 3. Save/recovery torture tests — complete

The durability pass covers stage creation, ENOSPC/fsync, original-backup copy,
partial commit interruption, later replacement failure, new-target rollback,
rollback failure and successful cleanup. Recovery fault injection covers hidden
staging creation/write/publish failures, catchable interruptions, orphan staging
and structurally invalid payloads whose manifest hashes were updated to match.

If rollback itself cannot restore an existing target, the `.stepnx-original`
backup is retained and surfaced rather than deleted by cleanup.

Checkpoint:

- Linux/glibc 2.31: 573 tests in 5.064 s, OK;
- Windows: 573 tests in 6.645 s, OK with one expected case-collision skip.

A deliberate boundary remains: ordinary filesystem renames cannot make an
entire multi-file `Save All` physically atomic against hard power loss or an
uncatchable process kill between target renames. A stronger guarantee would
require a persistent transaction journal and startup reconciliation.

See `SAVE_RECOVERY_TORTURE.md`.

### 4. Keyboard workflow audit — complete

The final workflow includes:

- stable-ID Timeline cursor navigation with arrows and Home/End;
- fixed-anchor/moving-edge Shift selection across visible Block/Split boundaries;
- row-count semantics independent of Beat Split, BPM or tick density;
- cross-Block Cut/Copy/Paste and playable transforms;
- direct `1..0` tool selection and N/H/G note-function selection;
- true Enter/Toggle behavior for single and multiple selections;
- Timeline-only Delete, Escape, Ctrl+C/X/V, X/Y/M and Space;
- `Alt+1..5` pane focus;
- native `Ctrl+Tab` / `Ctrl+Shift+Tab` chart switching;
- Workspace tree keyboard metadata/timing/Split/structure operations;
- Routes Enter activation;
- standard `Ctrl+S` Save All while retaining `Ctrl+Shift+S`;
- F1 shortcut discoverability;
- three-channel `LM.NX` Toggle/Select keyboard authoring and clipboard workflow.

The Lightmap row model is backed by **2,896,556 audited rows** across NXA,
Fiesta 2 and Prime 2. Bytes 0..2 are exclusively binary `00`/`01`; byte 3 is
always `00`. StepNX authors the proven three lights and preserves the unresolved
fourth byte.

Automated checkpoint:

- Linux/glibc 2.31: **597 tests in 4.950 s, OK**;
- Windows: **597 tests in 7.161 s, OK**, with one expected skip.

The subsequent real Windows item-5 authoring work exercised the corrected
keyboard/Lightmap workflow and closed the manual re-smoke requirement.

See `KEYBOARD_WORKFLOW_AUDIT.md` and `LIGHTMAP_AUTHORING.md`.

### 5. Editor-field scaling pass — complete

The 0.9.5 scope is editor-field zoom, not application-wide DPI scaling.
`View > Editor zoom` exposes the full 100%..300% matrix in 25% increments.
Timeline row/lane/ruler/info geometry, waveform, notes, Lightmap lights,
selection and hit testing scale from the same geometry while the surrounding Qt
application chrome remains unchanged.

- Ctrl+wheel remains vertical timing-precision zoom.
- Shift+wheel steps the field zoom by one preset.
- Alt+wheel is not intercepted. The initial Alt binding was retired after real
  Windows use showed Qt/native horizontal scrolling could consume it.

Item-5 checkpoint:

- Windows: **610 tests in 6.240 s, OK**, with one expected skip;
- Linux/glibc 2.31: full suite, OK;
- manual Windows validation covered the baseline and all eight additional
  presets through 300%.

See `HIGH_DPI_SCALING_GATE.md`.

### 6. Editor UX cleanup — implementation complete, final gate pending

The consistency pass covers:

- Workspace context menus reusing canonical actions where semantics match;
- specialized Timeline structure commands retaining row/viewport semantics but
  using consistent overlapping labels and destructive wording;
- richer rectangular/sparse/cross-Block selection feedback;
- Flip/Mirror/Paste enabled state matching actual applicability;
- note-only controls visibly disabled in Lightmap;
- direct Routes selector terminology without post-render text replacement;
- Inspector scope refresh/clear behavior after timing/metadata/structure edits;
- stale Division-metadata target rejection after switching charts;
- chart-field state following the actual Workspace-selected document;
- F1 and View-menu shortcut truth;
- Timeline Remove Block confirmation aligned with the canonical Structure flow;
- Shift+wheel Editor zoom replacing the ineffective Alt+wheel binding found in
  real Windows use.

Item 6 adds **22 focused regressions** over the 610-test item-5 checkpoint. The
strict Windows discovery floor is now **632**.

The remaining closure work is the full 632-test automated gate plus the focused
manual smoke in `EDITOR_UX_CLEANUP_AUDIT.md`.

## Remaining implementation for 0.9.5

No new NX20 format family, legacy importer, trailer encoding, gameplay-debug
subsystem, selection-performance subsystem, save/recovery subsystem, keyboard
workflow or scaling subsystem is currently required to complete 0.9.5. The
remaining work is validation/fix fallout from item 6 and release packaging/doc
consistency.

A later 1.0 hardening phase should continue:

- deeper parser/writer/importer/command fuzzing;
- crash-recovery coverage beyond the 0.9.5 fault matrix, including evaluating a
  persistent multi-file transaction journal and restart-time reconciliation;
- broader corpus performance regression budgets outside ordinary selection
  transforms;
- reproducible packaging/update policy;
- broader accessibility and assistive-technology validation;
- application-wide DPI/localization infrastructure;
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
- physical cabinet-light actuation from `LM.NX`;
- semantic meaning, if any, of a future nonzero fourth Lightmap row byte.

These questions may improve runtime fidelity or historical understanding later.
They are not reasons to fabricate editor semantics and are not 0.9.5 release
blockers.

## Explicit non-goals

- World Max `mission.txt` editing. Mission files may serve as evidence for
  condition syntax, but mission topology/configuration is outside the NX/NFO
  document model.
- A physical cabinet-light simulator. `LM.NX` has native three-channel cell
  authoring, but hardware output research is separate.
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
- save/recovery fault injection and rollback invariants;
- keyboard cursor/selection semantics, shortcut scoping and tree dispatch;
- cross-Block row-order clipboard/transform semantics;
- three-channel Lightmap authoring and fourth-byte preservation;
- editor-field geometry/hit-test agreement across every zoom preset;
- context-menu/action-state/Inspector/help consistency;
- no full compact-row iteration during ordinary sparse editing.

### Corpus gates

- 12,909 known NX20/NFO files remain byte-exact;
- all 2,125 supplied NX2 NX10 charts remain inside the frozen observed importer
  domain;
- 2,111 official successors remain recorded as semantic evidence rather than
  repository payloads;
- 2,896,556 supplied Lightmap rows support the three-channel authoring contract;
- large-chart parse/memory/viewport and selection-transform performance remain
  within regression budgets.

### Release gates

- strict Windows test gate with a **632-test minimum discovery floor**;
- Linux full-suite/package gate on the glibc 2.31 baseline;
- focused manual Windows UX smoke before item 6 closure;
- packaged smoke tests for authoring, audio, preview, keyboard, scaling and
  save/recovery workflows;
- documentation version/state consistency check before tagging.
