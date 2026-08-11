# ADR 0012 — Read-only authoring viewport boundaries

Status: accepted, 2026-08-11.

## Context

Phase 5 introduces the first Qt UI over documents that may contain hundreds of
thousands of rows. Building Qt objects for every row would discard the compact
storage work from Phase 2. Letting widgets retain or normalize their own chart
model would also create a second, lossy source of truth.

## Decision

The viewport is split into three layers:

1. `AuthoringSnapshot` projects immutable document structure, contextual
   metadata, stable IDs, diagnostics, and source-backed immutable row
   sequences.
2. `TimelineLayout` owns geometry, hit testing, branch selection projection,
   zoom, measure markers, and viewport culling without importing Qt.
3. `TimelineWidget` paints only the visible row windows and returns inspection
   or branch-session actions. Phase 5 exposes no chart mutation or save action.

The selected block for each split is session state stored in a replacement
snapshot. Switching a branch cannot change or serialize the canonical
document.

PySide6 is an optional dependency so the codec, CLI, importers, tests, and
folder tooling remain usable without a desktop runtime. The built-in visual
set is drawn from original vector primitives. User-selected PNG/SVG packs stay
local and are neither copied nor redistributed.

## Performance gate

The repository includes a synthetic 267,264-row Lightmap fixture with no
proprietary chart payload. Unit tests require the culling benchmark to exceed
30 frames per second while touching only a bounded visible window. A separate
offscreen Qt smoke test renders the same fixture when the host provides the Qt
native runtime.

The pure benchmark proves sublinear row access; it does not replace the final
30 fps scroll/zoom measurement on the supported Windows package. That runtime
gate remains mandatory before Phase 5 is marked complete.

## Consequences

- compact rows are preserved through snapshot creation;
- rendering cost scales with visible rows rather than chart length;
- geometry and branch behavior remain deterministic and unit-testable;
- GUI installation cannot make PySide6 mandatory for headless workflows;
- Phase 6 may issue stable-ID commands through the same snapshot boundary
  without granting widgets direct model mutation.
