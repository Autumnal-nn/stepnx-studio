# Phase 9 validation

> Historical validation snapshot updated for documentation consistency. Phase 9
> established the import-only legacy-format boundary. Later work completed SEE
> and UCS authoring import, so the original statement that SEE was unavailable is
> no longer true. Current importer coverage is summarized in `STATUS.md`.

Legacy formats remain import-only and project into the canonical NX20 document
model. Source files are never overwritten implicitly.

Current implemented one-way importer surface includes:

- NX10 through the isolated NX10 importer;
- STF / ST2;
- NOT / NOT5;
- STX;
- SEE;
- KSF / KIU;
- UCS;
- Direct Move data represented by the shared legacy semantic model where
  applicable.

Importers preserve source/provenance data as appropriate and report
approximation, ambiguity, and unsupported constructs as structured diagnostics.
Fatal ambiguity cancels import instead of manufacturing plausible chart data.

The NX10 importer has additionally been validated over the complete supplied
2,125-chart NX2 source domain, with 2,111 same-path official NXA NX20 successors
used as semantic conversion evidence. That later audit supersedes the narrower
Phase 9 importer evidence.

CLI entry point:

```text
stepnx import-legacy <source> -o <target.NX>
```

The writable/materialized target is NX20 only; import never silently rewrites the
legacy source.
