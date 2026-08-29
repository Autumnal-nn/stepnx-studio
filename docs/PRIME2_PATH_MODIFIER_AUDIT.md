# Prime 2 path-modifier audit

Date: 2026-08-29

Scope: use the supplied Pump It Up Prime 2 `exec` as the historical runtime arbiter for legacy path modifiers whenever the current R!SE build only preserves modifier state or otherwise lacks a validated gameplay consumer. R!SE remains the primary specification where an actual reproducible consumer exists. Snake is the explicit exception: its dormant R!SE state/helper is not treated as a behavioral specification.

Supplied executable SHA-256:

`21c9c1739ff68780ecbc13737bab62bd23684ed8454769b3ddd0caebf9250ec9`

The executable is UPX-packed. Analysis was performed on a reconstructed/unfiltered copy without executing the game.

## Snake: 30 is the runtime arbiter

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

The current R!SE image contains a 20-unit `LineBase` Snake helper/state path, but this audit did not validate a gameplay consumer that makes that helper authoritative. Per project policy, dormant implementation is not promoted into preview semantics. StepNX therefore uses the Prime 2 30-unit path for Snake visualization, including when a loaded Header exposes Snake state.

## Sink / Rise

Prime 2 reads a three-state path value around VA `0x08070c5a`. State 0 bypasses the path. The two active states use opposite signs of the same sine displacement.

Standard branch constants:

- span: `453.0` at `0x081805f4`
- base amplitude: `64.0` at `0x0817e870`
- post-sine multiplier: `1.5` at `0x081805e8`
- resulting amplitude: `64 * 1.5 = 96`

The second active state substitutes `-64.0` before the same sine path, yielding the opposite direction. This matches the runtime enum ordering already recovered as Sink=1, Rise=2.

Prime 2 also contains an external-state branch choosing `200/-200`, giving `300/-300` after the 1.5 multiplier. The producer of that external state is not identified, so StepNX does not enable the alternate amplitude implicitly.

## Exceed

Prime 2 and the PIUTESTER lineage confirm that Exceed/X Mode is a real horizontal path transform, not a lane permutation. The exact affine coefficient has not yet been recovered strongly enough to call the current 2D projection source-exact. The preview keeps that approximation isolated in `legacy_exceed_x_offset()` rather than contaminating Mirror, Under Attack, Drop, or Random semantics.

## Implementation boundary

The Studio preview now treats:

- Snake as the Prime 2 30-unit historical path; the dormant R!SE 20-unit helper is deliberately ignored as behavioral evidence;
- selectable Sink/Rise as the recovered Prime 2 sine path;
- R!SE Header Throw as using the historical curve as a compatibility projection because the modern runtime ultimately drives an Animator;
- path-modified long-note shafts as sampled trajectories rather than straight endpoint rectangles;
- Exceed as a separately labelled approximation until its exact legacy affine coefficient is recovered.

No proprietary executable bytes or game assets are copied into the repository.

## Visual validation follow-up

- NX20 Snake Path `221/222` boundary convergence was visually validated against legacy gameplay on 2026-08-29. The phase-zero identity convergence is locked; later preview work must not replace it without contradictory runtime/capture evidence.
- Legacy Appear/Vanish remains a continuous fade, but its spatial window is compact around the judge line. StepNX now scales that window to `1.5 * rendered note size` instead of viewport height; the exact legacy easing curve remains approximate.
- PIUTESTER/NX2 compatibility command `^` is restored to the selector as **NX Mode**. It is distinct from `x` / Exceed. No visual consumer is invented until source evidence establishes its rendering behavior.
