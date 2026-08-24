# Phase 11 active backlog

This file tracks work that remains inside the agreed Phase 11 scope while the
branch is still under active validation.

## Pending implementation

- **NX file management in the folder tree**: create, duplicate, and delete `.NX`
  files without leaving the editor. New charts should derive the required header
  context from `LM.NX`; destructive operations must confirm and `LM.NX` must be
  protected because the workspace requires exactly one valid Lightmap.
- **Waveform for compressed/staged audio**: extend the existing PCM WAV waveform
  path to MP3 and decoded/staged AUD/A audio while keeping playback and waveform
  aligned to the same source.
- **Explicit scope / field authoring tools**: finish the Phase 11 UI for changing
  the selected chart scope/field geometry rather than requiring external editing.
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
