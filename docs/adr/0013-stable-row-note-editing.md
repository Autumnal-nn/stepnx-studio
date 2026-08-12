# ADR 0013 — Stable-row note editing and atlas boundaries

Status: accepted, 2026-08-11.

## Context

An empty NX20 row is encoded as one four-byte marker and therefore owns no
cell IDs. The Phase 5 viewport could identify a visible row and lane, but the
existing cell command could only edit already-materialized note cells. Letting
the widget manufacture a row would duplicate codec semantics in Qt.

The project also needs useful artwork without redistributing proprietary Pump
It Up assets. The supported noteskin layout includes static or six-frame banks,
plus optional press overlays, receptor bars, item/Division sheets, and STEPFX
frames. Most gameplay feedback is irrelevant to authoring.

## Decision

The core accepts note edits addressed by stable row ID and lane. It promotes an
empty row to a full note row on first placement, allocates fresh monotonic cell
IDs, preserves the row ID, and recompacts the row when every lane is cleared.
Multiple row/lane edits may be submitted as one atomic command.

The command stack accepts an optional coalescing key. Consecutive commands from
one paint gesture retain only the pre-gesture snapshot as their undo boundary.
Ending a gesture, undoing, or redoing clears the key.

The Qt timeline performs hit testing and emits stable row/lane requests. It
does not mutate rows. The application translates the selected typed tool into
four raw bytes, sends a core command, rebuilds the immutable snapshot, and
replaces the corresponding folder-workspace document. `Save All` remains the
only GUI publication path and retains validation, target confirmation,
external-change detection, atomic replacement, and rollback.

StepNX Studio bundles a small original, royalty-free static authoring pack.
Additional local noteskin atlases are validated and referenced in place; they
override but are never copied into Git, fixtures, recovery data, chart folders,
or releases. Phase 6 may use tap, item, and Division tiles for authoring. Press
overlays, receptor bars, half-double feedback, and STEPFX are catalogued but
deferred to gameplay preview.

## Consequences

- placing the first note on an empty compact row is lossless and undoable;
- clearing the last note restores compact empty-row serialization;
- drag painting is one undo operation rather than a history flood;
- bulk-note semantics are available before the multi-selection UI;
- Qt remains a projection/controller, not a second chart model;
- tests use the bundled original pack or synthetic PNG headers and generated
  NX20 data;
- gameplay feedback assets do not quietly turn the authoring viewport into an
  premature simulator.
