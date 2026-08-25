# Phase 11 active backlog

This file tracks work that remains inside the agreed Phase 11 scope while the
branch is still under active validation.

## Implemented, awaiting final Windows validation

- **NX file management in the folder tree**: create, duplicate, and delete `.NX`
  files without leaving the editor. New charts use the exact `LM.NX` as their
  header/timing template, start with empty gameplay rows, and choose their field
  geometry at creation time. Duplicate is byte-exact. Delete is explicitly
  confirmed. `LM.NX` is protected from duplicate/delete and all membership
  changes refuse to reload over unsaved in-memory chart edits. A stale-document
  UI guard also absorbs the transient tree/tab callback observed after deleting
  the currently selected chart.
- **Explicit NX10 materialization on Save All**: imported NX10 `.NX` files remain
  provenance and are never overwritten implicitly. If one or more imports still
  lack a native output target, Save All presents one explicit confirmation that
  lists them and offers in-place NX20 materialization. Cancel leaves every NX10
  source untouched; approval assigns each source path as its explicit target,
  then the normal atomic Save All preflight/confirmation runs and reloads the
  folder as native NX20 after the write.
- **Explicit scope / field authoring tools**: standard Single `(0,5)`, Double
  `(0,10)`, and Half Double `(2,6)` presets plus an explicit custom Start Column
  / Columns path. Existing notes are remapped by absolute physical panel; a
  shrinking field refuses to discard non-empty cells unless the user explicitly
  confirms the destructive change. The edit runs through the normal command
  stack and therefore participates in Undo/Redo and Save All.
- **NX20 sparse long-note renderer parity**: NXA and Prime 2 have matching
  evidence. `D/1429/1429/D22_EXC22.NX` contains a 252-row completely empty
  interval inside the long at roughly 1:02–1:13; rows that resume gameplay also
  contain BODY in the carried lanes. NXA renders the same NX20 behavior while an
  NX10 conversion in PIUTESTER loses the shaft through the empty run. The Studio
  preview therefore models the NX20 rule: globally empty rows are transparent;
  on a globally non-empty row an open lane continues only on BODY, closes on
  TAIL, and is cancelled by any other value/implicit zero. There is no beat/time
  gap threshold. Authoring hold terminals are centered on their exact timing
  lines, and heads receive a body underlay so the shaft joins the terminal with
  no visual gap.
- **Compressed/staged precision waveform pipeline**: Qt `QAudioDecoder` derives
  the visual waveform asynchronously for MP3 and other Qt-supported compressed
  audio. ENC2 `.AUD` and `.A` reuse the exact staged decoded MP3 that
  `QMediaPlayer` receives, so waveform and playback share one source. The
  waveform uses stereo signed min/max summaries with a 16-frame base and a
  multiresolution pyramid selected by the visible time-per-pixel. Existing
  synchronous PCM-WAV projection remains the fast path. Automatic song lookup
  uses sibling `<FolderName>.mp3`, sibling `A.mp3`, then in-folder `Song.mp3`
  with Windows-compatible case handling before offering manual selection.
- **Authoring timing polish**: the toolbar can shift every Block Start Time by
  the same delta through `All splits`; the Inspector can opt into direct typed
  editing of the nine native Block timing values; both paths retain normal
  validation and Undo/Redo behavior.
- **Monotonic metronome transport**: small delayed backend position regressions
  during live playback are rejected without re-anchoring the extrapolated clock,
  preventing one note crossing from being emitted twice. Metronome playback uses
  a bounded voice pool so legitimate dense ticks do not truncate the previous
  WAV with `stop()+play()`.
- **Persistent external rendering assets**: successful local visual-pack and
  noteskin selections are stored as application preferences with `QSettings`,
  outside the chart folder, and restored on the next Studio launch.
- **Guarded length-changing trailer editing**: the core relocates aligned proven
  UTF-8/NUL trailer-string slots, updates every later typed trailer offset and
  the trailer size marker, preserves shared aliases, and blocks relocation when
  an untyped metadata value plausibly points into the region that would move.
  The GUI now uses this guarded path instead of imposing the earlier same-byte-
  length restriction.
- **Patched-profile capability gating**: normal executable names expose only NXA,
  Fiesta 2, and Prime 2. The hidden patched capability replaces native NXA only
  when the startup executable identity explicitly enables it; its UI label is
  `NXA-patched` while the internal registry key remains stable for compatibility.

## Pending implementation

None inside the agreed Phase 11 scope.

## Deferred validation, not an implementation blocker

- **Matched KSF ↔ NOT pairs**: when equivalent originals become available,
  compare row cuts, BUNKI boundaries, STARTTIME re-anchoring, and any historical
  rounding/padding adjustments. The current KSF and NOT importers already have
  an implemented model; this is a precision/equivalence gate.

## Phase close-out

- `README.md`, `docs/STATUS.md`, and `docs/ROADMAP.md` have been refreshed to
  reflect SEE import, compressed/staged waveform generation, guarded trailer
  relocation, workspace tools, and the completed Phase 11 implementation scope.
- Run the strict Windows test gate on the final Phase 11 HEAD and perform the
  final manual smoke tests before merging Phase 11.
