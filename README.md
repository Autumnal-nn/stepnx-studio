# StepNX Studio

StepNX Studio is a lossless NX20 chart editor for Pump It Up. It is created and
maintained by Autumnal ([`Autumnal-nn`](https://github.com/Autumnal-nn)).

Status: **0.9.5 pre-alpha / hardening**. Practical and advanced NX20 authoring,
legacy import, folder workflows, and the external native gameplay preview are
implemented. The project's central contract remains unchanged: an unedited NX20
or NFO document can be rebuilt byte for byte without normalizing metadata,
flags, padding, note cells, floating-point payloads, or its trailer.

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
- conservative STF, NOT/NOT5, STX, KSF, UCS, and corpus-verified SEE import
  projections through isolated one-way importer paths;
- complete supplied NX2 NX10 source-domain validation over 2,125 charts, with
  2,111 same-path official NXA NX20 successor conversions used as semantic
  evidence;
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
- explicit chart-audio selection plus deterministic sibling `<FolderName>.mp3`,
  sibling `A.mp3`, and in-folder case-insensitive `Song.mp3` auto-load;
- application-state recovery snapshots with payload hash verification;
- explicit NX/NFO mirror comparison and export primitives;
- `inspect`, `roundtrip`, `verify`, `validate`, `diff`, `import-nx10`,
  `import-legacy`, `folder-inspect`, `folder-save-plan`, `folder-generate-lightmap`,
  and `mirror-compare` CLI commands;
- immutable authoring snapshots and Qt-independent timeline culling;
- optional PySide6 shell with tabs, document tree, diagnostics, metadata
  inspection, branch switching, note tools, timing fields, undo/redo, and
  guarded `Save All`;
- stable Split/Block insertion, removal, reordering, resizing, and typed Split
  selection-byte editing;
- rectangular stable-ID selection with copy, cut, paste, erase, replace,
  horizontal/vertical flip, StepEdit-compatible mirror, typed bulk placement,
  visible musical snapping, and note function/visibility flags;
- deterministic row/beat/time projection, atomic Block timing editing, and
  chart-wide Start Time shifting;
- session audio transport, selection-or-viewport Play seeking, PCM-WAV and
  Qt-decoded compressed waveform generation, adaptive stereo min/max waveform
  rendering, per-beat or per-arrow metronome, follow-playhead, and explicit
  audio offset;
- bundled royalty-free noteskin atlases and metronome sound, with local
  noteskin/audio overrides;
- declarative NXA, Fiesta, and Prime+ engine-family semantics with scope-aware
  metadata labels, authoring validation, and raw preservation for unresolved
  fields;
- ordered, duplicate-preserving typed metadata editing, including Brain Shower
  fields and packed condition ranges;
- finalized Fiesta-and-later Header `1000..1008` semantics and guarded trailer
  string relocation for proven offset fields;
- NXA `VanishLow` and `AppearLow` note authoring and visualization;
- conditional-route projection with direct branch navigation;
- a safe mission-condition parser validated against every condition in the
  supplied official NX2/NXA mission files;
- previewed folder batches for header metadata and Block Start Times;
- explicit GUI comparison and export of NX/NFO deployment mirrors;
- immutable gameplay snapshots that retain every route branch, with internal
  random-route state and explicit non-random Block choices;
- a native Qt gameplay preview synchronized to the shared audio transport,
  using bundled royalty-free or validated local noteskin atlases;
- source-backed judgment timing, score, combo, grade and gauge behavior for the
  currently audited runtime path;
- expanded F6 debug statistics with P/G/Good/Bad/Miss, per-bank combo and
  MissCombo maxima, score, grade, gauge, clear state, and item counters;
- route provenance, conservative timing warnings, and refusal of conditions
  whose runtime state cannot be proven;
- deterministic generated command sequences, parser mutation fuzzing, synthetic
  fixtures, and external corpus gates.

## 0.9.5 hardening scope

The 0.9.5 cycle is a polish and hardening pass rather than a format-expansion
release. Its planned work is:

1. documentation truth pass;
2. performance regression coverage for bulk transforms;
3. save/recovery fault-injection tests;
4. keyboard workflow audit;
5. high-DPI/scaling validation at 100%, 125%, 150%, and 200%;
6. editor UX cleanup, including menus, selection, Inspector state, disabled
   actions, and error messages.

Open reverse-engineering questions are tracked separately from implementation
work. Raw-preserved fields with no proven semantics are not treated as missing
features.

This pre-alpha tree is suitable for focused authoring tests, not as a stable
release or a substitute for runtime validation in the target game.

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
python -m stepnx import-legacy C:\charts\legacy.STX -o C:\charts\native.NX
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
PYTHONPATH=src python3 -m stepnx import-legacy /path/to/legacy.KSF -o /path/to/native.NX
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

Before producing a Windows package, install the GUI extra and run the strict
gate. Unlike plain `unittest`, this rejects a misleading green run when the Qt
tests were merely skipped:

```powershell
py -m pip install -e ".[gui]"
py tools/run_windows_test_gate.py
```

Choose a note tool and click or drag across cells to place notes; one drag is
one undo step. `Bank / ID` supplies the noteskin bank, item ID, or Division ID.
`Save All` performs validation, shows affected files and a structural diff,
then uses the existing atomic multi-file save plan. Split/Block details live in
the right-side gutter; double-click that gutter to cycle a Split's active Block.
Hold Ctrl while using the mouse wheel to zoom. Without Ctrl, each mouse-wheel
notch scrolls half a musical beat in the split under the pointer.
Use **Edit → Structure → Edit Block timing** for the nine native NX20 Block
scalars. The toolbar's **All splits** option applies a Start Time change as one
relative delta across every Block, while **Edit → Editable Inspector timing
values** allows direct typed edits of those same timing fields. `Shift` extends
a rectangular selection and `Ctrl` toggles cells; copy/cut/paste, transforms,
filtered replace, erase, and application of the current tool operate as one undo
step. Audio source selection, metronome mode, and chart following live under
**Audio**; engine profile and Snap live under **File → Settings**.

Choose the engine profile before opening a folder. **Edit → Metadata** operates
on the Header, Split, or Block selected in the workspace tree and preserves
unknown entries and duplicate order. Proven trailer strings may be edited with
safe length-changing relocation; any ambiguous untyped pointer blocks the move
instead of being guessed. The Routes side tab projects Split flags, condition
ranges, and Division triggers; double-clicking a branch activates its Block
without changing chart data. Folder batches show every affected document before
changing memory and still require **Save All**. NFO mirrors remain an explicit
compare/export action and are never synchronized merely because their basename
matches an NX chart.

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

Current recorded corpus evidence includes:

- 12,909/12,909 NX20/NFO files rebuilt byte-exactly;
- 12 NXA-embedded NX10 files imported cleanly into stable native NX20;
- 2,125/2,125 supplied NX2 NX10 charts inside the frozen observed importer
  domain;
- 2,111 same-path official NX2-to-NXA successors used for semantic conversion
  evidence;
- all 110 observed nonzero NX10 note codes backed by successor evidence;
- exact Division projection across 18,769 aligned successor Blocks;
- zero NX20/NFO round-trip byte differences and zero structural errors in the
  recorded gate.

The largest measured chart improved from 150.7 MiB and 1.48 s in rich mode to
31.3 MiB and 0.244 s in compact mode. See [the corpus gate](docs/CORPUS_GATE.md)
and [the NX2/NXA conversion analysis](docs/NX2_NXA_CONVERSION_ANALYSIS.md).

## Architecture and roadmap

- [Project charter](docs/PROJECT_CHARTER.md)
- [Technical roadmap](docs/ROADMAP.md)
- [Current implementation status](docs/STATUS.md)
- [Phase 6 Windows validation](docs/PHASE6_VALIDATION.md)
- [Phase 7 Windows validation](docs/PHASE7_VALIDATION.md)
- [Phase 8 Windows validation](docs/PHASE8_VALIDATION.md)
- [Viewer source audit](docs/VIEWER_SOURCE_AUDIT.md)
- [Architecture decisions](docs/adr/)

The authoring viewport and gameplay preview are separate projections of the same
canonical document. Only the StepNX core may open, mutate, or save NX/NFO.
Open **Preview → Open gameplay preview** to choose the `.NX` filename, speed,
and startup modifiers. Random route state is generated internally and is not
exposed as a game option. During the run, `1` through `9` select 1x through 9x,
`F6` toggles the debug overlay, `F8` toggles autoplay, `F9` toggles the guide,
and Space seeks forward five seconds. P1 uses `Q E S Z C`; P2 uses
`Home PageUp Num5 End PageDown`. These controls are independently implemented;
no PIUTESTER code or official game assets are distributed.

## License and trademark

Code is licensed under Apache-2.0. Copyright © 2026 Autumnal and StepNX Studio
contributors.

StepNX Studio is an unofficial project and is not affiliated with Andamiro.
Official game assets are not distributed by this repository.