# StepNX Studio project charter

Version: 0.8

Date: 2026-09-02

Status: core product and governance decisions frozen; implementation-state
language amended for the 0.9.5 documentation truth pass

## Mission

Build and maintain a safe, lossless, native NX20 visual chart editor for Pump It
Up. The authoring workflow may learn from StepEdit 5.63 and other historical
tools, but the product remains independent from their executable code, artwork,
format limitations, and identity.

The editor is intended for substantial chart authoring, not merely repairs.
Opening and saving an unedited supported document must preserve every byte.
Unknown data must survive or produce a blocking diagnostic; it must never be
quietly normalized into a convenient lie.

## Frozen product decisions

- Product name: **StepNX Studio**.
- Native format: NX20, shared by NX and NFO.
- Default authoring family: NXA (`nxa-native`).
- Public authoring families: NXA, Fiesta, and Prime+.
- License: Apache-2.0.
- Primary desktop target: Windows 10/11 x64.
- Implementation baseline: Python 3.11+, PySide6/Qt Widgets.
- Workspace unit: a folder containing immediate NX files.
- No `.NXP`, `.snxproj`, or equivalent project manifest.
- `LM.NX` is required only when `Save All` publishes a complete folder.
- Importers are one-way into the canonical NX20 model.
- Save never silently converts a source format or engine family.
- Official game assets are excluded from repository and release artifacts.
- Core, CLI, documentation, and public API language is English.

## Identity

`StepNX Studio` describes the supported format without impersonating StepEdit or
an official Andamiro product. The application must always identify itself as
unofficial. Branding and artwork used by the project must be original or
redistributable under documented terms.

Project releases credit Autumnal as creator and maintainer. Contributors retain
copyright in their work and are credited through Git history and release notes.

## License and contribution policy

All repository code is Apache-2.0. Contributions use `inbound = outbound`: the
contributor grants the same license received by users. There is no CLA and no
private maintainer relicensing grant.

Every contribution must comply with the repository's DCO policy. The DCO records
that the contributor may legally submit the work; it does not transfer
copyright.

Telemetry is absent by default. Any future telemetry requires an ADR, explicit
opt-in, and a documented data-retention policy.

## Intellectual-property hygiene

Behavior observed in executables and official charts may inform an independent
implementation. Decompiled code, extracted artwork, official music, chart
payloads, and other proprietary content must not be copied into the repository.

Third-party code requires:

- an Apache-2.0-compatible permissive license;
- preserved notices and source attribution;
- a recorded upstream source/commit where applicable;
- separation from third-party assets that the code author did not own.

STEPEdit-pixi may be studied as a layout reference, but code reuse requires a
compatible license from its copyright holders. WebPrime may be studied as a
behavioral reference, but its copyleft-licensed code and Andamiro assets are
excluded from the Studio and its releases. PIUTESTER remains a private
behavioral reference only and is never redistributed or incorporated.

## Platform and stack

The core remains GUI-independent. Qt consumes core snapshots and commands; the
codec never requires an event loop to prove a round-trip.

Current stack:

- Python 3.11+;
- immutable dataclass-based canonical model;
- PySide6 and Qt Widgets for the desktop application;
- custom vertical timeline rendering with viewport culling;
- standard-library CLI and tests wherever practical;
- native Qt gameplay preview consuming immutable runtime projections;
- PyInstaller-based Windows packaging and a Linux package path in the release
  workflow.

Windows remains the primary desktop target. Linux packaging/development is
supported without changing the Windows-first authoring/runtime requirements.

## Format policy

### Native output

NX20 is the canonical editable and output format. NX and NFO share one codec;
their extension records deployment role. The model preserves later-generation
trailers and opaque tails without inventing semantics for unknown data.

### Import-only formats

NX10 and supported legacy formats are imported into new/materialized NX20
documents. Current one-way importer coverage includes NX10, STF/ST2, NOT/NOT5,
STX, SEE, KSF/KIU, and UCS, plus shared legacy semantic projections where
applicable.

Import never overwrites the source implicitly and must report approximation,
unsupported constructs, or unresolved choices. The native NX20 codec rejects
NX10 cleanly instead of accepting it through loose parsing.

The supplied NX2 NX10 domain has been audited separately over 2,125 charts, with
2,111 same-path official NXA NX20 successors used as semantic evidence. This is
an implementation result, not a relaxation of the import-only policy.

### Engine-family semantics

Raw preservation is engine-family independent. Semantic validation, labels,
constraints and runtime projections are contextual. The public authoring
families are:

- NXA (`nxa-native`);
- Fiesta (`fiesta2`) for Fiesta / Fiesta EX / Fiesta 2;
- Prime+ (`prime2`) for Prime / Prime 2 / XX / Phoenix / R!SE and compatible
  modern successors.

A numeric metadata ID by itself is never enough to establish meaning across
Header, Split, Division, or engine-family boundaries.

### Folder workflow

`Open Folder` loads every immediate NX file without recursion or a fixed slot
list. A bad file receives an isolated diagnostic and does not poison the
remaining documents. Audio may be discovered by supported conventions or
selected for the session.

Application state such as waveform caches, recovery journals, recent files,
window layout, local visual preferences, and preview state belongs in
application storage, not beside charts in a fake project manifest.

`Save All` requires a valid `LM.NX`; the user may generate a blank NX20 Lightmap
after confirmation. Existing Lightmaps are never silently replaced. Individual
NX/NFO saves remain independent from this folder publication requirement.

## Lossless contract

The canonical model must preserve:

- original scalar bytes and float bit patterns;
- ordered metadata, including duplicates and composite IDs;
- unknown flags, padding, note subtypes, and row markers;
- source spans and stable internal IDs;
- complete trailers and opaque tails;
- distinctions among empty, note, and Lightmap rows.

The writer rebuilds the tree; it may not return original source bytes as a
shortcut. Counts are recalculated only when collection length changes.

Length-changing trailer edits are allowed only through the guarded relocation
path for proven trailer strings. Every affected known offset must be updated
safely, aliases preserved, and ambiguous untyped pointer-like values may block
relocation rather than being guessed.

## Timing, audio, and preview principles

The chart model is the source of truth. Waveforms, authoring geometry, gameplay
positions, judgments, score, gauge, and route execution are projections. Timing
and runtime transforms must be testable outside Qt where practical and must keep
storage semantics separate from engine behavior.

Automatic BPM/offset detection, if used, is assistive rather than authoritative;
it must return candidates/confidence instead of silently rewriting timing.

The gameplay preview is read-only with respect to NX/NFO. It consumes an
immutable `PreviewSnapshot`, chooses one execution route through session state,
and never becomes a second parser or writer. Source-backed runtime semantics may
be improved as executable evidence becomes available without weakening the
lossless codec.

## Data safety

- saving uses same-directory temporary files and guarded replacement;
- imports never overwrite source documents implicitly;
- recovery data remains separate from deployable chart folders;
- unknown fields that would become invalid block the operation;
- bulk/folder actions use preview, validation, or structural diff before
  publication;
- stale external targets block guarded save rather than being overwritten.

## View architecture

Only the core reads, mutates, and writes NX/NFO. The vertical authoring timeline
and gameplay preview receive read-only projections.

The authoring view sends stable-ID commands back to the core. The gameplay view
chooses one route through branches using session/runtime state and cannot modify
the chart.

## Governance boundaries

The maintainer may review, merge, release, and enforce quality/IP policy. The
maintainer may not relicense third-party contributions under a proprietary
license without each copyright holder's permission.

Changes to these areas require an ADR:

- lossless model guarantees;
- native/output formats;
- license and contribution terms;
- default/public engine-family policy;
- telemetry and personal-data policy;
- silent conversion or normalization behavior;
- inclusion of a mandatory web/runtime dependency.

## Definition of 1.0

Version 1.0 requires a hardened, dependable form of capabilities that already
largely exist in 0.9.x:

- safe folder and individual-document workflows;
- byte-exact no-edit round-trip over the known corpus;
- typed editing of core NX20 timing, metadata, blocks, rows, and notes;
- dependable undo/redo and structural diff;
- NX10 and legacy import with explicit diagnostics;
- practical StepEdit-level authoring workflow in the Qt timeline;
- tested `LM.NX` publication/generation behavior;
- clear diagnostics for unsupported or unsafe data;
- reproducible packaging with no proprietary assets;
- regression coverage for performance, recovery, keyboard workflow, high-DPI,
  and other release-hardening concerns tracked by the current roadmap.

Gameplay preview, later-engine runtime research, and historical metadata
archaeology may continue to improve beyond 1.0. They do not redefine the native
NX20 lossless/editor contract.
