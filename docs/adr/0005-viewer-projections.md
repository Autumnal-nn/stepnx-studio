# ADR 0005 — Views are projections of the canonical document

Status: accepted, 2026-08-10.

## Context

The Studio needs two fundamentally different views:

- a vertical authoring viewport inspired by StepEdit 5.63 and STEPEdit-pixi;
- an animated gameplay preview for which WebPrime is a useful code base.

Both references use simplified parsers and models that violate the Studio's
lossless contract. A gameplay preview must also choose a single block route
without turning that transient choice into a chart edit.

## Decision

Only the StepNX core reads and writes NX/NFO. Views receive read-only snapshots
derived from the canonical document.

- `AuthoringSnapshot` feeds the vertical Qt widget. Interactions return commands
  addressed by stable ID.
- `PreviewSnapshot` feeds `RouteResolver` and a gameplay renderer. It cannot
  issue edit commands.
- STEPEdit-pixi is a conditional layout/code reference; code reuse requires a
  compatible license.
- WebPrime is a behavioral reference only. Its code and assets are excluded;
  the gameplay module will be independently implemented unless a future audit
  confirms a compatible license from every relevant copyright holder.

## Route resolution

A session chooses one reproducible route by one of these policies:

1. manual block choice per split;
2. profile-native random selection with a recorded seed;
3. profile-specific autoplay with simulated gameplay state;
4. a diagnostic and mandatory manual choice for unsupported conditions.

Route, seed, and simulated state are session data. They are not serialized in
NX and do not justify a project sidecar.

## Consequences

Renderers are replaceable without touching the codec. Preview failures cannot
corrupt the document. Alternative branches remain available for later runs.
Official/proprietary assets are excluded from every release.
