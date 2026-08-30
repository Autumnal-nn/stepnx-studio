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

Prime/NXA identify the `200/-200` branch as **NX Mode**. After the same 1.5 multiplier, NX Mode therefore uses `+/-300` while the normal branch remains `+/-96`. StepNX selects the 300-unit depth branch whenever Header 22 or COMMAND `^` enables NX Mode.

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
- NX20 Snake Path `221/222` remains locked after visual validation; this port does not alter its code or interpolation.

## Prime/NXA visibility mask and NX Mode

Prime and NXA independently generate the same 32x512 RGBA visibility texture. The low VisualEffect states are 0 Invisible, 1 Appear, 2 Vanish, 3 Visible. The recovered mask constants are centre 256, vertex offset 16.5, alpha bias 128 and slope +/-8 per logical pixel. On the native 640x480 viewport, alpha 128 occurs at screen Y 240.5 and the complete transition occupies only about 32 logical pixels (roughly Y 224.5..256.5). StepNX now renders Appear/Vanish into screen-space layers and applies that vertical mask after path/perspective transforms, matching the texture consumer rather than assigning one opacity to the entire sprite.

Header 22 and COMMAND `^` feed the same **NX Mode** state. Both supplied executables select a 75-degree perspective instead of the normal 90-degree projection. The perspective helper derives camera distance from viewport **height**, translates projection by `(-W/2,-H/2)`, and then uses a +Y `LookAt`. The four native branches are explicit: plain NX uses `Rx(-60)` plus centered `Scale(1.5,+1.5,1.5)`; NX+Drop uses `T(0,H)`, `Rx(-120)` and the same positive-Y scale; NX+Under Attack uses `T(0,H)`, `Rx(-120)`, centered `Scale(1.5,-1.5,1.5)`, then the native UA `T(W,H)/Rz(180)` tail; NX+UA+Drop uses `Rx(-60)`, the negative-Y scale, then that same UA tail. StepNX collapses each fixed-Z plane to the exactly equivalent projective homography, including Qt top-left to OpenGL bottom-left conversion. Sink/Rise uses the recovered NX-specific +/-300 Z branch.

Prime anchors: no-UA NX branch `0x080ae1de`, UA+NX branch `0x080ae0bb`, shared tilt targets near `0x080af5a3/0x080af5cc`, perspective helper `0x08087350`. NXA independently reproduces the same branch structure around `0x0808edc6`, `0x0808f362`, `0x0808fb84` and `0x0808fbce`.
