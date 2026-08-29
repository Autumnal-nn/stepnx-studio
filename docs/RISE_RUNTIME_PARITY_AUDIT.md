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
| RT-003 | Preview Smooth trigger | FIXED | `PUMPPlayer.DrawStep()` RVA `0x748B50` tests only `flags & 0x01`. | `RuntimeEventStream.speed_factor_at()` now delegates to native Smooth projection. Skip-only `2` does not interpolate; `3` combines Smooth+Skip. |
| RT-004 | Skip timing | MATCH | `StepLoader`: Skip sets `msPerLine = 0`; rows remain spatially present and judgeable. | Native Block/Line projection validated against PUPA. |
| RT-005 | Normal Div inside Skip route | MATCH | `PlayBase.Update` / `GetBlockBeat` use continuous float32 projection. | Corrected Player.Beat sign and float32 boundary arithmetic. |
| RT-006 | Loader Gap conversion | DIVERGENCE / visual consumer open | `Gap = rawGap / (BeatSplit * msPerLine)` only when `msPerLine > 0` and raw Speed > 0; otherwise 0. Negative raw Speed is normalized positive afterward. | Judgment timing is native; legacy non-Skip visual segment still models negative Speed as local motion delay and must be removed in Speed/Gap work. |
| RT-007 | Smooth interpolation curve | FIXED | Previous loaded Div Speed -> current loaded Div Speed over `previous DivEndTime -> current DivEndTime`, ratio clamped 0..1. | Implemented in `NativeTimingProjection.block_speed_at()`. Old next-Block-StartTime approximation removed. |
| RT-008 | Block speed initialization | MATCH | `ClearForNewStage()` initializes block/previous/target speed to 1.0. | Native projection uses 1.0 before first Div. |
| RT-009 | User speed vs block speed | APPROXIMATION | `SetSpeed()` stores `_modeSpeedExt = userSpeed` and `_modeSpeed = userSpeed * _blockSpeed`; `SpeedProc()` eases `pHighSpeed` toward `_modeSpeed`. | Studio still directly multiplies COMMAND speed by block speed. Exact speed-change processing belongs to the next item. |

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
| RM-002 | Duplicate StepParam lookup | MATCH | `Step.GetParam` RVA `0x74CC30` scans `(id,value)` pairs from the beginning and returns the first matching ID. | `StepParam` stays ordered; runtime projection is first-wins rather than dict/last-wins. |
| RM-003 | Float StepParam decoding | MATCH | `Step.GetFloatParam` RVA `0x74CC90` reconstructs the four raw value bytes as IEEE-754 float. | `StepParam.float_value` uses bit reinterpretation, not numeric uint32-to-float conversion. |
| RM-004 | Game/Common modifier defaults | MATCH | `GameModifier.Clear()` and `CommonModifier.Clear()` initialize runtime modifier state. `GameModifier` defaults include Speed=2, Static, Linear, Visible, PerfectFrame=2.5, Interval=2.5. | `EffectiveModifier` starts from recovered defaults and exposes both GameModifier and CommonModifier state. |
| RM-005 | Header Speed ID 0 | MATCH state projection | `mpSpeed`; decoded float in `(0,255]` is multiplied by 0.25, otherwise direct. | Projected to `EffectiveModifier.speed`; visual integration remains RT-009. |
| RM-006 | SpeedMode ID 1 | MATCH state projection | Enum includes AutoVelocity=3, but this dispatcher applies only 0 Static, 1 Earthworm, 2 RandomVelocity. | Value 3 is deliberately ignored here instead of fabricating a Header AutoVelocity write. |
| RM-007 | AccDec / Visibility | MATCH state projection | IDs 2 and 16 map to `GameModifier._AccDec` and `_Visibility`; Visibility value 3 is `Hidden`. | Explicit enums now match dump metadata. |
| RM-008 | Direction ID 32 | FIXED after dump metadata | `mpDirection`: 0 Normal, 1 180, 2 UpsideDown, 3 Mirror; writes `CommonModifier.bRotate180` / `bUpsideDown`. | Replaced the earlier provisional Under Attack/Drop interpretation. |
| RM-009 | Lane transform IDs 48..51 | FIXED after dump metadata | 48 `mpMirrorTurn` -> `bMirrorTurn`; 49 `mpMirrorLR` -> `bMirrorLR`; 50 `mpRandom` -> `bRandom`; enum declares 51 `mpRunner`, but this dispatcher has no ID-51 branch. | Correct names implemented; Runner remains unchanged by Header projection here. |
| RM-010 | Judge flags 64,66,67,68 | FIXED after dump metadata | 64 JudgeBank, 66 JudgeReverse, 67 HideJudge, 68 JudgeByNote. | Replaced provisional legacy labels with exact `GameModifier` fields. |
| RM-011 | Difficulty ID 65 | MATCH state projection | Native decimal decoder writes `PerfectFrame` and `Interval`. | Projected to `EffectiveModifier`; GameplaySession windows remain separate work. |
| RM-012 | ComboDisplay ID 69 | MATCH | Enum values: 0 SingleBank, 1 AllBank, 2 AllPlayer. Dispatcher jointly writes `GameModifier.bComboPerBank` and `CommonModifier.bMergeCombo`. | `ComboDisplay` enum and both effective booleans are projected. |
| RM-013 | Alt-skin factor ID 70 | MATCH | `PUMP.Param` aliases both `mpAltSkinScoreFactor` and `mpAltSkinGaugeFactor` to 70. Dispatcher reads the same float twice and writes `value - 1` to both fields. | Both named fields projected exactly. |
| RM-014 | Free Performance ID 71 | MATCH | `mpFreePerformance` -> `GameModifier.bFreePerformance`. | Projected exactly. |
| RM-015 | Gauge / break IDs 80..85 | MATCH state projection | 80 Max, 81 Display Max, 82 Init, 83 Break, 84 MissComboBreak, 85 GaugeLink -> `CommonModifier.GaugeLinkFactor`. | Named effective state preserved for later gauge integration. |
| RM-016 | Random skin / skin slots | MATCH | ID 19 sets `nRandomSkin`; 900..905 are six skin slots. Missing slot with Random Skin active falls back to 254. | `EffectiveModifier.skins` models all six slots and the native 254 fallback. |
| RM-017 | ForceBGA ID 20 | MATCH no-write finding | Enum names `mpForceBGA`; this dispatcher calls `GetStrParam(...,20)` but discards the result. | No fabricated `disable_bg` write from Header ID 20 here. Producer/consumer can be audited elsewhere. |
| RM-018 | Runner ID 51 | MATCH no-branch finding | `mpRunner=51` exists in `PUMP.Param`, but `ApplyStepParamToMod` contains no ID-51 branch. | `runner` is retained in effective state but not changed by Header ID 51 in this dispatcher. |
| RM-019 | SpeedBoost ID 1110 | MATCH no-write finding | `mpmSpeedBoost=1110`; dispatcher calls `GetFloatParam(...,1110)` and discards the result. `CommonModifier.SpeedBoost` is a real field read elsewhere. | No Header write invented. Actual producer remains a separate audit target. |
| RM-020 | SpeedX ID 1111 | MATCH | `mpmSpeedX` decoded float multiplies already-effective `GameModifier.Speed`. | Implemented after ID 0 processing. |
| RM-021 | Level ID 1001 | MATCH state projection | `mpLevel` is consumed by this routine for stage/gauge setup. | Raw effective level retained for downstream runtime parity work. |
| RM-022 | Engine profile vs R!SE runtime semantics | MATCH separation | Numeric Param IDs are reused across engine generations. R!SE enum names do not retroactively redefine native NXA/Fiesta metadata. | Profile registries remain engine-specific; R!SE runtime projection is a separate layer. |

## Visual placement / modifiers

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RV-001 | Base note Y projection | MATCH for beat-space core | `LineBase.RePos()` calls `PlayBase.GetBlockBeat(block,line)` and multiplies by `_baseVelocity`. | Skip-aware beat-space projection is native; pixel scale remains approximate. |
| RV-002 | `_baseVelocity` | OPEN, construction path recovered | `LineBase.CreateSplits()` stores judge time, GetBlockBeat, start Y=50, and derives `_baseVelocity` from transform Y distance divided by field `+0x8C`. | `+0x8C` appears serialized/prefab-provided. Do not fabricate its value from lane spacing. |
| RV-003 | Accel / Decel | APPROXIMATION | `LineBase.GetAccDecYOffset()` uses normalized visible Y, `_accPow`, `_accScale`, and a `-200` scale. | Studio still uses synthetic power curves. Exact prefab constants still needed. |
| RV-004 | Earthworm / Snake | APPROXIMATION | Runtime has SpeedMode state, `_snakeBase`, and animation paths. | Studio synthetic sine remains until visual-modifier item. |
| RV-005 | Random Velocity | APPROXIMATION | Runtime exposes SpeedMode RandomVelocity. | Studio deterministic `uniform(0.65,1.35)` is not claimed native. |
| RV-006 | Visibility modifier | OPEN | `GameModifier.Visibility`: Visible=0, Vanish=1, Appear=2, Hidden=3; separate from per-note Effects. | Current opacity curve remains custom pending native visual path. |
| RV-007 | Throw mode | OPEN | Flat=0, Sink=1, Rise=2; LineBase has throw animation state. | State is projected, transform remains unaudited. |

## Judgment / note semantics

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RJ-001 | Raw note attribute bits | PARTIAL | `0x20 NoJudge`, `0x40 JudgeMiss`, `0x60 NoMiss`, `0x10 bNoRush`; `JudgeLine()` skips exact NoJudge. | Current Ghost/Bonus labels are historical UI terminology; runtime effects need JudgeUnit/JudgeNote pass. |
| RJ-002 | Note types | MATCH | TypeMask low two bits: Item=1, Special=2, Normal=3. | Decode matches. |
| RJ-003 | Long flags | MATCH decode / runtime open | LongStart=0x04, LongMiddle=0x08, LongEnd=0x0C, bLong includes NoRush. | Glyph decode compatible; hold judgment behavior still open. |
| RJ-004 | Per-note visibility bits | MATCH decode | Hidden=0, Appear=1, Disappear=2, Visible=3; ZigZag bit separate. | Decode matches; fade/transform remains visual work. |
| RJ-005 | Judgment timing model | APPROXIMATION | `SetJudgeTiming` uses 16.666666 ms frame base, PerfectFrame, Interval, Delay, and asymmetric Start/End. | Studio still has fixed symmetric windows. |
| RJ-006 | Judge difficulty | DIVERGENCE | Runtime changes PerfectFrame/Interval. | Not yet consumed by GameplaySession. |
| RJ-007 | Base score table | DIVERGENCE | Perfect=1000, Great=500, Good=100, Bad=-200, Miss=-500; long Miss=-300. | Studio simplified score table differs. |
| RJ-008 | Native score bonuses | NOT MODELED | Perfect/Great combo and chord multipliers recovered in `GetScore`. | Current combo*10 model is not native. |
| RJ-009 | Forced judgment / Div 999 | OPEN | Known historical values 1..4 map to forced grades. | Preview integration still open. |

## Gauge / life

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RG-001 | Gauge defaults | DIVERGENCE | Perfect=12, Great=10, Good=0, Bad=-50, Miss=-500; GaugeDefault=500, LimitDefault=1000, DispMaxDefault=1000. | Studio simplified gauge differs. |
| RG-002 | Gauge dynamics | NOT MODELED | `Gauge.SetJudgeGauge()` applies dynamic factor, scaling and clamps. | Static delta table cannot reproduce it. |
| RG-003 | Gauge metadata | STATE MATCH / consumer open | Header IDs 80..85 feed gauge/stage-break/link state. | `EffectiveModifier` now preserves recovered named state; GameplaySession integration remains later. |
| RG-004 | SpeedBoost producer | OPEN | `CommonModifier.SpeedBoost` is consumed by later timing paths, but `ApplyStepParamToMod` does not assign Header 1110 to it. | Trace actual assignment source before integrating it into judgment timing. |

## Editor / authoring

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RE-001 | Encoded-row grid | MATCH by design | Native Div retains nLine/BeatPerLine even for Skip. | All encoded rows remain editable. |
| RE-002 | Block Speed sign | PARTIAL MATCH | Loader uses raw sign for Gap conversion, then normalizes Speed positive. | Authoring preserves raw sign; runtime visual path still needs final migration. |
| RE-003 | Scroll Factor / BeatPerLine | MATCH storage | Native BeatPerLine is raw spatial-per-line float. | Raw Scroll preserved; Real Scroll is editor convenience. |
| RE-004 | Div flag editing | FIXED | Native byte is a flags field with named bits 0/1. | Smooth/Skip independent, upper bits preserved. |
| RE-005 | Cross-generation ID reuse | MATCH separation | Same numeric metadata ID can mean different things in NXA, Fiesta-era engines and R!SE. | Do not rewrite engine-specific authoring profiles from the R!SE Param enum. Runtime projection and authoring registry remain distinct. |

## Source anchors

- `CommonModifier.Clear` RVA `0x5177C0`
- `GameModifier.Clear` RVA `0x517870`
- `GameModifier.SetJudgeDifficulty` RVA `0x517900`
- `Gauge.SetJudgeGauge` RVA `0x518C90`
- `PlayBase.ApplyStepParamToMod` RVA `0x659F00`
- `StepLoader.Load` RVA `0x751B80`
- `Step.GetBlock` RVA `0x74BFA0`
- `Step.GetLine` RVA `0x74C4C0`
- `Step.SetCurrentTime` RVA `0x74C570`
- `Step.currentGap` RVA `0x74C7B0`
- `Step.DivEndTime` RVA `0x74C890`
- `Step.GetParam` RVA `0x74CC30`
- `Step.GetFloatParam` RVA `0x74CC90`
- `Step.GetStrParam` RVA `0x74CEA0`
- `Step.SetJudgeTiming` RVA `0x74BB50`
- `Step.Judge` RVA `0x74D100`
- `PUMPPlayer.SetDefaultHighSpeed` RVA `0x7451B0`
- `PUMPPlayer.SetSpeed` RVA `0x746330`
- `PUMPPlayer.SpeedProc` RVA `0x746360`
- `PUMPPlayer.SetJudgeTiming` RVA `0x746B00`
- `PUMPPlayer.JudgeLine` RVA `0x7474D0`
- `PUMPPlayer.JudgeUnit` RVA `0x747A60`
- `PUMPPlayer.GetScore` RVA `0x748A40`
- `PUMPPlayer.DrawStep` RVA `0x748B50`
- `PlayBase.GetBlockBeat` RVA `0x656220` / private overload `0x656300`
- `LineBase.GetAccDecYOffset` RVA `0x638B20`
- `LineBase.RePos` RVA `0x638CA0`
- `LineBase.CreateSplits` RVA `0x639720`

## Current test checkpoint

After completing the dump-backed StepParam ID pass:

```text
Ran 437 tests in 2.249s
OK
```

## Next audit order

1. Speed / Gap / `_baseVelocity`.
2. `JudgeLine` / `JudgeNote` / `JudgeUnit` / long-note processing.
3. Native judgment windows.
4. Native scoring and gauge.
5. Accel/Decel, Visibility, Snake/ZigZag, Earthworm, Random Velocity and remaining visual modifiers.
