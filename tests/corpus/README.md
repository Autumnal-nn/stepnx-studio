# External corpus tests

Official game charts are intentionally absent from this repository. They are
test inputs, not redistributable project assets.

Run the complete local corpus gate with:

    PYTHONPATH=src python -m stepnx verify \
      /path/to/nxa /path/to/fiesta2 /path/to/prime2

NX10 files are routed through the isolated importer. The gate requires a
semantically lossless report, a structurally valid canonical document, and an
NX20 projection that reparses and rebuilds exactly. Approximate or unsupported
NX10 projections fail the gate. Use `--strict-formats` only when every other
unrecognized format in the selected corpus should also fail.

Generate the private per-file manifest with:

    python tools/build_corpus_manifest.py \\
      --corpus nxa nxa-native /path/to/nxa \\
      --corpus fiesta2 fiesta2 /path/to/fiesta2 \\
      --output tests/corpus/local-manifest.json

The generated manifest is ignored by Git because it records local paths and
official filenames. The example documents the schema without leaking a corpus.

The twelve NX10 files embedded in the official NXA tree also have a committed
hash-only projection reference. It contains no chart payload. Verify those
inputs and their expected native NX20 bytes with:

    PYTHONPATH=src python tools/verify_nx10_reference.py /path/to/nxa
