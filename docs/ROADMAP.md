# StepNX Studio technical roadmap

Revision: 2026-08-24

Target: a lossless native NX20 desktop editor, not another converter wrapped in
a brittle GUI

## Product boundary

StepNX Studio uses a canonical NX20 model. NX and NFO are native documents;
NX10 and other legacy formats are one-way imports. A folder is the workspace
unit. No NXP sentinel or project sidecar exists.

The Qt application, authoring viewport, audio system, and gameplay preview are
consumers of the core. They do not parse or serialize charts independently.

## Non-negotiable engineering rules

1. No-edit round-trip is byte-exact.
2. Unknown means preserved, not zeroed, discarded, or guessed.
3. Metadata remains ordered and may contain duplicates.
4. Float bits remain authoritative until explicitly edited.
5. Semantics are contextual: global, split, and Division metadata are distinct.
6. Engine behavior belongs to explicit profiles.
7. Imports never silently replace or convert their source.
8. The canonical document is the only source of truth.
9. Every edit is a command with validation, undo, and structural diff support.
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
        +-- engine profile semantics
        |
        +-- AuthoringSnapshot --> Qt vertical timeline
        +-- PreviewSnapshot --> RouteResolver --> gameplay preview
```

### Canonical model

The model retains raw scalars, source spans, stable IDs, ordered metadata,
splits, blocks, rows, cells, and envelope data. Compact source-backed row tables
are the default. Sparse overlays promote only edited rows.

### Feature registry

Known metadata, note types, flags, conditions, and engine extensions live in
declarative registries keyed by scope and profile. A registry entry may add
labels, editors, constraints, and preview behavior; it may never erase raw data.

### Operations

Commands address entities by stable ID and return new documents. The current
minimum supports metadata values, block scalar fields, complete rows, note
cells, collection edits, field geometry, guarded trailer relocation, and folder
batch operations. New commands must define ID allocation, insertion anchors,
selection behavior, validation, and reversible payloads.

### Timeline

The timeline renders only visible rows. Geometry, hit testing, selection, and
beat/time conversion stay separate from Qt paint objects. Branches may be
switched or compared without modifying the document. The authoring timing line
is the exact row timestamp; note terminals and waveform projection share that
same coordinate.

### Audio

Audio playback, waveform generation, and metronome use a shared monotonic
transport. Timing transforms are deterministic and unit-testable. Compressed
waveform decoding uses the same source supplied to playback, including staged
ENC2 audio. Visual waveform summaries use a high-resolution multiresolution
min/max cache selected by visible time-per-pixel. Automatic BPM/offset analysis
reports candidates and confidence rather than applying hidden edits.

## Release phases

### Phase 0 — Charter and scope (complete)

- product identity and Apache-2.0;
- DCO contribution policy;
- Python/PySide6 baseline;
- native/import format policy;
- folder workspace and no-sidecar decision;
- proprietary-asset boundary.

### Phase 1 — Format laboratory (complete for the known corpus)

- audit StepEdit 5.63 and `nx_editor-v60.py` behavior;
- classify NX20/NFO envelopes;
- prove NFO shares the NX20 codec;
- classify 12 NX10 files embedded in NXA folders;
- prove implicit `columns == 3` Lightmap behavior;
- record executable path evidence for NXA, Fiesta 2, Prime 1, and Prime 2;
- establish the 12,909-file byte-exact gate.

Open research: fully type later-generation trailer fields and encodings.

### Phase 2 — Lossless core (current, mostly complete)

Delivered:

- bounded binary reader;
- raw scalar model and stable IDs;
- shared NX20/NFO parser and writer;
- exact envelope preservation;
- compact/lazy rows and sparse overlays;
- atomic save;
- CLI inspection and corpus verification;
- structural validator;
- immutable minimum command set;
- collection insert/remove/move commands;
- monotonic stable-ID allocation for new entities;
- undo/redo snapshots;
- structural diff;
- deterministic generated command-sequence tests and parser mutation fuzzing.

Remaining gates:

- deeper malformed-model and writer fuzzing as an ongoing hardening gate.

### Phase 3 — Importers and profile semantics (implemented; precision gates remain)

Delivered:

1. NX10 importer with a conversion report; official NX2 corpus/runtime
   equivalence remains a validation gate.
2. `nxa-native`, Fiesta 2, Prime 2, and patched-NXA metadata/capability
   registries with structural versus authoring validation.
3. Startup capability gating keeps the patched NXA profile out of normal editor
   profile choices while retaining its stable internal registry key.
4. Typed trailer views where evidence is sufficient, including guarded
   length-changing UTF-8 relocation for aligned proven string pools. Unknown or
   ambiguous pointers block relocation instead of being guessed.
5. Isolated one-way STF/ST2, NOT/NOT5, STX, SEE, KSF, and UCS authoring imports
   with structured diagnostics and explicit materialization.

Importer acceptance requires source preservation, a deterministic NX20 result,
and an explicit list of approximations or unsupported concepts.

### Phase 4 — Folder layer (implemented)

- open all immediate NX files and isolate per-file failures (implemented);
- individual save and `Save All` transaction planning (implemented);
- require a valid `LM.NX` for complete-folder publication (implemented);
- generate or reuse a StepEdit-compatible blank NX20 Lightmap through a
  previewable, explicitly executed save plan (implemented);
- discover/select audio without a project manifest (implemented);
- recovery journal and crash restoration outside the chart folder (implemented);
- NX/NFO mirror compare/export without automatic synchronization (implemented);
- create, duplicate, and delete workspace `.NX` files with unsaved-state guards
  and Lightmap protection (implemented);
- choose standard or custom chart field geometry without silently discarding
  occupied panels (implemented).

### Phase 5 — Read-only Qt viewport (complete)

- desktop shell, tabs, document tree, and diagnostics panel;
- vertical timeline inspired by StepEdit/STEPEdit-pixi;
- viewport culling on the 267,264-row stress chart;
- measure ruler, block headers, metadata/Division inspection;
- branch switching without mutation;
- custom redistributable glyphs and user-supplied local visual packs.

Delivered:

- immutable `AuthoringSnapshot` with contextual metadata and compact row
  preservation;
- Qt-independent geometry, hit testing, zoom, measure markers, active-block
  selection, and viewport culling;
- optional PySide6 shell with folder tree, tabs, diagnostics, inspection, and
  read-only timeline;
- original vector glyphs plus validated user-selected local PNG/SVG packs;
- synthetic 267,264-row culling benchmark and conditional offscreen Qt smoke
  test;
- full Windows 10 test-suite validation: 95 tests discovered, 94 passed, one
  expected case-insensitive-filesystem skip, and exit code 0;
- packaged Qt paint/scroll/zoom validation at 175.3 fps over 300 frames on
  Windows 10, passing both the 30 fps requirement and 60 fps target.

Performance gate: target 60 fps and require at least 30 fps during scroll/zoom on
the stress fixture without abandoning compact storage.

### Phase 6 — Practical visual editing (complete)

- note placement, deletion, drag, and typed item editing;
- block and split insertion/removal/move;
- timing, BPM, scroll, stop, warp, and smooth-speed tools;
- multi-selection and safe bulk operations;
- command coalescing for drag gestures;
- validation-before-save and structural diff preview;
- audio transport, waveform, metronome, snapping, and offset tools.

Delivered for validation:

- stable-row note placement and deletion, including promotion and recompaction
  of empty rows;
- typed tap, hold, item, and Division placement presets;
- click/drag painting with one undo step per gesture;
- atomic bulk-note command support used by the multi-selection UI;
- guarded Qt `Save All` with validation, target confirmation, structural diff,
  external-change detection, and the existing rollback path;
- bundled royalty-free static noteskin atlases and validated local overrides,
  with gameplay-only feedback assets catalogued but not coupled to the authoring
  renderer;
- dense-split viewport correction: square note targets, beat-relative wheel
  scrolling, timing-line-centered noteskin hold terminals, and a hold-head body
  underlay that removes the terminal/shaft gap;
- stable-ID Split/Block insertion, removal, reordering, and tree selection;
- atomic typed editing of every native Block timing scalar, optional direct
  Inspector editing, and chart-wide Start Time shifting including a toolbar
  relative-delta mode across every Split/branch;
- deterministic row/beat/millisecond projection based on explicit Block anchors;
- rectangular stable-ID selection, musical snapping, copy/paste, erase, mirror,
  filtered replace, and typed bulk placement;
- session audio transport, selection-or-viewport Play seeking, explicit offset,
  PCM-WAV plus Qt-decoded compressed/staged waveform generation, and an
  absolute-time metronome with per-beat and per-arrow modes;
- stereo signed min/max waveform summaries with a 16-frame base and a
  multiresolution pyramid queried according to visible time-per-pixel;
- monotonic live transport filtering that rejects delayed backend rewinds and a
  bounded metronome voice pool that avoids duplicate crossings and WAV cutoff
  clicks;
- StepEdit-compatible note function/visibility flag editing and visible snap
  guides;
- StepEdit-style fixed encoded-row geometry shared exactly by editing and
  playback, preserved viewport/zoom across Play/Pause, and non-obstructing
  side-gutter Block labels;
- compact Audio and Settings menus with conservative defaults.

This phase is where the project finally earns the word “editor.” Shipping a
pretty read-only timeline before commands are dependable would be a demo, not a
product.

### Phase 7 — Advanced NX20 authoring (complete)

- profile-aware Brain Shower metadata and question tooling;
- conditional branches and route visualization;
- patched-engine capabilities;
- typed mission-trailer strings/conditions where safe;
- batch operations across a folder;
- NFO deployment mirror workflow.

Delivered for validation:

- declarative metadata/capability registries for native NXA and the patched
  engine, with inheritance and explicit evidence levels;
- separate structural and profile-aware authoring validation;
- ordered metadata collection editing that retains duplicate order, stable IDs,
  unknown entries, and exact untouched scalar bytes;
- typed integer, float-bit, bitmask, enum, and packed-u16 range editors;
- Brain Shower projection and editing for confirmed IDs 11/12, 21–26, and
  31–34, while unidentified IDs 43–49 remain visible but raw-only;
- Split selection and Division-condition route projection with direct Qt branch
  navigation;
- a non-evaluating mission-condition parser covering arithmetic, comparisons,
  Boolean operators, rank constants, case variants, and patched variables;
- validation against every `CONDITION_1..4` expression in the supplied official
  NX2 and NXA mission text references;
- safe typed views of known trailer string offsets plus guarded length-changing
  relocation for the aligned UTF-8/NUL pool shape proven in later-engine corpus
  evidence; unterminated strings, invalid offsets, unknown encodings, and
  ambiguous unknown pointers remain blocked;
- write-free folder batch plans for global metadata and Start Time shifts, with
  explicit duplicate policy and Lightmap exclusion;
- GUI mirror comparison/export that keeps NX and NFO deployment roles explicit.

### Phase 8 — Gameplay simulator (implementation candidate; packaged gate pending)

- export a read-only `PreviewSnapshot`;
- manual route selection;
- deterministic seeded random routes;
- runtime autoplay and two-player pad input on one execution surface;
- one initialization dialog for `.NX` filename, 1x–9x, and COMMAND;
- speed keys, debug display, guide, seek, and runtime flags;
- unsupported-condition diagnostics;
- compare timing against NXA behavior;
- evaluate an independent web renderer versus a native Qt implementation;
- ship with no official artwork/JPAK assets.

Delivered for validation:

- immutable `PreviewSnapshot` projection that retains every Block branch and
  source-backed row collection without granting mutation access;
- explicit manual route choices, local seeded RNG, recorded route decisions,
  and deterministic all-perfect state for proven NXA condition counters;
- blocking diagnostics for missing choices, random ties without a seed,
  unsupported applause state, no-match routes, Lightmaps, and invalid timing;
- a runtime event stream anchored to each Block's explicit Start Time and BPM,
  with conservative warnings for unproven freeze, warp, and Scroll behavior;
- a native Qt renderer selected over a browser/WebPrime integration, avoiding a
  second parser and all unlicensed JPAK/runtime assets;
- synchronized audio time, continuous scroll geometry, animated supported
  noteskin frames, native five-pitch sequence-zone strips, remapped input/STEPFX
  feedback, Double's continuous ten-lane receptor pitch, a divider-free field,
  bounded recent feedback projection, original fallback shapes, and read-only
  preview tabs;
- composed chart visibility and COMMAND display behavior for Appear, Vanish,
  Invisible, Non-Step, Freedom, Flash, Mirror, Random, and Judge Reverse, with
  Ghost and Bonus/Hidden kept as distinct NX20 function families;
- the shared authoring metronome toggle and per-arrow/per-beat mode apply to the
  immutable snapshot of the active preview tab;
- a recorded PIUTESTER behavioral audit with a strict prohibition on copying
  its proprietary executable, scripts, DAT archives, manual text, or artwork;
- internally randomized route seeds, with random selection restricted to Splits
  whose flags request it and shared only by matching nonzero lower-five-bit
  banks; zero lower bits create independent random events;
- additive STEPFX composition for opaque RGB sheets that use black as the
  neutral background.

Exact judgment, grade, score, gauge, freeze, modifier-curve, and later-engine
behavior are not complete until independent NXA, Fiesta 2, and Prime captures
establish profile evidence. Local debug counters are labeled accordingly.

The preview comes after the authoring timeline and command model. A simulator on
top of unstable semantics is an attractive way to debug the wrong program.

### Phase 9 — Hardening and 1.0

- fuzz parser, writer, importers, and command sequences;
- crash-recovery and interrupted-save tests;
- corpus performance regression budgets;
- reproducible Windows packaging and update policy;
- accessibility, keyboard-only editing, high-DPI, and localization framework;
- documentation, example files using original data, and release checklist.

### Current development branch — Phase 11 close-out

The agreed implementation scope is complete. The active branch has additionally
closed the legacy-import GUI flow, SEE/UCS authoring import, workspace NX file
management, field geometry tools, sparse NX20 hold behavior, compressed/staged
precision waveform rendering, persistent external rendering preferences,
guarded trailer relocation in the Qt UI, patched-profile startup gating, timing
Inspector polish, and metronome transport jitter/cutoff fixes.

The remaining Phase 11 work is validation and integration rather than feature
implementation: run the strict Windows gate on the final HEAD, perform the final
manual smoke tests, record the result, and merge the branch.

### Separate track — mission text and World Max

`mission.txt` tooling may share registries and condition parsers, but it must not
contaminate NX20's binary model. It remains a separate codec/document type and
may ship after the minimum visual editor.

## Test strategy

### Unit and property tests

- every raw scalar and source-span invariant;
- parser limits and offset diagnostics;
- rich/compact identity;
- sparse promotion and stable-ID preservation;
- command apply/undo/redo sequences;
- validator issue codes and paths;
- structural diff paths;
- timing transforms and profile rules;
- import conversion reports.

### Corpus gates

- 12,909 known NX20/NFO files remain byte-exact;
- 12 NX10 files remain classified outside the NX20 codec;
- rich mode stays available as a reference;
- compact mode is the required performance/default gate;
- corpus payloads never enter the repository.

### Runtime gates

- NXA validates generated/edited native charts and blank Lightmaps;
- later-engine fixtures validate sized trailers and NFO deployment;
- patched-engine behavior is tested only under its explicit profile;
- every runtime test records executable identity and exact input artifact.

## Current priority queue

P0:

1. run the final strict Windows Phase 11 gate and manual smoke tests;
2. merge Phase 11 after the close-out record is clean.

P1:

1. validate the NX10 importer against the official NX2 corpus and runtime;
2. continue runtime evidence work for exact preview semantics.

P2:

1. deeper hardening/fuzzing and performance regression budgets;
2. remaining typed later-generation trailer fields where evidence becomes
   sufficient;
3. packaging, accessibility, keyboard-only editing, high-DPI, and localization
   work on the road to 1.0.

## Quality metrics

- zero unexplained byte differences in no-edit round-trip;
- no silent data loss in any command or importer;
- deterministic validation and diff paths;
- memory and parse-time regression budgets based on the stress chart;
- all public documentation in English;
- no proprietary assets or chart payloads in releases;
- every format/architecture change captured by tests and, when required, an ADR.
