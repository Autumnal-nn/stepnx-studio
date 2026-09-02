# PIUTESTER behavioral audit

Date: 2026-08-13

> **2026-09-02 status correction:** this document remains the behavioral/source-
> boundary record for PIUTESTER controls and presentation observations. It is no
> longer the authority for StepNX runtime-fidelity status. Later source-primary
> work against native game executables established judgment timing, score, combo,
> grade, normal-mode gauge, multiple modifier paths, and field transforms. See
> `RISE_RUNTIME_PARITY_AUDIT.md` and `STATUS.md` for the current implementation
> state.

## Scope and boundary

PIUTESTER was inspected solely as a private interoperability and behavioral
reference. Its executable, DLLs, Lua scripts, BGA archives, fonts, artwork, and
manual text are proprietary and must not be copied into this repository,
packages, fixtures, screenshots, or generated noteskin assets.

The inspected 32-bit Windows executable has SHA-256:

`2fea7e2ffb89bddbcfd75d8d19726a658a33d55a61d739e2ae79bf0d313c4fd0`

StepNX implements documented interactions independently. It reads the canonical
StepNX preview snapshot and may reference only redistributable bundled artwork
or a user-selected local visual pack. It does not load PIUTESTER DAT or Lua
resources.

## Confirmed interactions

The supplied PIUTESTER package and its embedded help establish these controls:

| Control | Behavior |
| --- | --- |
| `1` through `9` | Select speed multipliers from 1x through 9x |
| `F6` | Toggle runtime status information |
| `F8` | Toggle autoplay |
| `F9` | Toggle the judgment guide |
| `F11` | Toggle the World Tour runtime flag |
| `Space` | Seek forward five seconds |
| `Esc` | Exit the run |
| P1 `Q E S Z C` | Upper-left, upper-right, center, lower-left, lower-right pads |
| P2 `Home PageUp Num5 End PageDown` | UL, UR, center, DL, and DR pads |

The top-row `5` and numeric-keypad `5` are different controls. The first changes
speed; the second is the P2 center pad.

StepNX selects the chart directly by its `.NX` filename; the chart itself
determines field layout. The preview launch flow also selects speed and supported
COMMAND modifiers. Random-route seeds remain internal session state.

Confirmed PIUTESTER COMMAND flags include Vanish (`V`), Non-Step (`N`), Flash
(`W`), Freedom (`F`), Mirror (`M`), Random (`R`), vertical inversion (`U`), Judge
Reverse (`J`), Deceleration (`D`), Acceleration (`A`), Exceed (`X`), Random
Velocity (`S`), and Earthworm (`E`). Digits are cumulative speed contributions
in the audited PIUTESTER grammar.

## Note visibility/function distinction

Static StepEdit evidence and runtime observations require function and visibility
to remain distinct:

| Function bits | Visibility | StepEdit label | Preview role |
| --- | --- | --- | --- |
| Normal | Visible | `__: Normal` | Visible and judged |
| Normal | Appear | `_v: Appear` | Appear presentation |
| Normal | Vanish | `_^: Vanish` | Vanish presentation |
| Normal | Invisible | `_X: Invisible` | Hidden visually, still registering |
| H family | Visible | `H_: Bonus` | Bonus/treasure family |
| H family | Appear | `Hv: Bonus(Appear)` | Bonus + Appear |
| H family | Vanish | `H^: Hidden(Vanish)` | Hidden/vanishing family |
| H family | Invisible | `HX: Hidden` | Hidden registering family |
| Ghost family | Visible | `G_: Ghost` | Ghost, non-registering |
| Ghost family | Appear | `Gv: Ghost(Appear)` | Ghost + Appear |
| Ghost family | Vanish | `G^: Ghost(Vanish)` | Ghost + Vanish |

StepNX preserves these families independently. Mission scoring semantics for
named historical modes such as Ghostbuster/Treasure Hunter remain separate from
ordinary preview judgment behavior unless source evidence establishes them.

Fiesta 2 contains separate display-command objects for Vanish, Appear, Non-Step,
Freedom, and Flash. StepNX composes supported global display state with each
note's own raw visibility instead of rewriting the canonical note bytes.

## Sequence-zone and STEPFX geometry

The audited StepEdit-compatible `BASE.png` layout uses a central five-pitch strip
with side padding. Historical Prime rendering evidence supports adjacent five-
lane strips for Double rather than two visually independent Versus fields.
StepNX therefore keeps receptor, note, hold, input and STEPFX lane centres on one
shared field geometry.

The inspected PIUTESTER STEPFX frames are opaque RGB images with black as the
near-neutral background. Static evidence did not prove the exact OpenGL blend
function at the draw call, so StepNX's black-neutral additive handling is an
independent compatibility choice rather than copied PIUTESTER rendering code.

STEPFX represents physical/autoplay pad presses separately from judgments. Hold
body/tail resolution and misses do not retrigger the initial press effect. Recent
feedback is bounded so delayed audio updates cannot replay an unbounded history.

## Current evidence status

PIUTESTER remains useful for controls, launch behavior, visual distinctions, and
historical comparison. It is **not** the current source of truth for claims that
were subsequently established from native runtime code.

Later audits have superseded the old 2026-08-13 limitations in these areas:

- judgment windows and difficulty decoding;
- ordinary score increments, combo behavior and grade projection;
- normal-mode gauge/life behavior;
- Acceleration/Deceleration generation-specific curves;
- Earthworm and Random Velocity cadence/state;
- historical Snake/ZigZag/Throw compatibility projection;
- Under Attack / vertical field transforms;
- expanded F6 statistics, including per-bank judgment/combo/score data and item
  counters.

The F6 panel is therefore no longer accurately described as a small set of
`LOCAL` placeholder counters. It is a real diagnostic surface, while still
remaining read-only session state that never participates in chart
serialization.

## Remaining source-gated work

Current unresolved runtime-fidelity work is tracked centrally in
`RISE_RUNTIME_PARITY_AUDIT.md` and `STATUS.md`. The remaining items are narrow
source/asset questions, such as exact asset-driven presentation paths or runtime
producers not yet demonstrated. They should not be re-expanded here into the
older blanket claim that score, gauge, judgment and modifiers are all
unmeasured.

Any future capture used as evidence should record executable identity, exact
chart hash, engine generation, and the isolated variable being tested.
