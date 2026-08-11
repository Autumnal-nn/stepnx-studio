# ADR 0009 — Collection commands and stable-ID allocation

Status: accepted, 2026-08-10.

## Context

Point edits can preserve an entity's parser-assigned stable ID, but insertion
needs a new identity. Recomputing every ID after a collection edit would break
selection, diagnostics, undo history, and view snapshots. Reusing an ID after
removal would make an old reference silently address a different entity.

Indexes are equally unsuitable as command targets: inserting one item changes
every later index. Metadata also permits duplicates, so a metadata ID/value pair
cannot identify one entry.

## Decision

`NX20Document.next_stable_id` is an editor-only monotonic allocation watermark.
The parser sets it one above the last assigned ID. Insert commands allocate from
the watermark and return a document with an advanced watermark. Remove and move
commands never decrement it.

Commands address existing entities and optional insertion anchors by stable ID.
`before_*_id=None` means append. An absent or cross-collection anchor is an
error, not a request to guess a nearby position.

The public collection commands cover:

- insert/remove/move for global, split, and Division metadata;
- insert/remove/move for splits;
- insert/remove/move for blocks, including movement between splits;
- insert/remove/move for rows, including movement between blocks.

Metadata moves remain within their current owner because changing global,
split, or Division scope changes semantics. Split moves remain within the
document. Block and row moves name their destination owner explicitly.

Insertions take a prototype entity and recursively clone it. Every entity in
the inserted subtree receives a fresh ID, every source span is cleared, and raw
scalar bytes remain unchanged. Allocation follows the parser's child-before-
parent order. Moves preserve the complete subtree and all its IDs.

Stored count scalars remain source evidence. Length-changing commands may leave
them stale in memory; validation reports a warning and the writer emits the
actual collection length, as already required by the lossless model.

## Consequences

- view selections and diagnostics survive reordering;
- deleted identities cannot alias later insertions in the same history branch;
- undo restores both the document and its allocation watermark;
- redo restores the exact previously allocated identities;
- copying a split or block cannot collide with IDs in the source subtree;
- command ordering is deterministic and independent of Python object identity;
- structural row edits currently materialize the affected compact row
  collection, while point row/cell edits retain sparse overlays.

The validator rejects a watermark that is not greater than every live stable
ID. Generated command-sequence tests repeatedly validate and serialize edited
documents, then prove complete undo and redo identity at the byte level.
