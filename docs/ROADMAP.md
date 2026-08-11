# StepNX Studio technical roadmap

Revision: 2026-08-11

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

Known metadata, note types, flags, conditions, and engine extensions will live
in declarative registries keyed by scope and profile. A registry entry may add
labels, editors, constraints, and preview behavior; it may never erase raw data.

### Operations

Commands address entities by stable ID and return new documents. The current
minimum supports metadata values, block scalar fields, complete rows, and note
cells. Future collection commands must define ID allocation, insertion anchors,
selection behavior, validation, and reversible payloads.

### Timeline

The timeline will render only visible rows. Geometry, hit testing, selection,
and beat/time conversion stay separate from Qt paint objects. Branches may be
switched or compared without modifying the document.

### Audio

Audio playback, waveform generation, and metronome use a shared monotonic
transport. Timing transforms must be deterministic and unit-testable. Automatic
BPM/offset analysis reports candidates and confidence rather than applying
hidden edits.

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
- structural diff.
- deterministic generated command-sequence tests and parser mutation fuzzing.

Remaining gates:

- deeper malformed-model and writer fuzzing as an ongoing hardening gate.

### Phase 3 — Importers and profile semantics (current)

1. NX10 importer with a conversion report (implemented; official NX2 corpus
   validation pending).
2. `nxa-native` metadata/flag registry.
3. Patched NXA extension registry without collisions.
4. Structural versus authoring validation levels.
5. Typed trailer views where evidence is sufficient.
6. Later importers: STF, NOT/NOT5, STX, and SEE.

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
- NX/NFO mirror compare/export without automatic synchronization (implemented).

### Phase 5 — Read-only Qt viewport

- desktop shell, tabs, document tree, and diagnostics panel;
- vertical timeline inspired by StepEdit/STEPEdit-pixi;
- viewport culling on the 267,264-row stress chart;
- measure ruler, block headers, metadata/Division inspection;
- branch switching without mutation;
- custom redistributable glyphs and user-supplied local visual packs.

Performance gate: target 60 fps and require at least 30 fps during scroll/zoom on
the stress fixture without abandoning compact storage.

### Phase 6 — Practical visual editing

- note placement, deletion, drag, and typed item editing;
- block and split insertion/removal/move;
- timing, BPM, scroll, stop, warp, and smooth-speed tools;
- multi-selection and safe bulk operations;
- command coalescing for drag gestures;
- validation-before-save and structural diff preview;
- audio transport, waveform, metronome, snapping, and offset tools.

This phase is where the project finally earns the word “editor.” Shipping a
pretty read-only timeline before commands are dependable would be a demo, not a
product.

### Phase 7 — Advanced NX20 authoring

- profile-aware Brain Shower metadata and question tooling;
- conditional branches and route visualization;
- patched-engine capabilities;
- typed mission-trailer strings/conditions where safe;
- batch operations across a folder;
- NFO deployment mirror workflow.

### Phase 8 — Gameplay preview

- export a read-only `PreviewSnapshot`;
- manual route selection;
- deterministic seeded random routes;
- profile-specific all-perfect autoplay state;
- unsupported-condition diagnostics;
- compare timing against NXA behavior;
- evaluate an independent web renderer versus a native Qt implementation;
- ship with no official artwork/JPAK assets.

The preview comes after the authoring timeline and command model. A simulator on
top of unstable semantics is an attractive way to debug the wrong program.

### Phase 9 — Hardening and 1.0

- fuzz parser, writer, importers, and command sequences;
- crash-recovery and interrupted-save tests;
- corpus performance regression budgets;
- reproducible Windows packaging and update policy;
- accessibility, keyboard-only editing, high-DPI, and localization framework;
- documentation, example files using original data, and release checklist.

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

1. validate the NX10 importer against the official NX2 corpus and runtime;
2. `nxa-native` registry and authoring validation.

P1:

1. read-only Qt viewport;
2. audio transport and timing projection;
3. practical note/timing editing;
4. authoring validator.

P2:

1. advanced NX20 and patched-engine tooling;
2. typed mission trailer editor;
3. gameplay preview;
4. remaining legacy importers.

## Quality metrics

- zero unexplained byte differences in no-edit round-trip;
- no silent data loss in any command or importer;
- deterministic validation and diff paths;
- memory and parse-time regression budgets based on the stress chart;
- all public documentation in English;
- no proprietary assets or chart payloads in releases;
- every format/architecture change captured by tests and, when required, an ADR.
