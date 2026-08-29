# Prime 2 path-modifier audit

Date: 2026-08-29

Scope: use the supplied Pump It Up Prime 2 `exec` only as a historical runtime arbiter for legacy path modifiers where R!SE and PIUTESTER expose different constants. R!SE remains the primary specification for modern Header StepParam behavior.

Supplied executable SHA-256:

`21c9c1739ff68780ecbc13737bab62bd23684ed8454769b3ddd0caebf9250ec9`

The executable is UPX-packed. Analysis was performed on a reconstructed/unfiltered copy without executing the game.

## Snake: 30 is correct for Prime 2

The Prime 2 rendering path around VA `0x08070bbf` tests its Snake state and enters this scalar path:

```text
0x08070bcc  load  pi
0x08070be0  phase *= pi
0x08070c01  call  sinf
0x08070c06  reload 60.0
0x08070c28  result *= 60.0
0x08070c2c  result *= 0.5
```

The constant at VA `0x081805d4` is IEEE-754 float `60.0`. The constant used by the final multiply at `0x0817e850` is `0.5`.

Therefore the historical Prime 2 Snake excursion is:

```text
xOffset = sin(pi * phase) * 60 * 0.5
        = sin(pi * phase) * 30
```

This resolves the 20-versus-30 discrepancy:

- R!SE `LineBase.PlaySnakeAnim`: amplitude **20** (`LineBase.xAmplitude` constructor default).
- Prime 2 legacy Snake: amplitude **30**.

StepNX intentionally keeps these as separate helpers rather than forcing one generation's constant onto the other.

## Sink / Rise

Prime 2 reads a three-state path value around VA `0x08070c5a`. State 0 bypasses the path. The two active states use opposite signs of the same sine displacement.

Standard branch constants:

- span: `453.0` at `0x081805f4`
- base amplitude: `64.0` at `0x0817e870`
- post-sine multiplier: `1.5` at `0x081805e8`
- resulting amplitude: `64 * 1.5 = 96`

The second active state substitutes `-64.0` before the same sine path, yielding the opposite direction. This matches the runtime enum ordering already recovered as Sink=1, Rise=2.

Prime 2 also contains an external-state branch choosing `200/-200`, giving `300/-300` after the 1.5 multiplier. The producer of that external state is not identified, so StepNX does not enable the alternate amplitude implicitly.

## Implementation boundary

The Studio preview now treats:

- R!SE Header Snake as the modern 20-unit LineBase path;
- selectable legacy Snake as the Prime 2 30-unit path;
- selectable Sink/Rise as the recovered Prime 2 sine path;
- R!SE Header Throw as using the historical curve only as a compatibility projection because the modern runtime ultimately drives an Animator;
- Exceed as a separately labelled approximation until its exact legacy affine coefficient is recovered.

No proprietary executable bytes or game assets are copied into the repository.
