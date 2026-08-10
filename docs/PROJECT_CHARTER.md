# StepNX Studio project charter

Version: 0.7

Date: 2026-08-10

Status: core product and governance decisions frozen

## Mission

Build a safe, lossless, native NX20 visual chart editor for Pump It Up. The
authoring workflow may learn from StepEdit 5.63, but the product must be
independent from its executable, code, artwork, NX10 limitations, and identity.

The editor is intended for substantial chart authoring, not merely repairs.
Opening and saving an unedited supported document must preserve every byte.
Unknown data must survive or produce a blocking diagnostic; it must never be
quietly normalized into a convenient lie.

## Frozen product decisions

- Product name: **StepNX Studio**.
- Native format: NX20, shared by NX and NFO.
- Default engine profile: `nxa-native`.
- License: Apache-2.0.
- Primary desktop target: Windows 10/11 x64.
- Implementation baseline: Python 3.11+, PySide6/Qt Widgets for the future GUI.
- Workspace unit: a folder containing immediate NX files.
- No `.NXP`, `.snxproj`, or equivalent project manifest.
- `LM.NX` is required only when `Save All` publishes a complete folder.
- Importers are one-way into the canonical NX20 model.
- Save never silently converts a source format or profile.
- Official game assets are excluded from repository and release artifacts.
- Core, CLI, documentation, and public API language is English.

## Identity

`StepNX Studio` describes the supported format without impersonating StepEdit or
an official Andamiro product. The application must always identify itself as
unofficial. A future logo and trademark policy must use original artwork.

Project releases credit Autumnal as creator and maintainer. Contributors retain
copyright in their work and are credited through Git history and release notes.

## License and contribution policy

All repository code is Apache-2.0. Contributions use `inbound = outbound`:
the contributor grants the same license received by users. There is no CLA and
no private maintainer relicensing grant.

Every commit must carry a Developer Certificate of Origin 1.1 sign-off. The DCO
records that the contributor may legally submit the work; it does not transfer
copyright.

The project may distribute source-only builds if binary distribution becomes
impractical. Telemetry is absent by default; any future telemetry requires an
ADR, explicit opt-in, and a documented data-retention policy.

## Intellectual-property hygiene

Behavior observed in executables and official charts may inform an independent
implementation. Decompiled code, extracted artwork, official music, chart
payloads, and other proprietary content must not be copied into the repository.

Third-party code requires:

- an Apache-2.0-compatible permissive license;
- preserved notices and source attribution;
- a recorded upstream commit;
- separation from third-party assets that the code author did not own.

STEPEdit-pixi may be studied as a layout reference, but code reuse requires a
compatible license from its copyright holders. WebPrime may be studied as a
behavioral reference, but its copyleft-licensed code and Andamiro assets are
excluded from the Studio and its releases.

## Platform and stack

The core remains GUI-independent. Qt must consume core snapshots and commands;
the codec must never require an event loop to prove a round-trip.

Planned stack:

- Python 3.11+;
- immutable dataclass-based canonical model;
- PySide6 and Qt Widgets for the desktop application;
- custom timeline rendering with viewport culling;
- standard-library CLI and tests wherever practical;
- independently implemented gameplay preview only after the core timeline model
  is stable.

The first stable release should favor a reproducible Windows x64 bundle. Linux
development support is welcome, but it is not allowed to delay the primary
runtime target.

## Format policy

### Native output

NX20 is the canonical editable and output format. NX and NFO share one codec;
their extension records deployment role. The model preserves later-generation
trailers and opaque tails without pretending they are fully understood.

### Import-only formats

NX10, STF, NOT/NOT5, STX, and SEE may be imported into a new NX20 document.
Import never overwrites the source and must produce a conversion report listing
approximations, dropped concepts, and unresolved choices.

NX10 import has priority because official NXA folders can mix NX10 and NX20.
The NX20 codec must reject NX10 cleanly instead of accepting it through loose
parsing.

### Engine profiles

Raw preservation is profile-independent. Semantic validation and feature labels
are profile-specific. The default `nxa-native` profile describes official NXA
behavior. 

### Folder workflow

`Open Folder` loads every immediate NX file, without recursion or a fixed slot
list. A bad file gets its own diagnostic and does not poison the remaining
documents. Audio may be discovered by convention or selected for the session.

Application state such as waveform caches, recovery journals, recent files,
window layout, and preview routes belongs in application storage, not beside
the charts in a fake project manifest.

`Save All` requires a valid `LM.NX`; the user may generate a blank NX20
Lightmap after confirmation. Existing Lightmaps are never silently replaced.
Individual NX and NFO saves remain independent from this folder requirement.

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

Length-changing trailer edits are forbidden until every affected offset is
typed or the operation can prove that unknown data remains valid.

## Timing and audio principles

The chart model is the source of truth. Waveform caches and rendered positions
are projections. Beat-to-time and time-to-pixel transforms must be testable
outside Qt and must explicitly handle BPM changes, stops, warps, scroll changes,
and engine-profile behavior.

Automatic BPM/offset detection is an assistive tool, never an authority. It
must return confidence and alternatives instead of silently rewriting timing.

## Data safety

- saving uses same-directory temporary files and atomic replacement;
- overwrite and backups are opt-in;
- imports never overwrite source documents;
- autosave/recovery data remains separate from deployable chart folders;
- unknown fields that would become invalid block the operation;
- bulk actions require a preview or structural diff before publication.

## View architecture

Only the core reads, mutates, and writes NX/NFO. The vertical authoring timeline
and gameplay preview receive read-only projections.

The authoring view sends stable-ID commands back to the core. The gameplay view
chooses a reproducible single route through branches using session state; it is
never allowed to modify the chart.

## Governance boundaries

The maintainer may review, merge, release, and enforce quality/IP policy. The
maintainer may not relicense third-party contributions under a proprietary
license without each copyright holder's permission.

Changes to these areas require an ADR:

- lossless model guarantees;
- native/output formats;
- license and contribution terms;
- default engine profile;
- telemetry and personal-data policy;
- silent conversion or normalization behavior;
- inclusion of a mandatory web/runtime dependency.

## Definition of 1.0

Version 1.0 requires:

- safe folder and individual-document workflows;
- byte-exact no-edit round-trip over the known corpus;
- typed editing of core NX20 timing, metadata, blocks, rows, and notes;
- dependable undo/redo and structural diff;
- NX10 import with an explicit report;
- practical StepEdit-level authoring workflow in the Qt timeline;
- tested blank `LM.NX` generation;
- clear diagnostics for unsupported or unsafe data;
- reproducible Windows packaging with no proprietary assets.

Mission-text tooling, exhaustive later-engine semantics, and a gameplay preview
may ship after the minimum editor if they would otherwise hold the core hostage.
