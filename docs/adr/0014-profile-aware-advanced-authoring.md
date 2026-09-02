# ADR 0014 — Profile-aware advanced authoring

Status: accepted

## Decision

Advanced NX20 semantics live in declarative engine-family profiles. Metadata
identity is the tuple of engine profile, storage scope, and numeric ID; a numeric
ID by itself is not a semantic key.

The public authoring families are NXA, Fiesta, and Prime+. Engine-family
registries may add typed labels, constraints, editors, and preview behavior only
where evidence supports them. They may never erase or normalize raw data simply
because semantics are unknown.

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

Known trailer offsets may expose NUL-terminated UTF-8 strings. Guarded relocation
is allowed only when the trailer layout and every affected typed pointer can be
updated safely. Ambiguous unknown pointers block relocation rather than being
guessed.

Folder batches are write-free plans. Applying a plan changes editor documents;
publication still uses the existing guarded `Save All` path. NX/NFO mirror
deployment remains a separate, explicitly confirmed operation.

## Consequences

- ID collisions across Header, Split, and Division scopes cannot produce false
  labels or the wrong editor.
- semantics from one engine family do not leak into another family merely
  because numeric IDs match.
- unknown official or experimental data remains lossless.
- Brain Shower and branch tooling reuse the canonical model rather than creating
  a second serialized representation.
- trailer editing may refuse unsafe relocation, but it does not silently corrupt
  offsets.
