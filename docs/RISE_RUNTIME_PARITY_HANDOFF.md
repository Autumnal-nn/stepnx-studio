# R!SE Runtime Parity Audit — Fresh-Chat Handoff

This file is the continuity anchor for continuing the StepNX Studio audit against Pump It Up R!SE without depending on prior chat state.

## Working branch

Primary audit branch: `audit/rise-runtime-parity`

The current implementation checkpoint was developed on an isolated work branch and should only be fast-forwarded into the primary audit branch after the full suite is green and the temporary CI workflow is removed.

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

`PUMPPlayer.DrawStep()` RVA `0x748B50` tests only bit `0x01` for Smooth. Smooth interpolation now lives in `NativeTimingProjection.block_speed_at()` and uses the previous loaded Div Speed, previous Div end and current Div end. Skip-only `2` does not interpolate.

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

Native speed state is now explicit:

```text
_modeSpeedExt = selected/user speed
_blockSpeed   = active Div speed
_modeSpeed    = _modeSpeedExt * _blockSpeed
pHighSpeed    = displayed speed
```

`SpeedProc` moves `pHighSpeed` toward `_modeSpeed` by `0.05` each `1/60 s` tick. Block changes and Smooth updates remain on the DrawStep path rather than being confused with user speed easing.

Negative serialized Speed no longer creates a fake preview freeze. The loader uses its sign only while constructing Gap and then normalizes it positive.

Recovered LineBase geometry:

```text
LineBase start Y       = 50
TargetArrow Y          = 608
_startGapTime          = 8.5
_baseVelocity          = (608 - 50) / 8.5
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

Long-note distinction that invalidated old preview tests:

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

`NativeJudgeTiming` replaces the old fixed symmetric preview table. Header 65 now changes actual GameplaySession timing.

With default `PerfectFrame=2.5`, `Interval=2.5`, `Delay=2.5 frames`, the late side gets one additional Delay band before grade evaluation, exactly as the native Step path does.

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

Perfect/Great combo bonus:

```text
if per-bank combo after increment >= 51:
    score += 1000
```

Chord multiplier, using total JudgeUnit count:

```text
1-2 notes: x1
3 notes:   x1.5, truncate
4+ notes:  x2
```

Then the JudgeUnit AltSkin factor multiplies the result and the runtime truncates again. AddCount floors accumulated score at zero after negative additions.

Combo behavior is now native:

```text
Perfect / Great -> increment
Good            -> preserve
Bad / Miss      -> clear
```

Per-bank combo state is retained internally because the score bonus uses the bank combo.

### HPBar / gauge

Native setup:

```text
Life    = 500
Limit   = 1000 + 3 * min(Level, 50)^2
DispMax = 1000
```

Header overrides are direct runtime writes after setup:

```text
80 -> Limit
81 -> DispMax
82 -> Life
```

Recovered factor presets:

```text
Single:     Min 200, Max 1000, MissFactor -700, initial 500
HalfDouble: Min   0, Max  800, MissFactor -700, initial 100
Double:     Min 100, Max  900, MissFactor -700, initial 300
```

JudgeUnit gauge changes:

```text
Perfect: delta = trunc(12 * factor / 1000); factor += 20
Great:   delta = trunc(10 * factor / 1000); factor += 16
Good:    delta = 0
Bad:     delta = -50
Miss:
    lifeBase = min(Life, 1000)
    delta = trunc((-500 * lifeBase) / 2000) - 20
    factor += MissFactor
```

Factor is clamped to its mode-specific Min/Max. Normal `HPBar.Add` clamps Life to `[0, Limit]`.

A Miss carrying NoMiss bypasses the normal PostProcess/gauge path, so it does not alter counters, score or life.

Current preview field-width bridge:

- 5 columns -> Single
- 6 columns -> HalfDouble
- 10 columns -> Double
- unusual widths retain the HalfDouble fallback rather than inventing a new HPBar type.

The separate challenge-game HPBar.Add branch is not modeled yet.

## Validation checkpoint

After integrating Items 4 and 5 and correcting legacy hold fixtures that used rush bytes:

```text
Ran 464 tests in 2.285s
OK
```

The full suite includes Qt offscreen tests, previous Smooth/Skip regressions, EffectiveModifier coverage, Speed/Gap/base-velocity tests, JudgeLine/JudgeNote/JudgeUnit tests, native timing boundaries, score formula tests and HPBar dynamics.

## Next audit item — visual modifiers

Proceed in this order unless new source evidence suggests stronger coupling:

1. Accel/Decel
2. Visibility
3. Snake/ZigZag
4. Earthworm
5. Random Velocity
6. remaining Throw/Freedom/Flash visual behavior

Known anchors already available:

- `LineBase.GetAccDecYOffset` RVA `0x638B20`
- `LineBase.RePos` RVA `0x638CA0`
- LineBase constructor defaults include `_accPow=1.5`, `_accScale=1`, `_yMin=200`, `_yMax=550`, `xAmplitude=20`, `waveRate=2`.

Keep these open side-paths source-gated:

- real producer of `CommonModifier.SpeedBoost`;
- challenge-mode HPBar.Add branch;
- forced-judgment Div 999 consumer;
- any Split-level modifier dispatcher if one is eventually recovered.
