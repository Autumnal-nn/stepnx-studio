# R!SE Runtime Parity Audit — Fresh-Chat Handoff

This file is the continuity anchor for continuing the StepNX Studio audit against Pump It Up R!SE without depending on prior chat state.

## Working branch

`audit/rise-runtime-parity`

The branch starts from the PUPA Skip-timing hotfix and keeps the broader runtime-parity work isolated from the release hotfix.

## Primary-source corpus

Primary specification:

- `GameAssembly.dll` — Pump It Up R!SE IL2CPP runtime
- `dump.cs` — IL2CPP type/field/enum metadata
- `script.json` — IL2CPP method/address map

When Studio behavior or an old test conflicts with the runtime, the runtime wins. Do not preserve a regression merely because a test encoded it first.

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

Native loader behavior recovered from `StepLoader.Load` RVA `0x751B80`:

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

`PUMPPlayer.DrawStep()` RVA `0x748B50` tests only `flags & 0x01` for Smooth. A Skip-only Div (`2`) does not interpolate.

Smooth now lives in `NativeTimingProjection.block_speed_at()` and uses the native interval:

```text
prevEnd = 0                    if current Block == 0
prevEnd = DivEndTime(block-1)  otherwise
curEnd  = DivEndTime(current)
ratio   = clamp((time-prevEnd)/(curEnd-prevEnd), 0, 1)

blockSpeed = previousLoadedDivSpeed
           + (currentLoadedDivSpeed - previousLoadedDivSpeed) * ratio
```

If `curEnd <= prevEnd`, ratio is 1. The first previous speed is 1.0. Negative serialized Div Speed has already been normalized positive by StepLoader.

The legacy `PreviewTimingSegment` speed transition was removed. `RuntimeEventStream.speed_factor_at()` delegates to the native projection. Tests explicitly cover raw flags 0/1/2/3 and previous-Div speed handoff.

## Completed Item 1 — ApplyStepParamToMod / EffectiveModifier

Primary binary anchor: `PlayBase.ApplyStepParamToMod` RVA `0x659F00`.

### Scope finding

The recovered R!SE path reads the loaded Step's global Header StepParam array at `Step + 0x28`.

Split metadata is stored separately (`Split + 0x18`), but no second `ApplyStepParamToMod` path applying Split metadata to `GameModifier` has been recovered. Therefore the preview:

- preserves both Header and Split StepParams in `PreviewSnapshot`;
- applies only Header StepParams to `EffectiveModifier`;
- does not invent Header -> Split modifier overrides from historical editor profile scopes.

Revisit this only if a direct runtime consumer of Split StepParams is recovered.

### Lookup behavior

`Step.GetParam` RVA `0x74CC30` scans serialized `(id,value)` pairs from the beginning and returns the first matching ID. Duplicates are therefore **first-wins**. Never convert runtime StepParams to a normal dict.

`Step.GetFloatParam` RVA `0x74CC90` preserves the four value bytes and reinterprets them as IEEE-754 `float`; it does not numerically cast the uint32 payload.

### Runtime types recovered from dump.cs

`GameModifier` contains:

```text
Skin[6]
Speed
_SpeedMod
_AccDec
_Visibility
bFreedom
bFlash
nRandomSkin
_Throw
bSnake
bZigZag
bMirrorTurn
bMirrorLR
bRandom
bRunner
bJudgeBank
PerfectFrame
Interval
bJudgeReverse
bHideJudge
bJudgeByNote
bComboPerBank
bFreePerformance
_JudgeLinePos
_DefaultJudgeLinePos
bGhostBuster
bTreasureHunter
bShowMeTheBank
AltSkinScoreFactor
AltSkinGaugeFactor
```

`CommonModifier` contains:

```text
bDisableBG
bExceed
bNX
bRotate180
bUpsideDown
bMergeCombo
GaugeLinkFactor
SpeedBoost
```

`GameModifier.Clear()` establishes at least:

```text
Speed        = 2.0
SpeedMode    = Static (0)
AccDec       = Linear (0)
Visibility   = Visible (0)
PerfectFrame = 2.5
Interval     = 2.5
```

### Exact PUMP.Param names relevant to this dispatcher

```text
0     mpSpeed
1     mpSpeedMod
2     mpAccDec
16    mpVisibility
17    mpFreedom
18    mpFlash
19    mpRandomSkin
20    mpForceBGA
21    mpExceed
22    mpNX
32    mpDirection
33    mpThrow
34    mpSnake
35    mpZigZag
48    mpMirrorTurn
49    mpMirrorLR
50    mpRandom
51    mpRunner
64    mpJudgeBank
65    mpDifficulty
66    mpJudgeReverse
67    mpHideJudge
68    mpJudgeByNote
69    mpComboDisplay
70    mpAltSkinScoreFactor / mpAltSkinGaugeFactor
71    mpFreePerformance
80    mpGaugeMax
81    mpGaugeDispMax
82    mpGaugeInitVal
83    mpGaugeBreak
84    mpMissComboBreak
85    mpGaugeLink
900   mpSkinBase (900..905 = six skin slots)
1000  mpGameType
1001  mpLevel
1002  mpPlayers
1003  mp2PStep
1100  mpmTitle
1101  mpmLevel
1102  mpmDescS
1103  mpmDescF
1110  mpmSpeedBoost
1111  mpmSpeedX
1150  mpmCondition
1199  mpmBreakCond
```

Important: declaration in `PUMP.Param` does not imply an effective Header write in this method.

### ApplyStepParamToMod projections now implemented

```text
1001 Level
0    Speed
1    SpeedMode: 0 Static, 1 Earthworm, 2 RandomVelocity
2    AccDec: 0 Linear, 1 Acceleration, 2 Deceleration
16   Visibility: 0 Visible, 1 Vanish, 2 Appear, 3 Hidden
17   Freedom
18   Flash
19   Random Skin selector
21   CommonModifier.bExceed
22   CommonModifier.bNX
32   Direction: 0 Normal, 1 180, 2 UpsideDown, 3 Mirror
33   Throw: 0 Flat, 1 Sink, 2 Rise
34   Snake
35   ZigZag
48   MirrorTurn
49   MirrorLR
50   Random
64   JudgeBank
65   PerfectFrame / Interval decimal decoder
66   JudgeReverse
67   HideJudge
68   JudgeByNote
69   ComboDisplay
70   AltSkinScoreFactor and AltSkinGaugeFactor
71   FreePerformance
80   Gauge Max
81   Gauge Display Max
82   Gauge Initial Value
83   Gauge Break / Stage Break
84   MissComboBreak
85   CommonModifier.GaugeLinkFactor
900..905 six GameModifier Skin slots
1111 SpeedX multiplier applied to already-effective Speed
```

### Corrections made after dump.cs became available

The first no-dump pass used several provisional names inferred only from stores. Those are now replaced with metadata-backed names:

- ID 32 is **Direction**, not Under Attack / Drop.
- ID 48 is `MirrorTurn`.
- ID 49 is `MirrorLR`.
- ID 50 is `Random`, not Runner.
- ID 64 is `JudgeBank`, not legacy Judge-by-Note.
- ID 66 is `JudgeReverse`.
- Visibility 3 is **Hidden**, not Vanish+Appear.
- ID 69 is `ComboDisplay`.
- ID 70 is both `AltSkinScoreFactor` and `AltSkinGaugeFactor`.
- ID 71 is `FreePerformance`.
- ID 85 is `GaugeLink`.

Do not change NXA/Fiesta profile metadata just because R!SE reuses the same numeric ID differently. Engine-profile authoring semantics and the R!SE runtime projection are separate layers.

### Detailed cases

#### Header Speed ID 0

Uses `GetFloatParam`. After decoding:

```text
if 0 < speed <= 255:
    speed *= 0.25
else:
    speed remains direct
```

`-1.0` is the no-value sentinel.

#### SpeedMode ID 1

The enum declares `AutoVelocity = 3`, but `ApplyStepParamToMod` only applies values 0, 1 and 2. Value 3 is handled elsewhere and is not treated as a Header dispatcher write.

#### Direction ID 32

```text
0 Normal      -> Rotate180=0, UpsideDown=0
1 180         -> Rotate180=1, UpsideDown=0
2 UpsideDown  -> Rotate180=0, UpsideDown=1
3 Mirror      -> Rotate180=1, UpsideDown=1
```

#### ComboDisplay ID 69

```text
0 SingleBank -> GameModifier.bComboPerBank=1, CommonModifier.bMergeCombo=0
1 AllBank    -> GameModifier.bComboPerBank=0, CommonModifier.bMergeCombo=0
2 AllPlayer  -> GameModifier.bComboPerBank=0, CommonModifier.bMergeCombo=1
```

#### Alt Skin Factor ID 70

The enum intentionally declares the same numeric ID twice. The dispatcher reads ID 70 twice and writes:

```text
AltSkinScoreFactor = decodedFloat - 1.0
AltSkinGaugeFactor = decodedFloat - 1.0
```

#### Skin IDs 900..905

After processing Random Skin ID 19, the dispatcher iterates all six slots:

```text
if Header 900+slot exists:
    Skin[slot] = value
else if nRandomSkin != 0:
    Skin[slot] = 254
else:
    keep current/default slot
```

#### IDs that exist but are not effective writes here

- `20 mpForceBGA`: `GetStrParam(...,20)` is called but the returned string is discarded by this method.
- `51 mpRunner`: enum member exists, but no ID-51 branch exists in `ApplyStepParamToMod`.
- `1110 mpmSpeedBoost`: `GetFloatParam(...,1110)` is called but the return value is discarded by this method.

Do not fabricate writes for those IDs in `EffectiveModifier`. `CommonModifier.SpeedBoost` does exist and is consumed elsewhere, including judgment timing, so its producer must be audited separately.

#### ID 1111 SpeedX

If present, decoded float directly multiplies the current `GameModifier.Speed`.

#### ID 65

The R!SE decimal decoder currently updates only `EffectiveModifier.perfect_frame` and `.interval_frame`. It does not yet alter `GameplaySession` judgment windows; that belongs to the native judgment-window item.

### Tests

After the dump-backed mapping correction and expanded coverage:

```text
Ran 437 tests in 2.249s
OK
```

Coverage includes Direction 0..3, Hidden visibility, ComboDisplay, skin slots and Random fallback 254, exact lane/judge flags, AutoVelocity value 3 not being applied by this dispatcher, ForceBGA/SpeedBoost discarded-lookups, gauge/link state, and all previous Smooth/Skip/Qt regressions.

## Existing Skip-aware timing anchors

Already ported and validated against PUPA:

- `Step.GetBlock` RVA `0x74BFA0`
- `Step.GetLine` RVA `0x74C4C0`
- `Step.SetCurrentTime` RVA `0x74C570`
- `Step.DivEndTime` RVA `0x74C890`
- `PlayBase.GetBlockBeat` RVA `0x656220`, private overload RVA `0x656300`

Keep these axes separate:

- judgment time
- Block/Line beat-space position
- visual speed multiplier

## Next item — Speed / Gap / `_baseVelocity`

Primary anchors already identified:

- `PUMPPlayer.SetSpeed` RVA `0x746330`
- `PUMPPlayer.SpeedProc` RVA `0x746360`
- `PUMPPlayer.DrawStep` RVA `0x748B50`
- `Step.currentGap` RVA `0x74C7B0`
- `LineBase.RePos` RVA `0x638CA0`
- `LineBase.CreateSplits` RVA `0x639720`

Current source findings to preserve:

- `SetSpeed()` stores `_modeSpeedExt = userSpeed` and `_modeSpeed = userSpeed * _blockSpeed`.
- `SpeedProc()` moves `pHighSpeed` toward `_modeSpeed`; the existing Studio direct multiplication is not frame-exact.
- `LineBase.RePos()` multiplies `PlayBase.GetBlockBeat(block,line)` by the LineBase `_baseVelocity` before transform placement.
- `CreateSplits()` stores judge time as `msStart + line*msPerLine`, stores `GetBlockBeat(block,line)`, sets start Y to 50, and derives `_baseVelocity` from a transform Y distance divided by a LineBase field at `+0x8C`.
- That `+0x8C` input appears serialized/prefab-provided rather than assigned inside `CreateSplits`; do not invent its value from Studio lane spacing. Recover the prefab/config source or explicitly keep a normalized Studio scale.
- `CommonModifier.SpeedBoost` is a real field and later affects timing consumers, but Header ID 1110 is not assigned to it by `ApplyStepParamToMod`; audit its actual producer separately.

## Planned order after Speed/Gap

1. `JudgeLine` / `JudgeNote` / `JudgeUnit` / long-note processing.
2. Native judgment windows.
3. Native scoring and gauge.
4. Accel/Decel, Visibility, Snake/ZigZag, Earthworm, Random Velocity and remaining visual modifiers.

## Other primary-source anchors

- `PUMPPlayer.SetJudgeTiming` RVA `0x746B00`
- `PUMPPlayer.JudgeLine` RVA `0x7474D0`
- `PUMPPlayer.JudgeUnit` RVA `0x747A60`
- `PUMPPlayer.JudgeStep_PostProcess` RVA `0x748000`
- `PUMPPlayer.GetScore` RVA `0x748A40`
- `LineBase.GetAccDecYOffset` RVA `0x638B20`
- `Gauge.SetJudgeGauge` RVA `0x518C90`
