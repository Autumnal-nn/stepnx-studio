# Implementation status

Date: 2026-08-10

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
- 46 synthetic/unit tests;
- complete byte-exact gate over the known corpus.

| Corpus metric | Value |
| --- | ---: |
| Exact NX20/NFO | 12,909 / 12,909 |
| Classified NX10 | 12 |
| Differences | 0 |
| Structural errors | 0 |

The largest chart in the corpus is 2,125,684 bytes with 267,264 rows. Rich mode
used 150.7 MiB and 1.48 s for parse plus rebuild. Compact mode used 31.3 MiB and
0.244 s: about 79% less memory and six times faster, with identical bytes,
stable IDs, and source spans.

## Current limitations

- validation is structural, not yet engine-profile authoring validation;
- structural row insertion/removal/move currently materializes the affected
  compact row collection; point edits remain sparse;
- the trailer remains raw and cannot safely relocate typed strings;
- NX10 is recognized but not imported;
- folder workflows and blank `LM.NX` generation are pending;
- no timeline or GUI exists.

## Next gate

1. implement the isolated NX10 importer with an explicit conversion report;
2. implement folder open/save and validate/generate `LM.NX`;
3. add the `nxa-native` feature registry and authoring validation layer;
4. produce the first read-only Qt authoring viewport.

The viewer audit accepts STEPEdit-pixi as a conditional layout reference and
WebPrime as a possible basis for a separate gameplay preview. Neither external
parser becomes authoritative, and no proprietary artwork enters the build.
