# R!SE Runtime Parity Audit

This document tracks source-primary comparisons between StepNX Studio and the Pump It Up R!SE IL2CPP runtime. `GameAssembly.dll` is the primary executable specification; `dump.cs` and `script.json` provide the type, enum and method metadata needed to name recovered state safely.

Audit states:

- **MATCH**: Studio behavior is supported by the native runtime.
- **FIXED**: a previously identified divergence has been corrected on the audit branch.
- **DIVERGENCE**: Studio behavior conflicts with the native runtime.
- **APPROXIMATION**: Studio intentionally provides a simplified simulation.
- **OPEN**: native behavior still needs to be recovered before changing Studio.

The NX20 codec remains lossless unless a finding explicitly says otherwise.

## Timing / Div semantics

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RT-001 | Div flag byte | MATCH | `DivFlags`: `bSmooth = 0x01`, `bSkip = 0x02`. | `native_timing.py` uses independent bits. Raw byte remains lossless. |
| RT-002 | Timing dialog flag UI | FIXED | Same bit layout. | Smooth/Skip are independent toggles; unknown upper bits are preserved. |
| RT-003 | Preview Smooth trigger | FIXED | `PUMPPlayer.DrawStep()` RVA `0x748B50` tests only `flags & 0x01`. | `RuntimeEventStream.speed_factor_at()` delegates to native Smooth projection. Skip-only `2` does not interpolate; `3` combines Smooth+Skip. |
| RT-004 | Skip timing | MATCH | `StepLoader`: Skip sets `msPerLine = 0`; rows remain spatially present and judgeable. | Native Block/Line projection validated against PUPA. |
| RT-005 | Normal Div inside Skip route | MATCH | `PlayBase.Update` / `GetBlockBeat` use continuous float32 projection. | Corrected Player.Beat sign and float32 boundary arithmetic. |
| RT-006 | Loader Gap conversion | FIXED | `Gap = rawGap / (BeatSplit * msPerLine)` only when `msPerLine > 0` and raw Speed > 0; otherwise 0. Negative raw Speed is normalized positive afterward. | Native Gap/currentGap is projected explicitly; negative Speed no longer creates a fake local visual freeze. |
| RT-007 | Smooth interpolation curve | FIXED | Previous loaded Div Speed -> current loaded Div Speed over `previous DivEndTime -> current DivEndTime`, ratio clamped 0..1. | Implemented in `NativeTimingProjection.block_speed_at()`. |
| RT-008 | Block speed initialization | MATCH | `ClearForNewStage()` initializes block/previous/target speed to 1.0. | Native projection uses 1.0 before first Div. |
| RT-009 | User speed vs block speed | FIXED | `SetSpeed()` stores `_modeSpeedExt = userSpeed` and `_modeSpeed = userSpeed * _blockSpeed`; `SpeedProc()` moves `pHighSpeed` by 0.05 at the 1/60 s cadence. | `RuntimeSpeedState` separates selected speed, block speed, target mode speed and displayed high speed. |
| RT-010 | `_baseVelocity` | FIXED | `LineBase` initializes start Y=50 and `_startGapTime=8.5`; `ArrowMaker` places the target at Y=608. | Native base velocity is `(608-50)/8.5 = 65.6470588`, normalized to the 72-unit note render scale. |

Native loader normalization:

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

`Step.currentGap()` later returns `Gap * msPerLine / BeatPerLine`.

## Runtime StepParam / modifier state

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RM-001 | ApplyStepParamToMod scope | MATCH | `PlayBase.ApplyStepParamToMod` RVA `0x659F00` reads the loaded Step global Header StepParam array at `Step+0x28`. No recovered path applies `Split+0x18` through the same dispatcher. | Snapshot preserves Header and Split StepParams, but `EffectiveModifier` applies Header only. |
| RM-002 | Duplicate StepParam lookup | MATCH | `Step.GetParam` RVA `0x74CC30` scans `(id,value)` pairs from the beginning and returns the first matching ID. | Runtime projection is first-wins. |
| RM-003 | Float StepParam decoding | MATCH | `Step.GetFloatParam` RVA `0x74CC90` reinterprets the raw four value bytes as IEEE-754 float. | `StepParam.float_value` uses bit reinterpretation. |
| RM-004 | Game/Common modifier defaults | MATCH | `GameModifier.Clear()` and `CommonModifier.Clear()` establish runtime defaults including Speed=2, Static, Linear, Visible, PerfectFrame=2.5, Interval=2.5. | `EffectiveModifier` starts from recovered defaults. |
| RM-005 | Header Speed ID 0 | MATCH | Decoded float in `(0,255]` is multiplied by 0.25, otherwise direct. | Projected and consumed by runtime speed state. |
| RM-006 | SpeedMode ID 1 | MATCH | Dispatcher applies 0 Static, 1 Earthworm, 2 RandomVelocity. Enum value 3 AutoVelocity is not assigned here. | Value 3 is deliberately not fabricated as a Header write. |
| RM-007 | AccDec / Visibility | MATCH state projection | IDs 2 and 16 map to `_AccDec` and `_Visibility`; Visibility 3 is Hidden. | Explicit enums match dump metadata. |
| RM-008 | Direction ID 32 | FIXED after dump metadata | 0 Normal, 1 180, 2 UpsideDown, 3 Mirror. | Correct `bRotate180` / `bUpsideDown` projection. |
| RM-009 | Lane transform IDs 48..51 | FIXED after dump metadata | 48 MirrorTurn, 49 MirrorLR, 50 Random; ID 51 Runner is declared but has no branch in this dispatcher. | Exact names implemented; no fake Header Runner write. |
| RM-010 | Judge flags 64,66,67,68 | FIXED after dump metadata | 64 JudgeBank, 66 JudgeReverse, 67 HideJudge, 68 JudgeByNote. | Exact runtime fields projected. |
| RM-011 | Difficulty ID 65 | MATCH | Decimal decoder writes PerfectFrame and Interval. | `NativeJudgeTiming` now consumes both values. |
| RM-012 | ComboDisplay ID 69 | MATCH | 0 SingleBank, 1 AllBank, 2 AllPlayer; writes `bComboPerBank` and `bMergeCombo`. | Projected exactly. |
| RM-013 | Alt-skin factor ID 70 | MATCH | Same numeric ID feeds both score and gauge factor fields; dispatcher writes `decodedFloat - 1`. | Both fields projected. JudgeUnit score multiplier consumes the score factor. |
| RM-014 | Free Performance ID 71 | MATCH | `mpFreePerformance` -> `bFreePerformance`. | Projected exactly. |
| RM-015 | Gauge / break IDs 80..85 | MATCH | 80 Limit, 81 Display Max, 82 Initial Life, 83 Break, 84 MissComboBreak, 85 GaugeLink. | 80/81/82 are now consumed directly by RuntimeGauge; 83..85 remain named runtime state. |
| RM-016 | Random skin / skin slots | MATCH | ID 19 plus slots 900..905; missing random slots use 254. | Six-slot projection and fallback implemented. |
| RM-017 | ForceBGA ID 20 | MATCH no-write finding | `GetStrParam(...,20)` is called but discarded by this method. | No fabricated write. |
| RM-018 | Runner ID 51 | MATCH no-branch finding | Enum exists, dispatcher branch does not. | No fabricated write. |
| RM-019 | SpeedBoost ID 1110 | MATCH no-write finding | Header getter result is discarded, although `CommonModifier.SpeedBoost` is a real field consumed elsewhere. | Header 1110 does not assign it. Native judgment timing will scale if a future validated producer populates the field. |
| RM-020 | SpeedX ID 1111 | MATCH | Decoded float multiplies already-effective Speed. | Implemented. |
| RM-021 | Level ID 1001 | MATCH | Level participates in gauge setup. | RuntimeGauge uses the native level-derived limit. |
| RM-022 | Engine profile vs R!SE runtime semantics | MATCH separation | Numeric IDs are reused across engine generations. | R!SE runtime projection remains separate from NXA/Fiesta authoring registries. |

## Judgment / note semantics

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RJ-001 | Raw note attribute bits | MATCH for recovered judge path | `0x20 NoJudge`, `0x40 JudgeMiss`, `0x60 NoMiss`, `0x10 bNoRush`; `JudgeLine()` skips exact NoJudge. | Preview events expose the native attribute/effect/bank/param fields. |
| RJ-002 | Note types | MATCH | TypeMask low two bits: Item=1, Special=2, Normal=3. | Runtime judge filter uses Type Normal. |
| RJ-003 | Long routing | FIXED | Long components without `bNoRush` leave aggregate JudgeLine and use the rush/roll JudgeNote path; `bNoRush` longs remain aggregate. | 47/4B/4F are treated as rush; 57/5B/5F as regular aggregate long components. |
| RJ-004 | Bank grouping | FIXED | JudgeLine resolves one bank at a time. | Session groups by encoded line + bank; JudgeByNote adds lane to the unit key. |
| RJ-005 | JudgeByNote | MATCH | `GameModifier.bJudgeByNote` routes eligible cells through JudgeNote/JudgeUnit individually. | Per-note units implemented. |
| RJ-006 | JudgeUnit projection | MATCH | Negative grade maps to Miss; NoMiss can bypass PostProcess; AltSkin factor is `1 + altCount/totalCount * AltSkinScoreFactor`; return is `grade <= Great`. | Structural projection implemented before explicit PostProcess consumers. |
| RJ-007 | Judgment timing model | FIXED | `PUMPPlayer.SetJudgeTiming` uses a 16.66666603088379 ms frame, PerfectFrame, Interval and 2.5-frame Delay. `Step.SetJudgeTiming` stores `Start=-(P+3I+D)`, `End=P+3I`; `Step.Judge` applies Delay on the late side before `GetGrade`. | Fixed symmetric windows replaced by `NativeJudgeTiming`. |
| RJ-008 | Judge difficulty | FIXED | Header 65 changes PerfectFrame and Interval. | GameplaySession now derives timing from the effective modifier. |
| RJ-009 | Base score table | FIXED | `PUMPPlayer.GetScore` table is Perfect=1000, Great=1000, Good=500, Bad=100, Miss=-200; ordinary-note Miss uses -300 in the PostProcess call path. | Native table implemented. |
| RJ-010 | Score combo bonus | FIXED | Perfect/Great receive +1000 when the per-bank combo after increment is at least 51. | Per-bank combo state feeds scoring. |
| RJ-011 | Chord score multiplier | FIXED | Total JudgeUnit count 3 multiplies by 1.5; 4+ multiplies by 2; result is truncated. | Implemented before AltSkin multiplication. |
| RJ-012 | AltSkin score multiplier | FIXED | JudgeUnit-derived factor multiplies GetScore result, then truncates. | Implemented. |
| RJ-013 | Negative score clamp | FIXED | AddCount does not let accumulated score fall below zero. | Implemented. |
| RJ-014 | Combo grade behavior | FIXED | Perfect/Great increment, Good preserves, Bad/Miss clear. | Old Good-break behavior removed. |
| RJ-015 | Forced judgment / Div 999 | OPEN | Historical values 1..4 are known, but the exact R!SE consumer has not been integrated in this pass. | Leave for a source-specific follow-up. |

## Gauge / life

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RG-001 | HPBar defaults | FIXED | Life=500, Limit=1000, DispMax=1000. | `RuntimeGauge` starts from these native defaults. |
| RG-002 | Level-derived Limit | FIXED | `Limit = 1000 + 3 * min(level,50)^2` before Header gauge overrides. | Implemented literally. |
| RG-003 | Play-type factor presets | FIXED for known NX field widths | Single: Min200/Max1000/Miss-700/Initial500; HalfDouble: 0/800/-700/100; Double: 100/900/-700/300. | 5 columns -> Single, 6 -> HalfDouble, 10 -> Double. Unusual widths retain the native invalid/fallback-style HalfDouble bridge. |
| RG-004 | Header 80/81/82 consumers | FIXED | ApplyStepParamToMod directly writes HPBar Limit, DispMax and Life after ResetHP/level setup. | RuntimeGauge applies the Header overrides directly. |
| RG-005 | Perfect/Great gauge | FIXED | Perfect delta=`trunc(12*factor/1000)`, factor +=20; Great=`trunc(10*factor/1000)`, factor +=16. | Implemented with factor clamp. |
| RG-006 | Good/Bad gauge | FIXED | Good=0; Bad=-50. | Implemented. |
| RG-007 | Miss gauge | FIXED | `lifeBase=min(Life,1000)`; delta=`trunc((-500*lifeBase)/2000)-20`; factor += MissFactor (-700), then clamp. | Implemented. |
| RG-008 | Life clamp | FIXED | Normal HPBar.Add clamps Life to `[0,Limit]`. | Implemented. |
| RG-009 | NoMiss | FIXED | A Miss with NoMiss bypasses the normal gauge/PostProcess path. | Expired protected notes do not change counters, score or life. |
| RG-010 | Challenge-mode HPBar.Add branch | OPEN | Native HPBar has a separate challenge-game path. | Current RuntimeGauge models the normal gameplay branch only. |
| RG-011 | SpeedBoost producer | OPEN | SpeedBoost is consumed by timing, but Header 1110 does not assign it. | Trace the real producer before connecting authored Header 1110. |

## Visual placement / remaining modifiers

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RV-001 | Base note Y projection | MATCH | `LineBase.RePos()` uses `PlayBase.GetBlockBeat(block,line) * _baseVelocity`. | Renderer uses native beat distance and recovered base velocity. |
| RV-002 | Accel / Decel | APPROXIMATION | `LineBase.GetAccDecYOffset()` uses normalized visible Y, `_accPow=1.5`, `_accScale=1`, and native field geometry. | Synthetic curves remain; this is the next visual-modifier item. |
| RV-003 | Earthworm / Snake | APPROXIMATION | Runtime has dedicated speed/animation state. | Synthetic sine remains pending visual-modifier pass. |
| RV-004 | Random Velocity | APPROXIMATION | Runtime exposes SpeedMode RandomVelocity. | Studio deterministic random range is not claimed native. |
| RV-005 | Visibility modifier | OPEN | Visibility enum and note effects are distinct runtime paths. | Current opacity curve remains custom pending native visual path. |
| RV-006 | Throw mode | OPEN | Flat/Sink/Rise and LineBase throw state are recovered. | Transform behavior remains unaudited. |

## Editor / authoring

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RE-001 | Encoded-row grid | MATCH by design | Native Div retains nLine/BeatPerLine even for Skip. | All encoded rows remain editable. |
| RE-002 | Block Speed sign | MATCH storage/runtime separation | Loader uses raw sign for Gap conversion and then normalizes Speed positive. | Authoring preserves raw bytes; runtime projection applies loader semantics. |
| RE-003 | Scroll Factor / BeatPerLine | MATCH storage | Native BeatPerLine is the raw spatial-per-line float. | Raw Scroll preserved; Real Scroll remains an editor convenience. |
| RE-004 | Div flag editing | FIXED | Native byte is a flags field. | Smooth/Skip independent; upper bits preserved. |
| RE-005 | Cross-generation ID reuse | MATCH separation | Same metadata number can mean different things across NXA, Fiesta-era engines and R!SE. | Runtime projection does not rewrite historical authoring profiles. |

## Source anchors

- `CommonModifier.Clear` RVA `0x5177C0`
- `GameModifier.Clear` RVA `0x517870`
- `GameModifier.SetJudgeDifficulty` RVA `0x517900`
- `PlayBase.GetBlockBeat` RVA `0x656220` / private overload `0x656300`
- `PlayBase.ApplyStepParamToMod` RVA `0x659F00`
- `LineBase.GetAccDecYOffset` RVA `0x638B20`
- `LineBase.RePos` RVA `0x638CA0`
- `LineBase.CreateSplits` RVA `0x639720`
- `PUMPPlayer.SetDefaultHighSpeed` RVA `0x7451B0`
- `PUMPPlayer.SetSpeed` RVA `0x746330`
- `PUMPPlayer.SpeedProc` RVA `0x746360`
- `PUMPPlayer.SetJudgeTiming` RVA `0x746B00`
- `PUMPPlayer.JudgeNote` RVA `0x747320`
- `PUMPPlayer.JudgeLine` RVA `0x7474D0`
- `PUMPPlayer.JudgeUnit` RVA `0x747A60`
- `PUMPPlayer.JudgeStep_PostProcess` RVA `0x748000`
- `PUMPPlayer.GetScore` RVA `0x748A40`
- `PUMPPlayer.DrawStep` RVA `0x748B50`
- `Step.SetJudgeTiming` RVA `0x74BB50`
- `Step.GetBlock` RVA `0x74BFA0`
- `Step.GetLine` RVA `0x74C4C0`
- `Step.SetCurrentTime` RVA `0x74C570`
- `Step.currentGap` RVA `0x74C7B0`
- `Step.DivEndTime` RVA `0x74C890`
- `Step.GetParam` RVA `0x74CC30`
- `Step.GetFloatParam` RVA `0x74CC90`
- `Step.GetStrParam` RVA `0x74CEA0`
- `Step.Judge` RVA `0x74D100`
- `Step.GetGrade` RVA `0x7508E0`
- `StepLoader.Load` RVA `0x751B80`

## Current test checkpoint

Items 0 through 5 are covered by the full repository suite. The first green Item 4+5 integration checkpoint ran:

```text
Ran 464 tests in 2.285s
OK
```

## Next audit order

1. Accel/Decel.
2. Visibility.
3. Snake/ZigZag.
4. Earthworm.
5. Random Velocity and remaining visual modifiers.

Open side-paths such as the real `SpeedBoost` producer, challenge-mode HPBar and forced-judgment Div 999 should remain source-gated and must not be guessed into the main preview path.
