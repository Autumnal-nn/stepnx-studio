# Phase 11 active backlog

This file tracks work that remains inside the agreed Phase 11 scope while the
branch is still under active validation.

## Implemented, awaiting final Windows validation

- **First closed-alpha responsiveness / workflow feedback**: interactive note
  toggles now avoid full-document route/diagnostic reconstruction in the
  immediate click path. Mouse hit-testing retains the already-known Block,
  CompactRows use binary stable-ID lookup, and one-cell edits remain sparse row
  overlays. The visible Block snapshot updates immediately; structural
  validation, Routes, Diagnostics and menu refresh coalesce into one idle pass
  after a short edit burst. The generic core SetNoteAt remains unchanged and
  regression tests require byte-equivalence with the indexed interactive path.
- **StepEdit-style Split boundary drag**: the divider between adjacent Splits
  exposes a vertical-resize cursor. Dragging resizes the upper Split and shifts
  every Block Start Time in the immediately lower Split by the corresponding
  visible/reference-Block time delta. Shrinking is clamped after the last
  non-empty cell across every Block in the upper Split, so the gesture cannot
  truncate arrows/items/Division cells. The completed drag is one Undo/Redo
  command.
- **Metadata workflow discoverability**: Edit → Metadata now includes an
  explicit Division metadata action that uses the Block last inspected in the
  chart even when the workspace tree is still selected on a Split. The existing
  duplicate-preserving typed dialog supplies Add/Edit/Remove.
- **Stable two-row toolbar layout**: Audio transport is placed on its own toolbar
  row, eliminating the transient Qt three-dot overflow popup.
- **Compact engine-family profiles and R!SE evidence**: public labels are `NXA`,
  `Fiesta`, and `Prime+`, while stable internal keys remain `nxa-native`,
  `fiesta2`, and `prime2`. `Fiesta` represents Fiesta / Fiesta EX / Fiesta 2;
  `Prime+` represents Prime / Prime 2 / XX / Phoenix / R!SE and compatible
  modern successors. Header1008 is registered in Prime+ as the runtime-confirmed
  `Step Artist (XX and beyond)` trailer field (`mpStepArtist` in R!SE), enabling
  the guarded trailer-string editor without creating a R!SE-only profile.
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
  Fiesta, and Prime+. The hidden patched capability replaces native NXA only
  when the startup executable identity explicitly enables it; its UI label is
  `NXA-patched` while the internal registry key remains stable for compatibility.
- **Final engine-profile authoring coverage**: the NXA, Fiesta, Prime+, and
  patched-NXA registries cover every metadata ID observed in the supplied
  official corpora without inventing semantics for unresolved raw fields. The
  final audit separates NXA GM65's native simplified decoder from the Fiesta-
  style decoder deliberately copied by the Step5 patch; removes later-only
  Header 1000/1001/1002, GM35, Div11/12, and Div200 semantics from native NXA;
  types native Div10/16 as the Cheer Level state pair; maps Fiesta GM67/68 to
  Judge Hide/Judge by Note; records Fiesta-era H1005 Auto Velocity as strongly
  inferred and H1006 as raw-only; types per-floor x110/x111 Rush/scroll values;
  records the Fiesta Brain Div11/12 family and the co-op `1000+n = other-player
  Div n` condition family; suppresses that O/X authoring in Prime+; isolates
  discarded `EF2166_D18_MINAMI` Split 0..4 / Division 1005..1007 placeholders;
  and adds modern Header1008 Step Artist from the R!SE evidence. Composite
  trailer IDs preserve their full 32-bit ID and expose the historical language
  labels Korean/Spanish/Portuguese/Chinese/Japanese. The complete decision record
  is `docs/PHASE11_METADATA_CLOSEOUT.md`.
- **Official NX2 -> NXA importer audit**: all 2,125 supplied NX2 charts fall
  inside the supported NX10 source domain, and 2,111 same-path official NXA NX20
  successors provide conversion evidence. The comparison corrected Half Double
  row addressing, NX20 bank high bits, the no-register long-note family, and the
  leading zero-BPM fallback. All 110 observed source note codes now have matching
  successor evidence; Division projection is exact across 18,769 aligned blocks.
  The full evidence record is in `docs/NX2_NXA_CONVERSION_ANALYSIS.md`.

## Pending implementation

None inside the agreed Phase 11 scope.

## Deferred research, not a validation blocker

- **NXA Brain Div43..49**: direct native consumers exist, but the supplied
  official NXA corpus does not exercise these IDs. They remain explicitly
  unknown/raw and non-authorable until a concrete editor/runtime need justifies
  another executable pass.
- **Fiesta 2 Brain Split11/12 and Header1006**: the corpus establishes their
  presence and scope but not a safe typed meaning. They remain raw-only; this is
  an intentional preservation state, not unfinished Phase 11 implementation.
- **Matched independent KSF ↔ NOT originals**: the current KSF and NOT importers
  already have an implemented conservative model. The unavailable 13-column KSF
  material is expected to be downstream conversion material rather than an
  independent authoring source, so it cannot serve as a stronger equivalence
  oracle. If genuinely independent matched originals become available later,
  they may still refine historical row cuts, BUNKI boundaries, STARTTIME
  re-anchoring, or rounding/padding behavior; Phase 11 does not wait for them.
- **Physical Lightmap output**: validating actual cabinet-lamp actuation requires
  hardware not currently available. `LM.NX` structural generation/publication is
  covered by the editor; reverse-engineering NXA's cabinet-light I/O can remain a
  separate hardware research task and does not imply a dedicated Lightmap UI.
- **World Max `mission.txt`**: supplied mission files remain useful reference
  evidence for condition syntax, but mission topology/configuration is outside
  the StepNX Studio document scope. NFO remains in scope because it is native
  NX20 chart data.

## Phase close-out

- `README.md`, `docs/STATUS.md`, `docs/ROADMAP.md`, and
  `docs/PHASE11_METADATA_CLOSEOUT.md` reflect SEE import, compressed/staged
  waveform generation, guarded trailer relocation, workspace tools, completed
  engine-family profiles, the first closed-alpha feedback round, and the frozen
  official NX2 import domain.
- No additional Phase 11 implementation or research dependency remains.
- Re-run the strict Windows test gate and closed-alpha smoke test on the final
  Phase 11 HEAD before merging.
- Do not merge solely from documentation state; the Windows gate remains the
  final release/merge guard.
