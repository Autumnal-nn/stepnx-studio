# ADR 0003 — Folder as the workspace unit

Status: accepted, 2026-08-10.

## Decision

The product will not create or consume `.NXP`, `.snxproj`, or an equivalent
manifest. A folder directly contains its NX documents. Folder discovery is
non-recursive and accepts arbitrary NX filenames instead of a fixed slot list.

`Save All` must require a structurally valid `LM.NX` and may offer to generate
one. Missing `LM.NX` does not prevent opening a damaged folder for repair. This
behavior belongs to the future folder layer, not the binary codec.
