# External corpus gate

The official research corpus stays outside the repository. Run the lossless
gate with:

```bash
PYTHONPATH=src python -m stepnx verify ROOT [ROOT ...] --row-storage compact
```

For every NX/NFO file, the gate:

1. requires `NX20` magic for the NX20 codec;
2. parses the complete body under bounded limits;
3. serializes the tree again;
4. requires byte-for-byte equality;
5. imports NX10 separately and requires a clean report, valid document, and
   stable native NX20 rebuild.

## Baseline (2026-08-11)

| Corpus | Result |
| --- | ---: |
| NXA NX20 | 4,168 exact |
| Fiesta 2 NX20/NFO | 4,078 exact |
| Prime 2 NX20/NFO | 4,663 exact |
| NXA NX10 | 12/12 imported cleanly |
| Differences/errors | 0 |

Both rich and compact row storage rebuilt all 12,909 NX20/NFO documents
exactly. Synthetic fixtures cover raw cases absent from the official corpus,
including NaN payloads, negative zero, non-zero padding, duplicate metadata,
and opaque tails.

The hash-only NX10 reference manifest pins both each source identity and its
expected native NX20 projection. `tools/verify_nx10_reference.py` checks all
twelve files without storing or redistributing their payloads.

## Folder-layer gate

The Phase 4 loader was also run over every directory containing an immediate
NX file. This gate checks workspace isolation and publication readiness; it
does not write to the corpus.

| Corpus | Folders | Documents | NX10 | Ready for `Save All` | Expected blockers |
| --- | ---: | ---: | ---: | ---: | --- |
| NXA | 1,269 | 4,180 | 12 | 1,263 | six folders require explicit NX10→NX20 materialization |
| Fiesta 2 | 799 | 3,811 | 0 | 795 | four folders have no `LM.NX` |
| Prime 2 | 617 | 4,375 | 0 | 617 | none |

Six NXA folders contain two NX10 documents each, including `LM.NX`. Opening
imports all twelve into canonical editable NX20 documents, but those folders
remain blocked for publication until every projection receives an explicit
NX20 materialization target. The four Fiesta 2 folders with missing Lightmaps
remain blocking diagnostics, proving that the gate is not merely counting
parsable neighbors. The previously tested 1,536-byte
`D/1442/1442/DP4_Z_AL.NX` was an incomplete local extraction. The retained
Prime 2 corpus copy is 11,192 bytes, rebuilds exactly, and needs no filename
exception or whitelist.

The corpus is evidence, not a test fixture that may be committed. Reports must
not contain proprietary chart payloads.
