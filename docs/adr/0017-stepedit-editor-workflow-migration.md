# ADR 0017: STEPEdit-inspired editor workflow migration

Status: Proposed (StepNX Studio 1.0 milestone M1)
Date: 2026-10-26
Baseline: main at `9b75a27dae0d567b689214de7a19661130c9f048` (0.9.6b)

## Context

The STEPEditor 5.63 static analysis, supported by Coxed/REA/Ghidra evidence, identifies reusable interaction and viewport conventions. The current StepNX editor already has a lossless immutable NX20 model, stable row targeting, compact row storage, source-backed snapshots, branch projection, command history, and fast sparse note operations.

The analysis used local commit `d327c50` **plus uncommitted changes**; the GitHub baseline is 11 commits newer, and the local uncommitted delta has not been verified in the repository. In particular, do not assume the static-analysis working tree and published 0.9.6b are byte-identical.

## Decision

1. Retain `NX20Document`, codecs, importers, exporters, validator, folder workspace, save/recovery pipeline and `CommandStack` as authoritative systems.
2. Introduce a Qt-independent `EditorSession` for active branch choices, tool settings, hover/cursor/selection state, viewport configuration, and gesture lifecycle. The session is not serialized to NX20.
3. Introduce an `EditorController` adapter for authoring actions. Both frontends must issue equivalent intent operations through the same command/application services. Do not duplicate note/hold/resize semantics in the new widget.
4. Keep a stable identity for each target: document identity, Split/Block context, stable row ID and local lane. Validate gesture context before commit, particularly if the active branch or document changes.
5. Use an independent STEPEdit-inspired viewport policy. Preserve encoded BeatSplit, row count, BPM, time, Scroll, branch choices, raw metadata and all four note bytes. Geometry must never normalize document data. Keep existing viewport geometry available for comparison.
6. Implement explicit interaction profiles; the existing keyboard cursor workflow must remain usable. Do not infer tool identity from note-value equality or UI labels.
7. Draw gesture previews without mutating the document. Commit one atomic command (or an explicitly coalesced command sequence) per gesture; Escape, loss of capture, invalid context and document switches must not partially apply a gesture.
8. Preserve the indexed/sparse `phase11_fast_notes` behavior while extracting GUI-resident operations. Avoid full chart scans or snapshot rebuilds on each pointer event.
9. NX10 remains import-only and requires explicit target materialization. Unknown bytes and metadata are preserved instead of guessed.
10. Migrate incrementally: M1 baseline/contracts, M2 controller/session, M3 viewport, M4 gestures and advanced integration, M5 consolidation, M6 release candidate. Keep existing UI available until equivalence and manual usability gates pass.

## Terminology

| STEPEdit concept | StepNX concept |
| --- | --- |
| Sequential block region | Split |
| Alternative/division in that region | Selected Block |
| Chart/category | Document/tab |
| Note location | Stable row ID + lane, scoped to current document/Block |

`Block.divisions` is ordered metadata, **not** a second active-branch state container.

## M1 baseline gates

- Opening and serializing a native NX20 without edits must be byte-exact, including opaque data and raw scalar bits.
- Selecting or cycling active Blocks modifies only an authoring projection, not the document.
- Notes edited in one alternative cannot mutate another alternative.
- One bulk edit or one completed paint gesture is one undo boundary; undo/redo restores exact serialized bytes.
- Selection targeting stays stable when viewport zoom changes.
- Normal and Lightmap paths retain their original encodings and extra raw bytes.
- NX10 materialization remains explicit; structural Split resize preserves downstream timing and all alternative Blocks.
- Existing high-volume sparse selection/performance tests must continue to pass.
- Full Windows and Linux gates are required; the six new M1 baseline tests are **additional**, not substitutes. UI fidelity and runtime STEPEdit behavior remain unverified by these tests.

## Deferred decisions requiring manual or separate evidence

- Precise StepEdit keyboard mapping vs default Studio mapping; per-tool continuous Add/Erase/Special behavior.
- Subpixel dense-row hit-testing and accessibility fallback.
- Boundary-resize rejection/confirmation rules when rows contain notes, including alternative Blocks.
- STEPEdit Insert/Delete/Copy peculiarities are **not** automatically adopted.
- Pixel-level fidelity, external preview placement and full scope of advanced menus.

## Consequences

We add a thin application layer rather than rewriting the engine. The cost is a temporary compatibility adapter and two UI surfaces. Removing GUI wrappers too early would risk losing optimized fast-note editing, profile-aware composition, Lightmap support, and NX10 materialization.
