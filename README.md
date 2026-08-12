# StepNX Studio

StepNX Studio is a lossless NX20 chart core and the foundation of a future
visual editor for Pump It Up. It is created and maintained by Autumnal
([`Autumnal-nn`](https://github.com/Autumnal-nn)).

Status: pre-alpha, with practical and advanced NX20 authoring slices. The current
release proves the project's most important contract: an unedited NX20 or NFO
document can be rebuilt byte for byte without normalizing metadata, flags,
padding, note cells, floating-point payloads, or its trailer.

## Implemented

- strict bounded reader with offset-aware diagnostics;
- raw `u8`, `u16`, `u32`, and `f32` scalars with source spans;
- bit-exact preservation of NaNs, infinities, and negative zero;
- ordered global, split, and Division metadata with duplicates;
- stable internal IDs for document entities;
- separate normal, empty, and Lightmap row variants;
- effective Lightmap detection from either its flag or `columns == 3`;
- no trailer, sized trailer, and opaque-tail envelopes;
- one NX20 codec shared by `.NX` and `.NFO`;
- isolated one-way NX10 importer with preserved source bytes and structured
  conversion diagnostics;
- compact/lazy row storage, now the default;
- sparse row overlays: editing one cell promotes one row, not the entire block;
- immutable commands for metadata, block fields, rows, and cells;
- stable-ID collection commands for metadata, splits, blocks, and rows;
- in-memory undo/redo snapshots;
- independent structural validation and structural diff;
- atomic saving;
- non-recursive folder workspaces with isolated per-file failures;
- `Save All` preflight, external-change detection, staged writes, and rollback;
- exact-case structurally valid `LM.NX` publication gate, with explicit
  NX10-to-NX20 materialization required for imported Lightmaps;
- StepEdit-compatible blank NX20 Lightmap generation with preview, explicit
  write, valid-file reuse, and no replacement of existing Lightmaps;
- manifest-free audio discovery and session-only audio selection;
- application-state recovery snapshots with payload hash verification;
- explicit NX/NFO mirror comparison and export primitives;
- `inspect`, `roundtrip`, `verify`, `validate`, `diff`, `import-nx10`,
  `folder-inspect`, `folder-save-plan`, `folder-generate-lightmap`, and
  `mirror-compare` CLI commands;
- immutable authoring snapshots and Qt-independent timeline culling;
- optional PySide6 shell with tabs, document tree, diagnostics, metadata
  inspection, branch switching, note tools, timing fields, undo/redo, and
  guarded `Save All`;
- stable Split/Block insertion, removal, and reordering;
- rectangular stable-ID selection with copy, paste, erase, replace, mirror,
  typed bulk placement, visible musical snapping, and StepEdit-compatible note
  function/visibility flags;
- deterministic row/beat/time projection, atomic Block timing editing, and
  chart-wide Start Time shifting;
- session audio transport, selection-or-viewport Play seeking, PCM WAV
  waveform, per-beat or per-arrow metronome, follow-playhead, and explicit
  audio offset;
- bundled royalty-free static noteskin atlases and metronome sound, with local
  noteskin/audio overrides;
- declarative `nxa-native` and `nxa-step5-patched` capability registries with
  scope-aware metadata labels and authoring validation;
- ordered, duplicate-preserving typed metadata editing, including Brain Shower
  fields and packed condition ranges;
- conditional-route projection with direct branch navigation;
- a safe mission-condition parser validated against every condition in the
  supplied official NX2/NXA mission files;
- same-byte-length UTF-8 trailer-string editing for proven metadata offsets,
  with relocation and unknown encodings deliberately blocked;
- previewed folder batches for header metadata and Block Start Times;
- explicit GUI comparison and export of NX/NFO deployment mirrors;
- deterministic generated command sequences, parser mutation fuzzing, synthetic
  fixtures, and an external corpus gate.

## Not implemented yet

- length-changing trailer-string relocation;
- typed editing of trailer fields whose offsets or encodings are still unknown;
- STF, NOT/NOT5, STX, and SEE importers;
- full-corpus validation of the NX10 importer against the official NX2 dump.

Calling the current package a finished editor would be marketing sludge. It is
the tested core on which an editor can safely be built.

## Running from a checkout

Python 3.11 or newer is required. Headless core and CLI workflows have no
runtime dependencies; the desktop application uses the optional `gui` extra.

Windows Command Prompt:

```bat
set PYTHONPATH=src
python -m unittest discover -s tests -v
python -m stepnx inspect C:\charts\NO.NX
python -m stepnx validate C:\charts\NO.NX
python -m stepnx validate C:\charts\NO.NX --authoring --profile nxa-native
python -m stepnx diff C:\charts\before.NX C:\charts\after.NX
python -m stepnx import-nx10 C:\charts\legacy.NX -o C:\charts\native.NX
python -m stepnx folder-inspect C:\charts\song-folder
python -m stepnx folder-save-plan C:\charts\song-folder
python -m stepnx folder-generate-lightmap C:\charts\song-folder --bpm 150 --write
python -m stepnx mirror-compare C:\charts\NM.NX C:\mission\NM.NFO
python -m stepnx verify C:\corpus\nxa C:\corpus\fiesta2
```

Bash:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m stepnx inspect /path/to/NO.NX
PYTHONPATH=src python3 -m stepnx roundtrip /path/to/NO.NX
PYTHONPATH=src python3 -m stepnx import-nx10 /path/to/legacy.NX -o /path/to/native.NX
PYTHONPATH=src python3 -m stepnx folder-inspect /path/to/song-folder
PYTHONPATH=src python3 -m stepnx folder-save-plan /path/to/song-folder
PYTHONPATH=src python3 -m stepnx folder-generate-lightmap /path/to/song-folder --bpm 150 --write
PYTHONPATH=src python3 -m stepnx verify /path/to/corpus
```

Editable installation:

```bash
python -m pip install -e .
stepnx --help
nxroundtrip /path/to/NO.NX
```

Desktop authoring viewport:

```bash
python -m pip install -e '.[gui]'
stepnx-studio --profile nxa-native /path/to/chart/folder
```

Choose a note tool and click or drag across cells to place notes; one drag is
one undo step. `Bank / ID` supplies the noteskin bank, item ID, or Division ID.
`Save All` performs validation, shows affected files and a structural diff,
then uses the existing atomic multi-file save plan. Split/Block details live in
the right-side gutter; double-click that gutter to cycle a Split's active Block.
Hold Ctrl while using the mouse wheel to zoom; the `6144 px/beat` ceiling gives
dense Beat Split rows enough magnification for precise editing.
Without Ctrl, each mouse-wheel notch scrolls half a musical beat in the split under
the pointer, so dense beat splits do not make navigation artificially slower.
Use **Edit → Structure → Edit Block timing** for the nine native NX20 Block
scalars. `Shift` extends a rectangular selection and `Ctrl` toggles cells;
copy/paste, mirror, filtered replace, erase, and application of the current tool
operate as one undo step. Audio source selection, metronome mode, and chart
following live under **Audio**; engine profile and Snap live under
**File → Settings**. On Play, an active selection becomes the seek anchor;
without one, playback starts at the beat at or immediately before the 7%
viewport playhead. Offset remains an explicit session-only numeric field. Beat
height follows zoom and is independent of Beat Split, so denser splits produce
smaller rows instead of taller charts. During Play, Block height additionally
follows `scroll`; zero-scroll Blocks collapse, and
smooth-warp Blocks are skipped; Pause restores the authoring grid. PCM WAV
files also receive an in-timeline waveform. A blank virtual tail after the last
row lets followed playback keep the playhead at 7% through the chart endpoint;
the tail never becomes editable or serialized. Compressed files still use Qt's
transport but do not pretend a waveform was decoded when it was not.
Choose the engine profile before opening a folder. **Edit → Metadata** operates
on the Header, Split, or Block selected in the workspace tree and preserves
unknown entries and duplicate order. The Routes side tab projects Split flags,
condition ranges, and Division triggers; double-clicking a branch activates its
Block without changing chart data. Folder batches show every affected document
before changing memory and still require **Save All**. NFO mirrors remain an
explicit compare/export action and are never synchronized merely because their
basename matches an NX chart.
The bundled royalty-free authoring pack and optional local visual overrides are
documented in [`docs/VISUAL_PACKS.md`](docs/VISUAL_PACKS.md). No proprietary
sprites ship with the project.

Run the culling benchmark against a large chart with:

```bash
stepnx-viewport-benchmark /path/to/chart.NX
```

`roundtrip` writes nothing unless `--output` is provided. Existing files are
protected unless `--force` is explicit. `import-nx10` also writes nothing
without an explicit output and never replaces its NX10 source implicitly.
`folder-save-plan` performs the complete publication preflight but never writes.
`folder-generate-lightmap` is also a preview unless `--write` is explicit. It
reuses a valid `LM.NX` and refuses to replace an invalid or case-colliding file.
The GUI executes a `Save All` plan only after showing its targets and structural
diff. Validation failures and targets changed outside the editor still block the
write.

## Corpus evidence

Official charts and executables are not redistributed. The local gate walks NX
and NFO files, reconstructs each file from the model, and compares the bytes.
NX10 inputs are routed through the dedicated importer and its projection
report; they are never accepted by the native NX20 codec.

Baseline recorded on 2026-08-10:

- 12,909/12,909 NX20/NFO files rebuilt byte-exactly;
- 12 NX10 files correctly classified outside the native NX20 codec;
- 12/12 NXA-embedded NX10 files imported cleanly into stable native NX20;
- zero byte differences;
- zero structural errors.

The largest measured chart improved from 150.7 MiB and 1.48 s in rich mode to
31.3 MiB and 0.244 s in compact mode. See [the corpus gate](docs/CORPUS_GATE.md)
and [the corpus analysis](docs/NX20_NFO_CORPUS_ANALYSIS.md).

## Architecture and roadmap

- [Project charter](docs/PROJECT_CHARTER.md)
- [Technical roadmap](docs/ROADMAP.md)
- [Current implementation status](docs/STATUS.md)
- [Phase 6 Windows validation](docs/PHASE6_VALIDATION.md)
- [Phase 7 Windows validation](docs/PHASE7_VALIDATION.md)
- [Viewer source audit](docs/VIEWER_SOURCE_AUDIT.md)
- [Architecture decisions](docs/adr/)

The authoring viewport and gameplay preview will be separate projections of the
same canonical document. Only the StepNX core may open, mutate, or save NX/NFO.

## License and trademark

Code is licensed under Apache-2.0. Copyright © 2026 Autumnal and StepNX
Studio contributors.

StepNX Studio is an unofficial project and is not affiliated with Andamiro.
Official game assets are not distributed by this repository.
