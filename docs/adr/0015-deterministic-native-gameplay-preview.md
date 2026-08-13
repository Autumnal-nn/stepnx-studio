# ADR 0015: Deterministic native gameplay preview

Status: accepted

## Context

Gameplay preview needs conditional-route selection, timing, chart-state
simulation, input, modifiers, and animation. A moving authoring timeline does
not simulate gameplay. Letting a web viewer parse NX20 independently would
create a second source of truth. Importing WebPrime or PIUTESTER also carries
parser drift, runtime weight, and unacceptable code and asset boundaries.

NXA route behavior is only partly proven. Perfect/Great/Good/Bad/Miss, rank
counters, and Brain Shower correct/wrong ranges have explicit profile entries.
Applause state and several timing effects do not yet have enough independent
runtime evidence for faithful simulation.

## Decision

The canonical document exports an immutable `PreviewSnapshot`. It retains all
Blocks, stable IDs, profile semantics, raw route flags, conditions, triggers,
and source-backed rows. It cannot save or mutate the document.

A separate resolver produces a recorded route using one explicit policy:

- manual choices supplied by the authoring timeline;
- random choices from a local PRNG with a required recorded seed;
- all-perfect state that advances only counters with proven semantics.

Unsupported conditions, ambiguous matches, and unseeded random ties block event
generation. No policy silently falls back to Block zero.

The event stream uses each Block's explicit Start Time and BPM anchor and a
continuous scroll-position projection. `Scroll = 0` is a valid stationary
segment in both gameplay preview and the authoring transport projection; the
editable row grid itself remains expanded. Smooth Speed never removes notes:
every nonzero Smooth Speed byte
interpolates the Block's fifth-float speed factor from the preceding value to
the current target. Unproven freeze behavior is reported.

The renderer is a native Qt gameplay surface. It consumes only the immutable
event stream, shares the existing audio clock, draws receptors and continuous
holds, resolves normal judgment once per row (including hold body/tail), keeps
STEPFX tied only to pad presses, maintains transient state outside the document, and loads
only the project's original royalty-free assets or an explicitly selected local
noteskin. Initialization accepts a play mode and COMMAND. Runtime controls use
the independently documented PIUTESTER layout, including speed keys, F6 debug,
F8 autoplay, and two-player pad input.

PIUTESTER is a private behavioral reference only. Its executable, scripts,
archives, assets, manual text, and derived artwork never enter the source tree,
tests, packages, or screenshots. Exact scoring and judgment values remain local
preview approximations until separate engine measurements establish profiles.

## Consequences

- Authoring and preview remain independent consumers of one core model.
- Route runs are reproducible and explainable by policy, seed, and decisions.
- Unknown NXA behavior remains visible instead of turning into plausible but
  false animation.
- The project does not ship WebPrime code, JPAK data, or official artwork.
- Runtime input and display can evolve without changing or dirtying a chart.
- Exact NXA, Fiesta 2, and Prime scoring remains gated on measured profile
  evidence rather than visual imitation.
