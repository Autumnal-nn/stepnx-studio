# PIUTESTER behavioral audit

Date: 2026-08-13

## Scope and boundary

PIUTESTER was inspected solely as a private interoperability and behavioral
reference. Its executable, DLLs, Lua scripts, BGA archives, fonts, artwork, and
manual text are proprietary and must not be copied into this repository,
packages, fixtures, screenshots, or generated noteskin assets.

The inspected 32-bit Windows executable has SHA-256:

`2fea7e2ffb89bddbcfd75d8d19726a658a33d55a61d739e2ae79bf0d313c4fd0`

StepNX implements the documented interactions independently. It reads the
canonical StepNX preview snapshot and may reference only a user-selected local
visual pack in place. It does not load PIUTESTER DAT or Lua resources.

## Confirmed interactions

The supplied PIUTESTER package and its embedded help establish these runtime
controls:

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
determines its field layout. One initialization dialog also selects 1x through
9x and accepts an auxiliary COMMAND. Random-route seeds remain internal.

Confirmed flags are Vanish (`V`), Non-Step (`N`), Flash (`W`), Freedom (`F`),
Mirror (`M`), Random (`R`), vertical inversion (`U`), Judge Reverse (`J`),
Deceleration (`D`), Acceleration (`A`), Exceed (`X`), Random Velocity (`S`), and
Earthworm (`E`). Digits in COMMAND are cumulative and each contributes one
quarter of its numeric value.

The display behavior is not one undifferentiated modifier bit. Static StepEdit
evidence names these NX20 combinations explicitly:

| Function bits | Visibility | StepEdit label | Preview behavior |
| --- | --- | --- | --- |
| Normal | Visible | `__: Normal` | Visible and judged |
| Normal | Appear | `_v: Appear` | Fades in toward the sequence zone |
| Normal | Vanish | `_^: Vanish` | Fades out toward the sequence zone |
| Normal | Invisible | `_X: Invisible` | Not drawn but still judged |
| H family | Visible | `H_: Bonus` | Visible bonus/treasure note |
| H family | Appear | `Hv: Bonus(Appear)` | Bonus note with Appear visibility |
| H family | Vanish | `H^: Hidden(Vanish)` | Registering hidden/vanishing note |
| H family | Invisible | `HX: Hidden` | Registering hidden note |
| Ghost family | Visible | `G_: Ghost` | Ghost artwork; does not register |
| Ghost family | Appear | `Gv: Ghost(Appear)` | Ghost artwork with Appear visibility |
| Ghost family | Vanish | `G^: Ghost(Vanish)` | Ghost artwork with Vanish visibility |

This distinction is required before Ghostbuster or Treasure Hunter semantics
can be implemented honestly. StepNX now preserves and renders the Ghost versus
Bonus/Hidden families, but mission scoring rules for those named modes remain a
separate runtime-capture gate.

Fiesta 2 embeds separate command objects for `display_vanish`,
`display_appear`, `display_nonstep`, `display_freedom`, and `display_flash`.
The independently documented game behavior confirms that Non-Step hides moving
notes, Freedom hides the stationary sequence zone, Vanish hides notes near the
zone, and Flash phase-gates moving-note visibility. StepNX composes these global
effects with each note's own visibility instead of replacing the raw flag.

## Sequence-zone and STEPFX geometry

The StepEdit-compatible noteskin `BASE.png` is a `480×192` atlas row whose
central `384` pixels contain the functional five-lane strip; both 48 px sides
are empty padding. Prime's mode-specific render path draws `BASE` twice with a
translation for Double. Its separate Half Double branch draws `HD1`, translates,
then draws `HD2`; treating the Double calls as two independent Versus fields is
therefore incorrect. StepNX maps each central 384 px strip to exactly five lane
pitches and places the two Double strips edge-to-edge. Notes, input, hold
shafts, and STEPFX use those same lane centres.

The inspected STEPFX PNG frames are opaque RGB images: their alpha is always
255 and roughly 93–96% of their pixels are black or nearly black. PIUTESTER
imports `glBlendFunc`; the available static evidence does not prove the exact
blend factors at the STEPFX draw call. StepNX therefore uses additive
composition for these frames, where black contributes no color, instead of
incorrect source-over composition that produces a black square.

STEPFX records physical/autoplay pad presses separately from judgments. Hold
body/tail ticks and misses therefore cannot retrigger it. Autoplay timestamps
the initial tap/head press at its chart time and discards stale feedback after
a delayed audio update. Optional STEPFX PNGs are decoded before playback, and
painting visits only the bounded recent press history.

Normal judgment is row-based: a chord produces one visible result and combo
increment. Hold head, body, and tail rows still resolve separately. Per-cell
visible judgment remains specific to JN rather than the default preview.

## Implementation evidence levels

The keyboard layout, toggle keys, initialization flow, COMMAND grammar, and
cumulative speed rule are treated as confirmed behavior. Exact judgment
windows, grade math, score increments, gauge changes, modifier curves, and
later-engine presentation are not yet established by independent measurements.

Until those measurements exist:

- F6 labels StepNX counters as `LOCAL` and reports live FPS/paint cost;
- local counters never participate in route or chart serialization;
- Exceed, acceleration/deceleration, random-velocity, Earthworm, and Vanish
  curves remain approximate until synchronized captures calibrate them;
- Under Attack/vertical inversion remains parsed but intentionally unprojected;
- unsupported or approximate behavior is not described as arcade-accurate;
- NXA, Fiesta 2, and Prime comparisons remain runtime validation gates;
- no value inferred from PIUTESTER is promoted into an engine profile merely
  because it looks plausible.

## Required follow-up evidence

Record synchronized captures using small original test charts for NXA, Fiesta
2, and Prime. Each capture should isolate one BPM, Beat Split, Scroll, freeze,
warp, hold, visibility flag, COMMAND modifier, and judgment offset at a time.
Record the executable identity and exact chart hash with every observation.
