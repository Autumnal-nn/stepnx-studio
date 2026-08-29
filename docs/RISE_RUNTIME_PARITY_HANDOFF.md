# R!SE Runtime Parity Audit — Fresh-Chat Handoff

This file is the continuity anchor for continuing the StepNX Studio audit against Pump It Up R!SE without depending on prior chat state.

## Working branch

Primary audit branch: `audit/rise-runtime-parity`

The visual-modifier implementation was developed and validated on `audit/rise-runtime-parity-item45-work`. The validated work tree is ready for promotion into the primary audit branch after the temporary CI workflow is removed.

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

### Snake

`LineBase.PlaySnakeAnim` RVA `0x6390A0` uses the same visible-Y range plus:

```text
xAmplitude = 20
waveRate   = 2
pi         = 3.1415927410125732f
xOffset    = sin(t * pi * waveRate) * xAmplitude
```

Header `bSnake` now drives this path. Earthworm no longer masquerades as horizontal sine motion.

### Header Visibility

`PlayBase.InitData` applies Header Visibility to loaded note state by replacing only the low `VisualEffect` nibble:

```text
Vanish -> 2
Appear -> 1
Hidden -> 0
Visible -> leave serialized value unchanged
```

High bits, including `Effects.bZigZag = 0x10`, are preserved. StepNX performs the rewrite only on runtime event bytes, never on the canonical NX document. Appear/Vanish fade curves remain Animator/asset dependent, so the presentation is not claimed pixel-perfect.

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

These values update `_modeSpeedExt`, then `_modeSpeed = _modeSpeedExt * _blockSpeed`, then non-Smooth display changes pass through SpeedProc.

### Random Velocity

DrawStep proves:

```text
Line % 48 == 0
native RNG result % 4 + 1
```

before writing `_modeSpeedExt`. StepNX uses the exact line gate and signed modulo conversion. The exact Unity RNG stream and native repeated-per-frame rerolls while a qualifying line remains current were not recovered, so the preview uses one deterministic reroll on line entry and marks Random Velocity approximate for that reason.

### COMMAND launch selector

The gameplay initialization dialog no longer accepts arbitrary free text. It exposes the 13 known auxiliary codes as checkable entries:

```text
V N W F M R U J D A X S E
```

Speed remains a separate 1x..9x selector. D/A and S/E are mutually exclusive in the UI because each pair targets one enum-like runtime mode. Legacy string parsing remains for tests and non-UI compatibility.

### Deliberately unresolved visual state

Do not invent transforms for:

- ZigZag: `Effects.bZigZag=0x10`, Header `bZigZag`, and Div params 221/222 are known, but a sufficiently strong direct gameplay consumer has not been recovered;
- Throw: Flat/Sink/Rise is known and `LineBase.PlayThrowAnim` exists, but movement depends on Animator/assets;
- exact Appear/Vanish Animator fade curves;
- exact Random Velocity Unity RNG/cadence.

## Final validation checkpoint

The completed repository-wide validation for Items 0 through 6 is:

```text
GitHub Actions run: 33256211227
Commit tested: 9ff6f29f042a41e4e163e0df81d88074eb95a622
Ran 476 tests in 1.975s
OK
```

The run includes dedicated regressions for LineBase constants and curves, Snake, Header Visibility without document mutation, Earthworm including the loaded `_BPM`/`msPerLine` alias and Skip behavior, Random Velocity gate/conversion, speed-mode resolution, and the selectable COMMAND dialog.

The first final-attempt run exposed two test regressions, not production behavior defects: a source-string assertion tied to the old renderer shape and a zero-tolerance assumption incompatible with R!SE's float32 pi. Both were corrected before the green checkpoint without weakening the native implementation.

## Remaining source-gated side paths

- exact ZigZag transform consumer;
- Throw Animator/asset movement;
- exact Random Velocity RNG stream/cadence;
- exact Appear/Vanish Animator curves;
- real producer of `CommonModifier.SpeedBoost`;
- challenge-mode HPBar.Add branch;
- forced-judgment Div 999 consumer;
- any Split-level modifier dispatcher if one is eventually recovered.
