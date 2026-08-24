# Phase 11 active backlog

This file tracks work that remains inside the agreed Phase 11 scope while the
branch is still under active validation.

## Implemented, awaiting the next Windows validation

- **NX file management in the folder tree**: create, duplicate, and delete `.NX`
  files without leaving the editor. New charts use the exact `LM.NX` as their
  header/timing template, start with empty gameplay rows, and choose their field
  geometry at creation time. Duplicate is byte-exact. Delete is explicitly
  confirmed. `LM.NX` is protected from duplicate/delete and all membership
  changes refuse to reload over unsaved in-memory chart edits.
- **Explicit scope / field authoring tools**: standard Single `(0,5)`, Double
  `(0,10)`, and Half Double `(2,6)` presets plus an explicit custom Start Column
  / Columns path. Existing notes are remapped by absolute physical panel; a
  shrinking field refuses to discard non-empty cells unless the user explicitly
  confirms the destructive change. The edit runs through the normal command
  stack and therefore participates in Undo/Redo and Save All.

## Pending implementation

- **Waveform for compressed/staged audio**: extend the existing PCM WAV waveform
  path to MP3 and decoded/staged AUD/A audio while keeping playback and waveform
  aligned to the same source.
- **Patched-profile capability gating**: `nxa-step5-patched` should not normally
  appear as a selectable engine profile. Resolve availability once at startup
  from the recognized executable/capability and expose it only when enabled.
- **NXA long-note renderer parity**: refine the current cross-Split/Block hold
  pairing to match the native renderer carry behavior observed in `piu_nxa`.
  Sequential Split/Block boundaries do not break a long. Globally empty rows are
  transparent to the carry. When a globally non-empty row is processed, an open
  lane continues only on BODY, finalizes on TAIL, and is cleared by any other
  value (including zero in that lane). Preserve the native per-frame scan-window
  reset behavior where relevant. Do not model this as a fixed beat/time gap.

## Deferred validation, not an implementation blocker

- **Prime 2 Rock the house D22 (`1429`, EXC)**: the public chart listing confirms
  song `1429` and D22 by EXC, and the referenced gameplay recording visibly
  sustains a long for roughly 1:02–1:13 without intervening judgments. When the
  actual Prime 2 NX becomes available, inspect that interval row-by-row and use
  it as a cross-engine sparse-long regression. In particular, determine whether
  the interval is HEAD → globally empty rows → TAIL, or whether Prime 2 permits
  carry across globally non-empty rows differently from the already recovered
  NXA rule. Do not assume the NXA renderer rule merely from the video.
- **Matched KSF ↔ NOT pairs**: when equivalent originals become available,
  compare row cuts, BUNKI boundaries, STARTTIME re-anchoring, and any historical
  rounding/padding adjustments. The current KSF and NOT importers already have
  an implemented model; this is a precision/equivalence gate.

## Phase close-out

- Update `README.md`, `docs/STATUS.md`, and `docs/ROADMAP.md` so they no longer
  describe SEE decoding or trailer relocation as unimplemented and accurately
  summarize the Phase 11 import/workspace features.
- Run the strict Windows test gate after the remaining GUI work and perform the
  final manual smoke tests before merging Phase 11.
