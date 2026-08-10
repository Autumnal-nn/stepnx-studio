# ADR 0006 — Compact and lazy row storage

Status: accepted, 2026-08-10; amended after the editing command gate.

## Context

The initial model created an object for every row, cell, and source span. The
largest known chart has 267,264 rows; parse plus rebuild used 150.7 MiB and took
1.48 s. That representation is clear but does not scale to multiple tabs or a
viewport that inspects a narrow timeline window.

## Decision

`CompactRows` stores source-backed rows through packed numeric arrays of
offsets, kinds, and stable IDs. Indexing materializes a temporary `EmptyRow`,
`LightmapRow`, or `PackedNoteRow`; packed cells materialize only when accessed.

`OverlayRows` stores only rich replacements over an untouched `CompactRows`
base. Editing one cell promotes exactly one row. Serialization copies untouched
row ranges directly and emits replacement rows between them. Undo/redo keeps
immutable document snapshots that share the compact base.

Compact storage is now the parser and CLI default. Rich storage remains an
explicit reference/debug mode.

## Evidence

| Representation | Peak RSS | Parse + rebuild |
| --- | ---: | ---: |
| Rich | 150.7 MiB | 1.48 s |
| Compact | 31.3 MiB | 0.244 s |

Compact mode preserved observable stable IDs, source spans, and all bytes. The
full gate rebuilt 12,909/12,909 NX20/NFO documents exactly and classified the
expected 12 NX10 files separately.

## Consequences

- consumers must treat `block.rows` as a `Sequence`, never assume a tuple;
- viewport access no longer requires a full object graph;
- row promotion is explicit and testable;
- representation equality is not a substitute for structural equality.
