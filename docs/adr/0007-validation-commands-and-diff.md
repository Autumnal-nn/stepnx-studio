# ADR 0007 — Validation, commands, history, and structural diff

Status: accepted, 2026-08-10.

## Context

Direct dataclass replacement is useful for codec tests but is a rotten public
editing API. It provides no stable place to enforce type rules, preserve sparse
storage, build undo history, or explain what changed.

## Decision

Edits are immutable commands addressed by stable ID. The first command set
covers metadata values, block scalar fields, complete rows, and individual note
cells. A command returns a new document and never mutates source-backed bytes.

`CommandStack` stores immutable document snapshots for undo/redo. Compact row
edits produce `OverlayRows`, preserving the base and promoting only touched
rows.

Structural validation is independent from parsing and serialization. Errors
identify unrepresentable model states; warnings identify stale raw counts that
the writer can safely recalculate.

Structural diff compares serializable fields by document position and reports
stable paths. Source spans and stable IDs are identity/navigation data and do
not themselves count as serialized changes.

## Consequences

- the GUI can issue commands without owning binary-format logic;
- undo restores the original byte-exact document after a reversible edit;
- validation can run before save and report multiple issues at once;
- CLI diff reports both the first binary mismatch and structural paths;
- collection insertion/removal still requires a future ID-allocation policy.
