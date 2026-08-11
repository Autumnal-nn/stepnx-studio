# ADR 0011 — Folder workspace, publication planning, and recovery

Status: accepted

Date: 2026-08-11

## Context

NXA deploys a song as a directory of NX documents rather than through an NXP
project manifest. A damaged chart must not prevent the other charts in that
directory from opening. Conversely, publishing a complete folder without a
valid `LM.NX`, silently converting an NX10 source, or overwriting a file changed
by another program would turn a convenient folder abstraction into a data-loss
feature.

NFO files share the NX20 codec but occupy a separate deployment location and
role. Audio is not present beside charts in the analyzed NXA dump. Editor state,
audio selection, and crash recovery therefore cannot be smuggled into the chart
directory as a private manifest.

## Decision

`stepnx.workspace` owns the folder workflow above the native codec and NX10
importer.

Opening a workspace:

- enumerates only immediate files whose suffix is case-insensitively `.NX`;
- accepts arbitrary filenames instead of a fixed chart-slot table;
- reports each parse, import, or I/O failure independently;
- rejects symbolic-link documents so a folder save cannot escape through a
  disguised target;
- reports case-colliding names as unsafe for the primary Windows target;
- imports NX10 into a canonical NX20 document while retaining its distinct
  import-only source status;
- discovers immediate MP2, MP3, WAV, OGG, and FLAC candidates without decoding
  them or asserting engine compatibility;
- keeps an explicitly selected audio path in session state only.

`Save All` is a two-stage operation. Planning validates every open model,
requires an exact-case structurally valid `LM.NX`, rejects unresolved file
failures, requires every NX10 import to name an explicit NX20 materialization
target, confines
all bulk targets to immediate files in the workspace, serializes payloads, and
records the expected state of every target. Execution refuses a target that
changed after planning, stages every payload first, and uses atomic replacement
for each file.

No filesystem transaction can atomically replace several independent files.
The executor therefore retains staged originals until all replacements finish
and attempts rollback if a later replacement fails. This is explicit
best-effort multi-file rollback, not a fictional cross-file atomic commit.

Recovery snapshots are stored under application state, never in or below the
chart folder. A snapshot contains only modified canonical NX20 payloads plus a
versioned JSON manifest with source path, source format, output path, and SHA-256
provenance. The manifest is written last. Loading verifies safe relative payload
names and hashes before parsing any recovered document. Restoration returns
documents to the caller or reapplies them to a matching workspace in memory
only after source path, format, and hash checks. It does not overwrite
deployment files automatically.

NX/NFO comparison and export are explicit operations. Opening a folder never
loads, rewrites, or synchronizes an NFO mirror behind the user's back.

Blank `LM.NX` generation reproduces the layout identified through two
controlled StepEdit 5.63 outputs: one split, one block, 4/4, BeatSplit 2,
default scroll 0.5, 400 zeroed Lightmap rows, and an explicit BPM. Synthetic
NX10 references match both outputs byte for byte at 150 and 180 BPM, and their
NX20 import projections match the native NX20 generator byte for byte.

Generation is an idempotent ensure operation. A valid exact-case `LM.NX` is
reused unchanged. A missing file receives a previewable create plan and is
written only after explicit execution. An unreadable, wrong-layout, or
case-colliding Lightmap blocks generation for explicit repair; it is never
replaced by a blank document. Future importers whose source formats embed light
events must merge them into the loaded Lightmap through a reviewed edit/diff,
creating a Lightmap only when none exists.

## Consequences

- the future Qt shell can display partial folders instead of failing as one
  opaque project;
- individual saves remain independent of the complete-folder Lightmap gate;
- NX10 sources cannot survive bulk publication accidentally: every import must
  be materialized explicitly as NX20, and in-place replacement is permitted
  only when the caller names the source path as the conversion target;
- external changes between edit and save are detected before replacement;
- crash artifacts and audio choices do not pollute game folders;
- NFO deployment remains deliberate and reviewable;
- generated Lightmaps share the same stale-target and atomic single-file
  execution guarantees as every other save plan.
