# ADR 0014 — Profile-aware advanced authoring

Status: accepted

## Decision

Advanced NX20 semantics live in declarative engine profiles. Metadata identity
is the tuple of engine profile, storage scope, and numeric ID; a numeric ID by
itself is not a semantic key. The Step5 patched profile inherits the native NXA
registry and adds only extensions proven by runtime tests.

Structural validation remains independent from authoring validation. Unknown
metadata is structurally legal, preserved, and reported as an authoring warning.
Reference-only or unidentified fields remain inspectable but are not offered as
typed presets.

Metadata collection edits replace one owner's ordered collection atomically.
Existing stable IDs and untouched raw scalars survive, duplicates remain legal,
and new entries use the document allocation watermark.

Conditional routes are projections over Split selection flags, Block Division
metadata, and Division note triggers. Selecting a projected branch changes only
viewport state. It never rewrites the document.

Known trailer offsets may expose NUL-terminated UTF-8 strings. Editing is allowed
only when the replacement has exactly the same encoded byte length. Any edit
requiring relocation remains blocked until every affected offset and encoding is
typed for that engine profile.

Folder batches are write-free plans. Applying a plan changes editor documents;
publication still uses the existing guarded `Save All` path. NX/NFO mirror
deployment remains a separate, explicitly confirmed operation.

## Consequences

- ID collisions across Header, Split, and Division scopes cannot produce false
  labels or the wrong editor.
- Patched capabilities do not leak into native NXA charts.
- Unknown official or experimental data remains lossless.
- Brain Shower and branch tooling reuse the canonical model rather than creating
  a second serialized representation.
- Trailer functionality is intentionally incomplete but cannot silently corrupt
  offsets.
