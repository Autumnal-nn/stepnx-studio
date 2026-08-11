# ADR 0010: Isolated NX10 importer and explicit projection diagnostics

Status: accepted

Date: 2026-08-11

## Context

NX10 is the native chart format used by Pump It Up NX2. NX20 is its successor
and the canonical StepNX Studio document model. Treating both formats as
dialects of one codec would weaken the byte-exact NX20 writer and obscure which
values are copied, transformed, approximated, or unsupported during import.

Existing tools are useful but not normative. `nx_editor-v61a.py` correctly
interprets the 80-byte table referenced by each NX10 block as ten `u32` minimum
values followed by ten `u32` maximum values. NXConvert v4 instead treats that
area as a random selector plus compatibility fields. Runtime behavior in
`piu_nxa`, followed by official NX2 files and `piu_nx2`, is authoritative when
implementations disagree.

## Decision

NX10 is handled by a one-way importer in `stepnx.importers.nx10`. The native
NX20 codec continues to reject NX10 input.

The importer:

- retains the complete NX10 source byte string in its result;
- builds a deterministic editable `NX20Document` using rich rows;
- emits structured transformation, approximation, and unsupported diagnostics;
- never writes over or rewrites the NX10 source;
- accepts the documented NX2 mode headers for Single, Double/Freestyle,
  Half-Double, and Lightmap;
- applies the NX10 `chart_type * 2` step-offset adjustment;
- converts `BPM == 0` to the NX20 smooth-warp bit with a deterministic auxiliary
  BPM and reports the transformation;
- preserves all nonzero Division ranges 0–9 as NX20 Division Metadata using
  `(max << 16) | min`, subject to NX20's packed `u16` range;
- treats Division 0 ranges `1/0` and `2/0` as the documented exceptions that
  project to Split select bits `0x80` and `0x40` instead of Division Metadata;
- reports any note, range, or scalar that cannot be represented exactly.

The `import-nx10` CLI command writes a native NX20 file only when an explicit
output path is supplied. A non-lossless projection returns an attention status
while still exposing the complete report and preserved source.

## Consequences

NX20 round-trip guarantees remain isolated from legacy import policy. Unknown
NX10 data cannot disappear silently because the original bytes and diagnostics
remain available together. Imports use more memory than compact native NX20
documents because two-byte NX10 cells cannot back four-byte NX20 cells without
conversion.

Synthetic tests establish the parser and known semantic mappings now. The full
official NX2 dump remains the acceptance corpus and may expose additional
runtime-backed rules. Such findings will change the importer and its tests, not
the native NX20 codec.
