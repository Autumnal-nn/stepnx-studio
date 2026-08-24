# Phase 11 active backlog

This file tracks work that remains inside the agreed Phase 11 scope while the
branch is still under active validation.

## Implemented, awaiting the next Windows validation

- **NX file management in the folder tree**: create, duplicate, and delete `.NX`
  files without leaving the editor. New charts use the exact `LM.NX` as their
  header/timing template, start with empty gameplay rows, and choose their field
  geometry at creation time. Duplicate is byte-exact. Delete is explicitly
  confirmed. `LM.NX` is protected from duplicate/delete and all membership
  changes refuse to reload over unsaved in-memory chart edits. A stale-document
  UI guard now also absorbs the transient tree/tab callback observed after
  deleting the currently selected chart.
- **Explicit scope / field authoring tools**: standard Single `(0,5)`, Double
  `(0,10)`, and Half Double `(2,6)` presets plus an explicit custom Start Column
  / Columns path. Existing notes are remapped by absolute physical panel; a
  shrinking field refuses to discard non-empty cells unless the user explicitly
  confirms the destructive change. The edit runs through the normal command
  stack and therefore participates in Undo/Redo and Save All.
- **NX20 sparse long-note renderer parity**: NXA and Prime 2 now have matching
  evidence. `D/1429/1429/D22_EXC22.NX` contains a 252-row completely empty
  interval inside the long at roughly 1:02–1:13; rows that resume gameplay also
  contain BODY in the carried lanes. NXA renders the same NX20 behavior while an
  NX10 conversion in PIUTESTER loses the shaft through the empty run. The Studio
  preview therefore models the NX20 rule: globally empty rows are transparent;
  on a globally non-empty row an open lane continues only on BODY, closes on
  TAIL, and is cancelled by any other value/implicit zero. There is no beat/time
  gap threshold.
- **Compressed/staged waveform pipeline**: Qt `QAudioDecoder` now derives the
  visual waveform asynchronously for MP3 and other Qt-supported compressed
  audio. ENC2 `.AUD` and `.A` reuse the exact staged decoded MP3 that
  `QMediaPlayer` receives, so waveform and playback share one source. Existing
  synchronous PCM-WAV projection remains the fast path.
- **Persistent external rendering assets**: successful local visual-pack and
  noteskin selections are stored as application preferences with `QSettings`,
  outside the chart folder, and restored on the next Studio launch.

## Pending implementation

- **Patched-profile capability gating**: `nxa-step5-patched` should not normally
  appear as a selectable engine profile. Resolve availability once at startup
  from the recognized executable/capability and expose it only when enabled.

## Deferred validation, not an implementation blocker

- **Matched KSF ↔ NOT pairs**: when equivalent originals become available,
  compare row cuts, BUNKI boundaries, STARTTIME re-anchoring, and any historical
  rounding/padding adjustments. The current KSF and NOT importers already have
  an implemented model; this is a precision/equivalence gate.

## Phase close-out

- Update `README.md`, `docs/STATUS.md`, and `docs/ROADMAP.md` so they no longer
  describe SEE decoding or trailer relocation as unimplemented and accurately
  summarize the Phase 11 import/workspace/audio features.
- Run the strict Windows test gate after the remaining GUI work and perform the
  final manual smoke tests before merging Phase 11.
