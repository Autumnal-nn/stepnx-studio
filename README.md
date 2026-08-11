# StepNX Studio

StepNX Studio is a lossless NX20 chart core and the foundation of a future
visual editor for Pump It Up. It is created and maintained by Autumnal
([`Autumnal-nn`](https://github.com/Autumnal-nn)).

Status: pre-alpha, with no graphical interface yet. The current release proves
the project's most important contract: an unedited NX20 or NFO document can be
rebuilt byte for byte without normalizing metadata, flags, padding, note cells,
floating-point payloads, or its trailer.

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
- `inspect`, `roundtrip`, `verify`, `validate`, `diff`, and `import-nx10` CLI
  commands;
- deterministic generated command sequences, parser mutation fuzzing, synthetic
  fixtures, and an external corpus gate.

## Not implemented yet

- typed editing and relocation of trailer strings;
- folder workspace, `Save All`, and blank `LM.NX` generation;
- GUI/Qt timeline;
- semantic engine profiles and authoring validation;
- STF, NOT/NOT5, STX, and SEE importers;
- full-corpus validation of the NX10 importer against the official NX2 dump.

Calling the current package a finished editor would be marketing sludge. It is
the tested core on which an editor can safely be built.

## Running from a checkout

Python 3.11 or newer is required. There are no runtime dependencies.

Windows Command Prompt:

```bat
set PYTHONPATH=src
python -m unittest discover -s tests -v
python -m stepnx inspect C:\charts\NO.NX
python -m stepnx validate C:\charts\NO.NX
python -m stepnx diff C:\charts\before.NX C:\charts\after.NX
python -m stepnx import-nx10 C:\charts\legacy.NX -o C:\charts\native.NX
python -m stepnx verify C:\corpus\nxa C:\corpus\fiesta2
```

Bash:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m stepnx inspect /path/to/NO.NX
PYTHONPATH=src python3 -m stepnx roundtrip /path/to/NO.NX
PYTHONPATH=src python3 -m stepnx import-nx10 /path/to/legacy.NX -o /path/to/native.NX
PYTHONPATH=src python3 -m stepnx verify /path/to/corpus
```

Editable installation:

```bash
python -m pip install -e .
stepnx --help
nxroundtrip /path/to/NO.NX
```

`roundtrip` writes nothing unless `--output` is provided. Existing files are
protected unless `--force` is explicit. `import-nx10` also writes nothing
without an explicit output and never replaces its NX10 source implicitly.

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
- [Viewer source audit](docs/VIEWER_SOURCE_AUDIT.md)
- [Architecture decisions](docs/adr/)

The authoring viewport and gameplay preview will be separate projections of the
same canonical document. Only the StepNX core may open, mutate, or save NX/NFO.

## License and trademark

Code is licensed under Apache-2.0. Copyright © 2026 Autumnal and StepNX
Studio contributors.

StepNX Studio is an unofficial project and is not affiliated with Andamiro.
Official game assets are not distributed by this repository.
