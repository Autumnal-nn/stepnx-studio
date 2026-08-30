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

Prime 1's live `path_exeed` flag is the global byte at `0x0AC0255D`; it is set by the historical Exceed path option and consumed directly in the note renderer at `0x0806D3E2..0x0806D426`. The renderer forms `d = beatDistance * 60 * highSpeed`. Native five-lane bank 0 receives `+d`; bank 1 receives `-d` relative to its ordinary bank origin. Single retains the selected player's sign. The normal Y renderer simultaneously uses `receptorY - d` in native bottom-left coordinates, so StepNX's top-left projection travels `+d` vertically. Exceed is therefore a true 1:1 diagonal in native path units, not a horizontal modifier layered over R!SE's later 65.647/72 vertical projection.

There is no absolute value, viewport-height normalization, or half-field clamp. StepNX scales the native 60-unit path pitch by rendered note size and otherwise preserves that signed, unbounded producer exactly. Legacy Acceleration/Deceleration remains the earlier Y-path producer when explicitly active, matching the native ordering before `path_exeed`. This reproduces EF029/PIUTESTER's diagonal rail, including notes and items entering from well outside the visible field.

## Implementation boundary

The Studio preview now treats:

- Snake as the Prime 2 30-unit historical path; the dormant R!SE 20-unit helper is deliberately ignored as behavioral evidence;
- selectable Sink/Rise as the recovered Prime 2 sine path;
- R!SE Header Throw as using the historical curve as a compatibility projection because the modern runtime ultimately drives an Animator;
- path-modified long-note shafts as sampled trajectories rather than straight endpoint rectangles;
- Exceed as the recovered signed Prime/NXA five-lane-bank path, with no viewport clamp.

No proprietary executable bytes or game assets are copied into the repository.

## Visual validation follow-up

- NX20 Snake Path `221/222` boundary convergence was visually validated against legacy gameplay on 2026-08-29. The phase-zero identity convergence is locked; later preview work must not replace it without contradictory runtime/capture evidence.
- NX20 Snake Path `221/222` remains locked after visual validation; this port does not alter its code or interpolation.

## Prime/NXA visibility mask and NX Mode

Prime and NXA independently generate the same 32x512 RGBA visibility texture. The low VisualEffect states are 0 Invisible, 1 Appear, 2 Vanish, 3 Visible. The recovered mask constants are centre 256, vertex offset 16.5, alpha bias 128 and slope +/-8 per logical pixel. On the native 640x480 viewport, alpha 128 occurs at screen Y 240.5 and the complete transition occupies only about 32 logical pixels (roughly Y 224.5..256.5). StepNX now renders Appear/Vanish into screen-space layers and applies that vertical mask after path/perspective transforms, matching the texture consumer rather than assigning one opacity to the entire sprite.

Header 22 and COMMAND `^` feed the same **NX Mode** state. Both supplied executables select a 75-degree perspective instead of the normal 90-degree projection. The perspective helper derives camera distance from viewport **height**, translates projection by `(-W/2,-H/2)`, and then uses a +Y `LookAt`. The four native branches are explicit: plain NX uses `Rx(-60)` plus centered `Scale(1.5,+1.5,1.5)`; NX+Drop uses `T(0,H)`, `Rx(-120)` and the same positive-Y scale; NX+Under Attack uses `T(0,H)`, `Rx(-120)`, centered `Scale(1.5,-1.5,1.5)`, then the native UA `T(W,H)/Rz(180)` tail; NX+UA+Drop uses `Rx(-60)`, the negative-Y scale, then that same UA tail. StepNX collapses each fixed-Z plane to the exactly equivalent projective homography, including Qt top-left to OpenGL bottom-left conversion. Sink/Rise uses the recovered NX-specific +/-300 Z branch.

Prime anchors: no-UA NX branch `0x080ae1de`, UA+NX branch `0x080ae0bb`, shared tilt targets near `0x080af5a3/0x080af5cc`, perspective helper `0x08087350`. NXA independently reproduces the same branch structure around `0x0808edc6`, `0x0808f362`, `0x0808fb84` and `0x0808fbce`.

## Native playfield geometry and Division 200

The Prime/NXA renderer keeps three independent SD measures instead of deriving everything from a single cell size: lane pitch `50`, legacy path unit `60`, and note/item quad size `64`. The native 640-wide judge-line centres are `160/480` for side Single/Versus banks, `194/446` for Double, and `320` for Centered. StepNX now preserves those logical coordinates, centres them without stretching on wider preview windows, and scales the complete logical system only when the viewport is narrower than 640.

The four render states are explicit and do not rewrite authored columns or judgment lanes: `0=Single`, `1=Double`, `2=Versus`, `3=Centered`. Division Metadata `200` is resolved from the active block and therefore may switch presentation as native timing advances. When no `200` is present, StepNX intentionally keeps its authoring defaults: five-column charts launch Centered; six- and ten-column charts launch Double.

This separation also fixes legacy path composition: Exceed, historical Acceleration/Deceleration, and the Prime Snake path scale through the native 60-unit path measure, while note/item artwork continues to use the independent 64-unit quad. Half-Double bank selection uses `start_column + lane`, so its native 2..7 span crosses banks at the correct boundary.

## Dense long-note preview performance

Fiesta 2 `/D/EF1299` is the stress reference for runtime preview density. Its NX contains 12,817 long-body cells and several BeatSplit=128 sections, including a block with 2,890 body ticks over 320 rows. A 60 fps screen capture exposed 7-10 repeated display frames (roughly 120-170 ms) while those walls were active.

Long-body `0x0B` events remain fully present in `RuntimeEventStream` and `GameplaySession` for judgment, combo, score and gauge semantics, but they are now excluded from the standalone render-event index because the renderer already represents them through paired hold shafts. The preview also caches one native timing state, playfield geometry and lane map per frame/state, culls render events once per paint, groups them by visibility once, and avoids allocating full-screen Appear/Vanish intermediate images when that family cannot contribute pixels. These are projection-only optimizations; authored NX and runtime judgment semantics are unchanged.

## Hold terminal collapse

Legacy gameplay capture (Fiesta 2 EF1299) confirms that high-tick/low-projection holds can collapse visually into a single ordinary head arrow. The renderer must not bake a repeatable shaft into head/tail terminal sprites. StepNX therefore draws the shaft as a separate behind-terminal layer, tail before head, and suppresses body/tail cells when the complete projected hold fits beneath one terminal. This applies to authoring zoom and gameplay projection, including Scroll=0, without removing encoded BODY/tail cells from the document or runtime judgment stream.
