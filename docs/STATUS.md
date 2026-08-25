# Implementation status

Date: 2026-08-24

Version: 0.1.0.dev0

## Delivered

- raw scalar model with source spans and stable IDs;
- one NX20 parser/writer shared by NX and NFO;
- NXA, Fiesta 2, and Prime 2 envelope preservation;
- bounded reader with offset-aware diagnostics;
- compact/lazy row representation as the default;
- sparse editable overlays with explicit row promotion;
- immutable metadata, block-field, row, and note-cell commands;
- insert/remove/move commands for metadata, splits, blocks, and rows;
- monotonic document-level stable-ID allocation for inserted subtrees;
- undo/redo snapshot stack;
- independent structural validator;
- structural and binary CLI diff;
- atomic saves;
- generated command-sequence and parser-mutation property tests;
- isolated NX10 importer with source preservation and structured diagnostics;
- NX2 Single, Double/Freestyle, Half-Double, and Lightmap projections;
- NX10 Division range projection, including the Division 0 `1/0` and `2/0`
  Split-select exceptions;
- explicit NX10 `BPM == 0` to NX20 smooth-warp conversion;
- `import-nx10` CLI command with explicit-output-only writes;
- immediate-folder discovery with independent per-file failures;
- native NX20 entries and NX10 provenance whose editable model is always NX20;
- exact-case structurally valid `LM.NX` gate for complete-folder publication;
- StepEdit-compatible native NX20 blank Lightmap planning and explicit creation,
  with valid-file reuse and invalid-file preservation;
- individual and `Save All` planning with stale-target detection;
- staged multi-file writes with best-effort rollback;
- manifest-free audio discovery and session-only selection;
- versioned recovery snapshots outside chart folders with SHA-256 verification;
- explicit NX/NFO mirror comparison and export planning;
- folder inspection, publication preflight, and mirror comparison CLI commands;
- immutable authoring snapshots that preserve compact source-backed rows;
- Qt-independent timeline geometry, hit testing, branch projection, measure
  markers, zoom, and visible-row culling;
- optional PySide6 shell with tabs, document tree, diagnostics, contextual
  metadata/Division inspection, and the first visual note-editing tools;
- original vector note glyphs and validated user-selected local visual packs;
- synthetic 267,264-row viewport benchmark and conditional offscreen Qt smoke
  coverage;
- Windows 10 validation of all 95 synthetic/unit tests: 94 passed and the one
  expected case-collision test was skipped on the case-insensitive filesystem;
- packaged Qt paint/scroll/zoom runtime gate at 175.3 fps over 300 frames,
  comfortably above the required 30 fps floor;
- complete byte-exact gate over the known corpus.
- stable-row note placement, deletion, empty-row promotion/recompaction, and
  atomic bulk-note commands;
- typed Qt tools for taps, hold parts, items, Divisions, and erasure;
- click/drag painting with command coalescing and undo/redo;
- validation and structural-diff preview before guarded Qt `Save All`;
- bundled royalty-free static noteskin atlases plus validated local overrides,
  with no proprietary artwork
  copied into the repository, workspace, recovery data, or release;
- StepEdit-style constant square encoded rows at every Beat Split;
- half-beat-relative mouse-wheel scrolling and atlas-faithful noteskin hold
  rendering with per-direction body offsets and complete tail cells;
- empty Split/Block insertion, guarded removal, stable reordering, and undo/redo;
- atomic editing of all nine native Block scalar fields and chart-wide Start
  Time shifts;
- deterministic row/beat/millisecond timing projection using explicit Block
  Start Times;
- rectangular stable-ID selection with musical snapping, copy/paste, erase,
  mirror, filtered replace, and typed bulk placement;
- Qt audio transport with automatic/manual selection, play-start seeking from
  the active selection or viewport beat, play/pause, synchronized
  playhead/viewport following, explicit session offset, and PCM WAV waveform;
- private WAV metronome playback through `QSoundEffect`, with no operating
  system beep fallback, selectable per beat or per tap/hold-head row;
- StepEdit-compatible `H`, `G`, `X`, `▵`, and `▿` note flag editing across all
  odd-nibble note variants, with one indexed bulk command and no rewriting of
  orthogonal raw bytes;
- visible musical snap guides and a follow-playhead anchor at 7% viewport
  height;
- fixed encoded-row geometry, zoom, and viewport position shared by editing and
  playback, with side-gutter Block labels;
- register-aware per-arrow metronome events: Hidden/Invisible may tick, Ghost
  does not;
- validated ENC2 AUD-to-MP3 support for the self-contained `ENCDecrypt.exe`
  profile, with explicit rejection of unsupported machine/HASP profiles;
- `nxa-native` and `nxa-step5-patched` registries with contextual Header, Split,
  and Division metadata definitions and evidence levels;
- profile-aware authoring diagnostics that never turn unknown data into a
  structural error;
- atomic ordered metadata collection editing with safe typed values, duplicates,
  unknown fields, and stable-ID preservation;
- Brain Shower field projection/editing and conditional-route visualization;
- mission-condition parsing validated against all supplied NX2/NXA mission
  conditions, including profile-gated patched variables;
- guarded UTF-8 trailer-string editing for proven offset fields, including
  conservative length-changing relocation with downstream typed-offset and size-
  marker repair;
- previewed folder batches and explicit Qt NX/NFO mirror deployment workflow;
- read-only `PreviewSnapshot` export with all route alternatives retained;
- manual, internally randomized, and profile-aware all-perfect route resolution
  without exposing an implementation seed as a game option;
- conservative blocking diagnostics for ambiguous routes and conditions whose
  runtime state is not proven;
- explicit Start Time/BPM runtime-event projection with warp/freeze/Scroll
  diagnostics rather than invented NXA behavior;
- native Qt gameplay tabs synchronized to the existing audio transport, with
  continuous scroll geometry, one file/speed/COMMAND dialog, the shared
  metronome control, PIUTESTER-style speed/debug/autoplay/pad controls, native
  complete five-pitch sequence-zone strips and continuous Double geometry,
  press-timed STEPFX, normal row-based judgment including hold body/tail,
  composed raw visibility/COMMAND display rules, fallback artwork, and bounded
  visible-event culling;
- patched-profile-only DM120 signed mode/weight editing and validation, including
  the distinct `0/-1` and `1/-2` sentinel limits;

| Corpus metric | Value |
| --- | ---: |
| Exact NX20/NFO | 12,909 / 12,909 |
| Classified NX10 | 12 |
| Clean NX10 imports from NXA | 12 / 12 |
| Differences | 0 |
| Structural errors | 0 |

The largest chart in the corpus is 2,125,684 bytes with 267,264 rows. Rich mode
used 150.7 MiB and 1.48 s for parse plus rebuild. Compact mode used 31.3 MiB and
0.244 s: about 79% less memory and six times faster, with identical bytes,
stable IDs, and source spans.

### Phase 5 Windows validation

Validated on Windows 10 Pro build 19045 with Python 3.11.9, PySide6 6.11.1, an
AMD Ryzen 5 5600X, and an NVIDIA GeForce RTX 3060 (driver 32.0.15.9597):

| Gate | Result |
| --- | ---: |
| Full test suite | 95 discovered; 94 passed; 1 expected skip; exit code 0 |
| Layout/culling benchmark | 17,256.6 fps; 600 frames in 0.035 s; max 43 rows/frame |
| Qt paint/scroll/zoom gate | 175.3 fps; 300 frames in 1.712 s; exit code 0 |

The Qt result represents about 5.7 ms per frame against a 33.3 ms minimum-frame
budget. Phase 5 therefore passes both its 30 fps requirement and 60 fps target
without abandoning compact row storage.

## Current limitations

- structural row insertion/removal/move currently materializes the affected
  compact row collection; point edits remain sparse;
- trailer fields whose offsets or encodings remain untyped are still raw-only;
  length-changing edits are refused whenever an untyped value plausibly points
  into the region that would move;
- NX10 importer awaits validation against the complete official NX2 dump;
- Phase 8 has passed its iterative Windows manual preview gate; its packaged
  Windows/PySide6 artifact gate remains separate from the Phase 11 close-out;
- ENC2 AUD support currently accepts the profile proven by `732.AUD`; the
  distinct profiles in `D91.AUD` and `508.AUD` remain unsupported;
- cross-Split Block moves remain outside the current structural UI;
- exact judgment windows, score, grade, gauge, modifier curves, and later-engine
  presentation still require independent NXA, Fiesta 2, and Prime measurements;
- negative Speed/Freeze remains diagnostic-only until NXA behavior is
  independently measured; Smooth Speed 0–3 preserves notes and every nonzero
  value interpolates the fifth-float factor;

## Next gate

1. run the strict Windows test gate and final Phase 11 manual smoke tests;
2. validate the NX10 importer against the official NX2 corpus and NXA runtime;
3. execute the generated blank `LM.NX` in NXA as an independent runtime gate;
4. keep public release packaging disabled until the project is ready for a public build.

The viewer audit accepts STEPEdit-pixi as a conditional layout reference and
WebPrime as a behavioral reference only. Phase 8 uses a native Qt projection;
neither external parser becomes authoritative, and no proprietary artwork
enters the build.


## Phase 9/10 consolidation

The current Phase 9/10 tree consolidates the validated work
without recovery-overlay scripts or generated package metadata.

Additional delivered behavior includes:

- import-only legacy format projections with structured diagnostics;
- Fiesta 2 and Prime 2 GUI engine profiles;
- StepEdit-style Toggle interaction and context-menu Split/Block editing;
- patched-NXA SPECIAL/Number Block authoring and raw Source Slot/Brain fields;
- fixed 640x480 external Gameplay Preview with arcade-calibrated scroll pitch;
- Space Play/Pause with silent transport when chart audio is absent;
- lazy AUD staging and sibling `<FolderName>.mp3` auto-load.

## Phase 11 active branch

Additional delivered behavior includes:

- one-way STF/ST2, NOT/NOT5, STX, SEE, KSF, and UCS authoring import through a
  reviewed multi-chart materialization flow that never overwrites existing NX;
- NX file create/duplicate/delete tools and explicit Single/Double/Half Double
  or custom field geometry editing;
- corpus/runtime-backed NX20 sparse-hold behavior in the preview and timing-line-
  aligned hold terminals in authoring;
- sibling `<FolderName>.mp3`, sibling `A.mp3`, and case-insensitive in-folder
  `Song.mp3` discovery with a manual-selection fallback;
- asynchronous compressed/staged waveform decoding with stereo signed min/max,
  a 16-frame base summary, and multiresolution viewport queries;
- persistent local visual and noteskin preferences outside chart folders;
- guarded length-changing trailer relocation exposed by the Qt editor;
- profile capability gating that hides patched NXA from normal startup and uses
  the concise `NXA-patched` UI label when the hidden capability is enabled;
- optional all-Block Start Time delta editing, direct typed Inspector timing
  edits, and authoring hold-head shaft underlay;
- monotonic live audio position filtering plus a metronome voice pool, removing
  duplicate ~one-poll ticks and sample-cutoff clicks observed during validation.

No Phase 11 implementation item remains open in `PHASE11_BACKLOG.md`; the branch
is awaiting its final strict Windows gate, manual smoke test, and merge close-out.
