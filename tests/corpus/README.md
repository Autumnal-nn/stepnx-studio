# External corpus tests

Official game charts are intentionally absent from this repository. They are
test inputs, not redistributable project assets.

Run the complete local corpus gate with:

    PYTHONPATH=src python -m stepnx verify \
      /path/to/nxa /path/to/fiesta2 /path/to/prime2

NX10 files are reported as recognized-but-unsupported and do not fail this
NX20 gate. Use `--strict-formats` only when the selected corpus is expected to
contain NX20 exclusively.

Generate the private per-file manifest with:

    python tools/build_corpus_manifest.py \\
      --corpus nxa nxa-native /path/to/nxa \\
      --corpus fiesta2 fiesta2 /path/to/fiesta2 \\
      --output tests/corpus/local-manifest.json

The generated manifest is ignored by Git because it records local paths and
official filenames. The example documents the schema without leaking a corpus.
