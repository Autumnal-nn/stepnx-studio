# Phase 9 validation

Phase 9 keeps legacy formats import-only and projects them into the canonical
NX20 document model. Source files are never overwritten implicitly.

Validated importer surface:

- NX10 through the isolated NX10 importer;
- STF;
- NOT / NOT5;
- STX;
- KSF / KIU;
- Direct Move data represented by the shared legacy semantic model.

The importer preserves source bytes and reports approximation, ambiguity, and
unsupported constructs as structured diagnostics. Fatal ambiguities cancel
import instead of manufacturing plausible chart data.

SEE remains intentionally unavailable because the required decryption profile
has not been recovered with sufficient corpus evidence.

CLI entry point:

```text
stepnx import-legacy <source> -o <target.NX>
```

The writable target is NX20 only.
