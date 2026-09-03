# R!SE Runtime Parity Audit — Fresh-Chat Handoff

> Historical continuity handoff. The branch names and work sequencing in this
> file describe the runtime-parity work while it was in progress. The completed
> findings were promoted and are summarized authoritatively in
> `RISE_RUNTIME_PARITY_AUDIT.md`; current product status belongs in `STATUS.md`
> and `ROADMAP.md`. The technical evidence below is retained as an audit trail,
> not as instructions to resume an old branch.

This file is the continuity anchor for continuing the StepNX Studio audit against Pump It Up R!SE without depending on prior chat state.

## Working branch

Primary audit branch: `audit/rise-runtime-parity`

The visual-modifier implementation was developed and validated on `audit/rise-runtime-parity-item45-work`. The validated work tree has no temporary CI workflow and is the promotion source for the primary audit branch.

## Primary-source policy

Primary specification:

- `GameAssembly.dll` — Pump It Up R!SE IL2CPP runtime
- `dump.cs` — IL2CPP type/field/enum metadata
- `script.json` — IL2CPP method/address map

When Studio behavior or an old test conflicts with the runtime, the runtime wins. Do not preserve a regression merely because a test encoded it first. Keep R!SE runtime semantics separate from the historical NXA/Fiesta authoring registries because numeric metadata IDs are reused across generations.

## Completed Item 0 — Smooth migration

`DivFlags` are independent bits:

```text
bSmooth = 0x01
bSkip   = 0x02

0 = normal
1 = Smooth
2 = Skip
3 = Smooth + Skip
```

`StepLoader.Load` RVA `0x751B80`:

```text
if flags & bSkip:
    msPerLine = 0
else:
    msPerLine = 60000 / (BPM * BeatSplit)

if msPerLine > 0 and rawSpeed > 0:
    Gap = rawGap / (BeatSplit * msPerLine)
else:
    Gap = 0

if rawSpeed < 0:
    Speed = -rawSpeed
```

`PUMPPlayer.DrawStep()` RVA `0x748B50` tests only bit `0x01` for Smooth. Smooth interpolation lives in `NativeTimingProjection.block_speed_at()` and uses the previous loaded Div Speed, previous Div end and current Div end. Skip-only `2` does not interpolate.

## Completed Item 1 — ApplyStepParamToMod / EffectiveModifier

Primary anchor: `PlayBase.ApplyStepParamToMod` RVA `0x659F00`.

Scope:

- runtime consumes the Step global Header StepParam array at `Step + 0x28`;
- Split metadata remains preserved at `Split + 0x18` but no second modifier dispatcher has been recovered;
- Header params are therefore the only source applied to `EffectiveModifier`.

Lookup semantics:

- `Step.GetParam` RVA `0x74CC30` is first-wins;
- `Step.GetFloatParam` RVA `0x74CC90` reinterprets raw uint32 bits as float;
- never collapse runtime StepParams into a normal dict.

Important recovered Header mappings:

```text
0     Speed
1     SpeedMode: 0 Static, 1 Earthworm, 2 RandomVelocity
2     AccDec: 0 Linear, 1 Accel, 2 Decel
16    Visibility: 0 Visible, 1 Vanish, 2 Appear, 3 Hidden
17    Freedom
18    Flash
19    RandomSkin
21    Exceed
22    NX
32    Direction: 0 Normal, 1 180, 2 UpsideDown, 3 Mirror
33    Throw: 0 Flat, 1 Sink, 2 Rise
34    Snake
35    ZigZag
48    MirrorTurn
49    MirrorLR
50    Random
64    JudgeBank
65    PerfectFrame / Interval decoder
66    JudgeReverse
67    HideJudge
68    JudgeByNote
69    ComboDisplay
70    AltSkinScoreFactor and AltSkinGaugeFactor
71    FreePerformance
80    Gauge Max / HPBar Limit
81    Gauge Display Max
82    Gauge Initial Life
83    Gauge Break / Stage Break
84    MissComboBreak
85    GaugeLinkFactor
900..905 six skin slots
1001  Level
1111  SpeedX multiplier
```

Important no-write findings:

- ID 20 ForceBGA getter result is discarded by this dispatcher;
- ID 51 Runner is declared in the enum but has no branch here;
- ID 1110 SpeedBoost getter result is discarded here even though `CommonModifier.SpeedBoost` is a real field consumed elsewhere.

Header 65 decoder:

```text
x = value + 5
q = trunc(x / 10)
r = x - q*10
PerfectFrame = (75 - q) / 10.0
Interval     = (10 - r) * 0.5
```

## Completed Item 2 — Speed / Gap / `_baseVelocity`

Primary anchors:

- `PUMPPlayer.SetSpeed` RVA `0x746330`
- `PUMPPlayer.SpeedProc` RVA `0x746360`
- `PUMPPlayer.DrawStep` RVA `0x748B50`
- `Step.currentGap` RVA `0x74C7B0`
- `LineBase.RePos` RVA `0x638CA0`
- `LineBase.CreateSplits` RVA `0x639720`

Native speed state is explicit:

```text
_modeSpeedExt = selected/user speed
_blockSpeed   = active Div speed
_modeSpeed    = _modeSpeedExt * _blockSpeed
pHighSpeed    = displayed speed
```

`SpeedProc` moves `pHighSpeed` toward `_modeSpeed` by `0.05` each `1/60 s` tick. Block changes and Smooth updates remain on the DrawStep path rather than being confused with user speed easing.

Negative serialized Speed does not create a preview freeze. The loader uses its sign only while constructing Gap and then normalizes it positive.

Recovered LineBase geometry:

```text
LineBase start Y        = 50
TargetArrow Y           = 608
_startGapTime           = 8.5
_baseVelocity           = (608 - 50) / 8.5
                        = 65.6470588
modern note render unit = 72
```

Runtime Y placement uses `PlayBase.GetBlockBeat(block,line) * _baseVelocity`. `PreviewEvent.position` remains a compatibility/culling axis and is not treated as the native visual distance.

## Completed Item 3 — JudgeLine / JudgeNote / JudgeUnit structure

Primary anchors:

- `PUMPPlayer.JudgeNote` RVA `0x747320`
- `PUMPPlayer.JudgeLine` RVA `0x7474D0`
- `PUMPPlayer.JudgeUnit` RVA `0x747A60`

Recovered note routing:

- native TypeMask low two bits: Item=1, Special=2, Normal=3;
- exact NoJudge mask is `0x20`;
- `bNoRush = 0x10`;
- bank comes from the top two bits of the 16-bit Param field;
- JudgeLine resolves one bank at a time;
- JudgeByNote resolves eligible cells independently.

Long-note distinction:

```text
47 / 4B / 4F = long without bNoRush = rush/roll JudgeNote path
57 / 5B / 5F = long with bNoRush    = aggregate JudgeLine path
```

JudgeUnit structural projection:

- negative grade becomes Miss;
- `bNoMiss` is preserved for the later bypass;
- `AltSkinFactor = 1 + altSkinCount/totalNoteCount * AltSkinScoreFactor`;
- return value is `grade <= Great`.

## Completed Item 4 — Native judgment windows

Primary anchors:

- `PUMPPlayer.SetJudgeTiming` RVA `0x746B00`
- `Step.SetJudgeTiming` RVA `0x74BB50`
- `Step.Judge` RVA `0x74D100`
- `Step.GetGrade` RVA `0x7508E0`

Base frame:

```text
16.66666603088379 ms
```

`PUMPPlayer.SetJudgeTiming` constructs:

```text
P = PerfectFrame * frame
I = Interval     * frame
D = 2.5          * frame
N = 4
```

If a validated producer has already populated `CommonModifier.SpeedBoost > 0`, the entire frame unit is multiplied by SpeedBoost. Header 1110 alone does not populate it.

`Step.SetJudgeTiming` stores:

```text
Start = -(P + 3*I + D)
End   =  P + 3*I
```

`Step.Judge` is asymmetric:

```text
early input: gradeTime = -error
late input:  gradeTime = max(0, error - D)
```

`Step.GetGrade`:

```text
x = gradeTime - P
if x <= 0:
    grade = Perfect
else:
    grade = trunc(x / I + 1)
    grade = min(grade, 3)
```

`NativeJudgeTiming` replaces the old fixed symmetric preview table. Header 65 changes actual GameplaySession timing.

## Completed Item 5 — Native score and gauge

### Score

Primary anchors:

- `PUMPPlayer.JudgeStep_PostProcess` RVA `0x748000`
- `PUMPPlayer.GetScore` RVA `0x748A40`

Recovered base score table:

```text
Perfect  1000
Great    1000
Good      500
Bad       100
Miss     -200
```

Ordinary-note Miss uses the special `-300` PostProcess path.

Perfect/Great receive +1000 once the per-bank combo after increment reaches 51. Chord counts of 3 use x1.5 and 4+ use x2, truncating before the JudgeUnit AltSkin multiplication. AddCount floors accumulated score at zero.

Combo behavior:

```text
Perfect / Great -> increment
Good            -> preserve
Bad / Miss      -> clear
```

### HPBar / gauge

Native setup:

```text
Life    = 500
Limit   = 1000 + 3 * min(Level, 50)^2
DispMax = 1000
```

Header 80/81/82 override Limit, DispMax and Life after setup. Mode-specific factor presets and native Perfect/Great/Good/Bad/Miss deltas are implemented. A Miss carrying NoMiss bypasses the normal PostProcess/gauge path.

Current preview field-width bridge:

- 5 columns -> Single
- 6 columns -> HalfDouble
- 10 columns -> Double
- unusual widths retain the HalfDouble fallback rather than inventing a new HPBar type.

The separate challenge-game HPBar.Add branch remains source-gated.

## Completed Item 6 — visual modifier pass

### Accel / Decel

`LineBase.GetAccDecYOffset` RVA `0x638B20` and constructor RVA `0x63B280` establish:

```text
_yMin     = 200
_yMax     = 550
_accPow   = 1.5
_accScale = 1
scale     = -200
```

For normalized `t = clamp((Y-yMin)/(yMax-yMin),0,1)`:

```text
Accel: (1 - pow(t, 1.5)) * -200
Decel: pow(1 - t, 1.5)   * -200
```

The previous synthetic pixel powers were removed. `TryGetMaxVisibleSplitLocalY` can substitute a grouped child maximum before this scalar formula; flattened preview events cannot reproduce that grouping perfectly and the limitation is explicit.

That modern Header path is **not** the historical PIUTESTER/NX2 Acceleration/Deceleration command path. The supplied unpacked Prime 1 and NXA executables independently agree on the older renderer. With `x = beatDistance * 60 * highSpeed`:

```text
Acceleration (mode 1): 600 - 50000 / (x + 83.33333587646484)
Deceleration (mode 2): x^3 / 1600
```

Prime 1 uses the same constants through its SSE branch around `0x806D350..0x806D809`; NXA reproduces them through the x87 branch around `0x8093475..0x809377C`. StepNX now keeps these historical A/D commands separate from the R!SE Header ID 2 LineBase curve instead of incorrectly routing both through one formula.

### Under Attack / Drop

Prime 1 confirms the sequence-zone transform applies to the complete rendered field, not just the receptor strip. Under Attack performs the 180-degree field rotation; the same painter transform therefore affects receptor artwork, note positions, note artwork, holds and pad feedback. Drop remains the independent vertical-flip bit. Their composition is preserved as the native bitmask rather than collapsed into a lane permutation.

### Snake

The current R!SE image preserves Snake state plus a 20-unit `LineBase` helper, but no validated gameplay consumer for that state was recovered. Per the audit policy, that dormant implementation is **not** treated as preview behavior.

Prime 2 is the historical runtime arbiter. Its rendering path proves:

```text
xOffset = sin(pi * phase) * 60 * 0.5
        = sin(pi * phase) * 30
```

StepNX therefore uses the Prime 2 30-unit path for Snake visualization, including loaded Header Snake state. Long-note shafts are sampled along the path instead of remaining straight endpoint rectangles. Earthworm remains a separate speed mode.

### Header Visibility

`PlayBase.InitData` applies Header Visibility to loaded note state by replacing only the low `VisualEffect` nibble:

```text
Vanish -> 2
Appear -> 1
Hidden -> 0
Visible -> leave serialized value unchanged
```

High bits, including `Effects.bZigZag = 0x10`, are preserved. StepNX performs the rewrite only on runtime event bytes, never on the canonical NX document. Legacy gameplay capture confirms that Appear/Vanish are continuous alpha fades rather than binary midpoint gates; StepNX restores the distance ramp while still treating the exact engine material/Animator curve as an approximation.

### Earthworm

`PUMPPlayer.DrawStep` RVA `0x748B50` reads:

- current time from inherited `Step.msCurTime` at +0x24;
- `Div.nBeatSplit` at +0x24;
- the Div field at +0x14.

`Div_h_t.msPerLine` aliases `_BPM` at +0x14. StepLoader therefore overwrites the serialized BPM there before DrawStep runs. Earthworm compares:

```text
nBeatSplit * loaded _BPM/msPerLine
```

against `333.3333435`. Normal Divs therefore compare milliseconds per beat; Skip loads the value as zero.

The two square waves are:

```text
>= 333.33334: msCurTime % 500 <= 250 -> 3x, else 2x
<  333.33334: msCurTime % 360 <= 180 -> 2x, else 1x
```

These values update `_modeSpeedExt`, then `_modeSpeed = _modeSpeedExt * _blockSpeed`, then non-Smooth display changes pass through SpeedProc. StepNX evaluates this on the native 1/60 s DrawStep cadence, independent of the caller's `advance()` chunk size.

### Random Velocity

DrawStep proves:

```text
Line % 48 == 0
native RNG result % 4 + 1
```

before writing `_modeSpeedExt`. StepNX uses the exact line gate, 1/60 s DrawStep cadence, repeated rerolls while a qualifying line remains current, and signed modulo conversion. The standalone preview intentionally uses its deterministic RNG rather than attempting to clone Unity's private RNG state; exact RNG identity is not a parity requirement for this modifier.

### ZigZag

Prime 1 contains a live `path_zigzag` consumer around `0x806D6EF`. Split param 222 is the path start and param 221 is the keyframe interval; both default to 1. After the start, the renderer interpolates through nine lane-permutation keyframes for phase 0 through 8 and then holds keyframe eight. The permutation generator uses the recovered 32-bit LCG:

```text
state = state * 0x0019660D + 0x3C6EF35F
pick  = (state >> 8) % remaining
```

StepNX ports that consumer and preserves Split 221/222 into the runtime stream. Prime also mixes an engine-owned per-player value into the initial seed; the standalone preview substitutes its resolved route seed, so the path mechanics are recovered while the exact native permutation sequence is intentionally preview-local. Header ZigZag state now drives this path.

### COMMAND launch selector

The gameplay initialization dialog no longer accepts arbitrary free text. It exposes 18 semantic modifier choices: Vanish, Appear, Non-Step, Flash, Freedom, Mirror, Random, Under Attack, Drop, Judge Reverse, Deceleration, Acceleration, Exceed, Sink, Rise, Snake, Random Velocity and Earthworm.

Speed remains a separate 1x..9x selector. Acceleration/Deceleration and Random Velocity/Earthworm are mutually exclusive in the UI because each pair targets one enum-like runtime mode. Historical command characters remain internal compatibility keys for tests and non-UI callers.

### Deliberately unresolved visual state

Do not invent transforms for:

- R!SE's exact Throw Animator/asset movement; the preview intentionally uses the recovered Prime 2 sine path as a historical compatibility projection;
- exact Appear/Vanish Animator/material fade curves.

ZigZag is no longer source-gated: Prime 1 supplied the historical consumer. Random Velocity's exact Unity RNG sequence is deliberately not a parity target; its gate, cadence and speed conversion are the behaviorally relevant pieces.

## Final validation checkpoint

The completed repository-wide validation after the visual-command correction pass is:

```text
GitHub Actions run: 33274239781
Commit tested before the resulting production commit: 9f540e350fcb27e66bb8e61b4c305405258d8c6f
Production commit: 9aebcb53634fbdc14462dc1553a77a0d6cacc3d9
Ran 491 tests in 4.477s
OK
```

This checkpoint includes dedicated regressions for independent UA/Drop bitmask geometry, whole-field Under Attack rotation, row-wise Random projection with hold continuity, the Prime/NXA historical Acceleration/Deceleration formulas, the distinct R!SE Header AccDec curve, Prime 2 Snake amplitude 30, Prime 2 Sink/Rise paths, Prime 1 ZigZag keyframes plus Split 221/222 preservation, Header Visibility without document mutation, Earthworm fixed DrawStep cadence, Random Velocity repeated qualifying-line rerolls, external-advance chunk invariance, and the complete 18-entry semantic modifier selector. Path-modified long-note shafts are rendered by sampling the same trajectory as their note heads.

The dormant R!SE Snake 20-unit helper is deliberately **not** accepted as behavior because no validated gameplay consumer was recovered; Prime 2 is the historical runtime arbiter for Snake.

## Remaining source-gated side paths

- exact R!SE Throw Animator/asset curve; the preview uses the recovered Prime 2 historical sine projection instead;
- exact Appear/Vanish Animator/material curves; the current fade is an explicit visual approximation;
- exact legacy Exceed affine coefficient; current X-mode projection is explicitly approximate and isolated;
- real producer of `CommonModifier.SpeedBoost`;
- challenge-mode HPBar.Add branch;
- forced-judgment Div 999 consumer;
- any Split-level modifier dispatcher if one is eventually recovered.

- Exceed correction: the recovered linear `d` is now shared by X and Y, removing the residual R!SE vertical-scale mismatch seen in EF029.

- Prime/NXA playfield geometry is now explicit: 50-unit lane pitch, 60-unit legacy path measure and 64-unit note quad, with Single/Double/Versus/Centered layouts and active-block Division 200 projection. Five-column launch defaults to Centered; six/ten-column launch defaults to Double.

- Prime/Fiesta/NXA Header Metadata 0 is an already-final IEEE-754 speed multiplier, not R!SE's quarter-normalized Header 0. EF1299 stores `4.0` (`0x40800000`), and the local corpora contain non-quarter values such as `2.80`, `3.66`, `4.35`, and `5.50`; legacy preview launch must therefore use the float directly before downstream Header 1111 multiplication.
- Hold-terminal z-order is intentionally head-last in both authoring and gameplay renderers. Dense high-BeatSplit charts use very short holds as tap-like visuals; when head/tail artwork overlaps, the head must remain the visible top terminal.
- EF1299 paint cost is now stable near the user's ~2 ms after body and shaft culling. Remaining temporary ~20 fps drops in BeatSplit/TickCount-128 sections occur with paint staying low and therefore point to GameplaySession judgment/tick processing rather than anticipatory rendering.

- Dense-long runtime optimization: autoplay now advances predecoded judgment groups instead of feeding every body through `_record_event`/`_finalize_group` and then traversing the same stream again through the manual Miss cursor. Per-cell `judgments` and native score/combo/gauge semantics remain intact. Perfect-group projection is prepared at session construction, group event keys are cached, and `GameplayStats` mutates in place to remove one dataclass allocation per judged group. F6 now reports `ADV` separately from `PAINT`, plus events/groups consumed by the latest runtime tick.

- Dense playback host optimization: authoring TimelineWidget coalesces contiguous explicit long BODY rows into one raster shaft only while playback projection is active. Encoded rows and paused authoring remain lossless. Gameplay F6 exposes the host timeline's previous paint cost as HOST to distinguish shared-Qt-thread stalls from gameplay PAINT/ADV.

- External preview ownership: while one or more standalone gameplay preview windows exist, Audio > Follow Chart is forced unchecked and disabled. Its exact prior checked/enabled state is restored when the final preview is destroyed. This removes authoring-follow repaint pressure from the shared Qt GUI thread without freezing the editor or audio transport.
- Collapsed long rendering: the gameplay renderer no longer enforces a synthetic 2 px shaft. Projected zero/subpixel shafts are omitted; shafts are also omitted while both visible terminal quads overlap. Active sustains may still draw a short shaft after a terminal ages out. This is screen-space raster policy only and does not alter NX timing/Scroll semantics.