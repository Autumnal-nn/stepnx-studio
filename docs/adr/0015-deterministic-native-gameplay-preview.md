# ADR 0015: Deterministic native gameplay preview

Status: accepted; amended 2026-09-02

## Context

Gameplay preview needs conditional-route selection, timing, chart-state
simulation, input, modifiers, judgment, scoring, gauge state and animation. A
moving authoring timeline does not simulate gameplay. Letting a second viewer
parse NX20 independently would create another source of truth. Importing
WebPrime or PIUTESTER would also introduce parser drift, runtime weight, license
problems and proprietary-asset boundaries.

Early Phase 8 builds intentionally treated many runtime behaviors as
approximations. Subsequent source-primary audits against native game executables
resolved enough timing, judgment, score, gauge and modifier behavior that those
early blanket limitations are no longer accurate. Remaining uncertainty is
tracked narrowly in `RISE_RUNTIME_PARITY_AUDIT.md`.

## Decision

The canonical document exports an immutable `PreviewSnapshot`. It retains all
Blocks, stable IDs, profile semantics, raw route flags, conditions, triggers and
source-backed rows. Preview code cannot save or mutate the document.

A separate route resolver produces one recorded execution route. It supports:

- explicit/manual Block choices for non-random authoring inspection;
- internally randomized Split selection only where the Split flags request it;
- shared random decisions for matching nonzero lower-five-bit banks;
- independent random events when the lower five bits are zero;
- recorded decisions/provenance for diagnostics and reproducibility;
- gameplay-state condition evaluation only where the required state has a
  supported semantic projection.

The user-facing preview does not expose an implementation seed as a game option.
Unsupported conditions or ambiguous deterministic choices block rather than
silently falling back to Block zero.

The runtime event/timing layer follows native field semantics where established.
In particular, the Block flag byte is not treated as "all nonzero = Smooth":

- bit `0x01` enables Smooth interpolation;
- bit `0x02` is Skip;
- value `3` combines Smooth + Skip;
- Skip keeps encoded rows spatially present/judgeable while native timing assigns
  zero `msPerLine` for the skipped Division.

Native timing, selected speed, Block speed and displayed high-speed state remain
separate projections. Source-primary details and generation-specific exceptions
belong in `RISE_RUNTIME_PARITY_AUDIT.md`, not duplicated in this ADR.

The renderer is a native Qt gameplay surface. It consumes the immutable runtime
projection, shares the application audio clock, draws supported field/note/hold
state, keeps STEPFX tied to pad presses, and stores all transient gameplay state
outside the document. Only redistributable bundled assets or explicitly selected
local visual packs are loaded.

For the audited runtime path, preview session state now includes source-backed:

- judgment timing and difficulty decoding;
- per-bank judgment/combo state;
- score and grade projection;
- normal-mode gauge/life behavior;
- supported modifier and field-transform behavior;
- item/debug counters used by the F6 diagnostic panel.

This does not imply pixel-perfect reproduction of official Animator/material
curves or hidden engine-global RNG streams. Those are explicit compatibility or
source-gated boundaries, not reasons to downgrade proven score/judgment behavior
to "local approximation".

PIUTESTER remains a private behavioral reference for controls/presentation only.
Its executable, scripts, archives, assets, manual text and derived artwork never
enter the source tree, tests or packages. Native executable evidence takes
precedence for runtime semantics when available.

## Consequences

- Authoring and preview remain independent consumers of one canonical model.
- A preview run cannot dirty or serialize a chart.
- Route decisions are explainable from Split flags, banks, policy and recorded
  decisions without exposing a game-facing seed control.
- Unknown runtime state produces diagnostics or a documented compatibility
  projection instead of plausible invented behavior.
- Current source-backed judgment/score/gauge behavior may evolve through audited
  engine-specific evidence without changing the NX20 codec.
- Exact asset-driven presentation and unavailable engine-global RNG state are not
  prerequisites for a useful deterministic authoring/debug preview.
- The project does not ship WebPrime code, PIUTESTER code, JPAK data or official
  artwork.
