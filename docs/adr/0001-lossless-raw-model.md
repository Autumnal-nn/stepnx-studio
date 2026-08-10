# ADR 0001 — Lossless NX20 raw model

Status: accepted, 2026-08-10.

## Decision

Every serializable scalar preserves its original bytes and source span.
`RawF32` exposes a float view, but its bits remain authoritative. Metadata uses
ordered sequences, never maps. Padding, unknown flags, note cells, and unknown
tails remain raw. Internal stable IDs are not serialized.

The writer rebuilds the file from the tree. Returning `source_bytes` when no
edit is detected would be a fake round-trip proof and would hide model gaps.

## Consequences

The rich model costs more memory than a flat representation. Compact storage
may reduce that cost, but no optimization may weaken byte-exact preservation.
