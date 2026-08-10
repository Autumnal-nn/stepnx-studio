# ADR 0002 — One NX20 codec for NX and NFO

Status: accepted, 2026-08-10.

## Decision

NX and NFO use the same NX20 parser and writer. The extension communicates a
deployment role, not a different binary format.

Three envelope states may follow the body:

1. immediate EOF;
2. a trailer whose final `u32` equals the complete tail size;
3. an opaque tail preserved intact and not exposed as an editable trailer.

Lightmap rows use their four-byte encoding when the explicit flag is non-zero
or when `columns == 3`, covering the Prime 2 variant observed in the corpus.
