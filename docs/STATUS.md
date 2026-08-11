# Implementation status

Date: 2026-08-11

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
- optional PySide6 read-only shell with tabs, document tree, diagnostics, and
  contextual metadata/Division inspection;
- original vector note glyphs and validated user-selected local visual packs;
- synthetic 267,264-row viewport benchmark and conditional offscreen Qt smoke
  coverage;
- Windows 10 validation of all 95 synthetic/unit tests: 94 passed and the one
  expected case-collision test was skipped on the case-insensitive filesystem;
- packaged Qt paint/scroll/zoom runtime gate at 175.3 fps over 300 frames,
  comfortably above the required 30 fps floor;
- complete byte-exact gate over the known corpus.

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

- validation is structural, not yet engine-profile authoring validation;
- structural row insertion/removal/move currently materializes the affected
  compact row collection; point edits remain sparse;
- the trailer remains raw and cannot safely relocate typed strings;
- NX10 importer awaits validation against the complete official NX2 dump;
- the Phase 5 viewport is read-only and has no authoring commands.

## Next gate

1. validate the NX10 importer against the official NX2 corpus and NXA runtime;
2. execute the generated blank `LM.NX` in NXA as an independent runtime gate;
3. add the `nxa-native` feature registry and authoring validation layer.

The viewer audit accepts STEPEdit-pixi as a conditional layout reference and
WebPrime as a possible basis for a separate gameplay preview. Neither external
parser becomes authoritative, and no proprietary artwork enters the build.
