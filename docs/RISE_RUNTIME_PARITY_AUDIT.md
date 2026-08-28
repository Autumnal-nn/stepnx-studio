# R!SE Runtime Parity Audit

This document tracks source-primary comparisons between StepNX Studio and the Pump It Up R!SE IL2CPP runtime (`GameAssembly.dll` + `dump.cs`).

The audit deliberately separates four states:

- **MATCH**: Studio behavior is supported by the native runtime.
- **DIVERGENCE**: Studio behavior conflicts with the native runtime.
- **APPROXIMATION**: Studio intentionally provides a simplified simulation; native parity has not yet been implemented.
- **OPEN**: native behavior still needs to be recovered before changing Studio.

The NX20 codec remains lossless unless a finding explicitly says otherwise. Most findings here concern runtime/editor semantics rather than serialization.

## Timing / Div semantics

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RT-001 | Div flag byte | MATCH after PR #10 core timing work | `DivFlags`: `bSmooth = 0x01`, `bSkip = 0x02`. | `native_timing.py` uses independent bits. Raw byte remains lossless. |
| RT-002 | Timing dialog flag UI | **FIXED on audit branch** | Same `DivFlags` enum. | Replaced the destructive "nonzero = Smooth" checkbox with independent Smooth/Skip bit toggles. The raw `Div Flags byte` remains editable and unknown upper bits are preserved. |
| RT-003 | Preview Smooth trigger | **DIVERGENCE, migration pending** | `PUMPPlayer.DrawStep()` tests `bmFlags & 0x01` specifically. | `events.py` still uses `block.smooth_speed != 0`. The obsolete regression test also encodes `2 = Smooth`. Migrate trigger + interpolation + tests together rather than leaving a half-converted branch. |
| RT-004 | Skip timing | MATCH after PR #10 | `StepLoader`: Skip sets `msPerLine = 0`; `DivEndTime = msStart + nLine*msPerLine`; `GetBlock` advances on `end <= currentTime`; rows remain present/judgeable. | Native Block/Line projection added and validated against PUPA. |
| RT-005 | Normal Div inside a Skip route | MATCH after PR #10 | `PlayBase.Update`/`GetBlockBeat` continuous float32 projection. | Corrected `Player.Beat` sign and float32 boundary arithmetic. Validated against PUPA Smooth=0 islands inside Skip snapshots. |
| RT-006 | Loader Gap conversion | **DIVERGENCE / visual consumer open** | `StepLoader.Load`: `Gap = rawGap / (BeatSplit * msPerLine)` only when `msPerLine > 0` and **raw Speed > 0**. Otherwise runtime `Gap = 0`. Negative raw Speed is then multiplied by -1 and stored as a positive runtime Speed. | Legacy preview still models negative Speed as `motion_start = StartTime + raw Delay`. Judgment timing does not do this natively. The authoring sign may still be a useful historical representation, but the renderer must not treat it as a persistent negative runtime speed. |
| RT-007 | Smooth speed interpolation curve | **DIVERGENCE, exact formula recovered** | `PUMPPlayer.DrawStep`: current Div must have `bSmooth`; previous runtime speed is the immediately preceding Div Speed (initially 1.0 after stage clear); target is current Div Speed. Ratio is `(msCurTime - prevDivEnd)/(currentDivEnd - prevDivEnd)`, clamped 0..1; if `currentDivEnd <= prevDivEnd`, ratio=1. `_blockSpeed = prev + (target-prev)*ratio`. | Current `PreviewTimingSegment` instead interpolates from its local motion start toward the **next Block StartTime** and also triggers on `0x02`. Replace both at once. |
| RT-008 | Block speed initialization | MATCH evidence available | `ClearForNewStage()` sets `_blockSpeed = _prevBlockSpeed = _targetBlockSpeed = 1.0`. On crossing blocks, `DrawStep()` writes `_prevBlockSpeed` from every passed Div, leaving the immediate previous Div's normalized Speed. | Use this state model when RT-007 is ported. |
| RT-009 | User speed vs block speed | **APPROXIMATION** | `SetSpeed()` stores `_modeSpeedExt = userSpeed` and `_modeSpeed = userSpeed * _blockSpeed`. `SpeedProc()` moves `pHighSpeed` toward `_modeSpeed` in `SPD_INC=0.05` steps on a `1/60 s` timer unless speed is forced / visual state suppresses it. | Studio directly multiplies COMMAND speed by one block-speed factor. This is sufficient for a visual preview but not frame-exact speed-change behavior. |

### Native loader normalization

For one loaded Div, the R!SE loader effectively performs:

```text
if bmFlags & bSkip:
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

`Step.currentGap()` later returns `Gap * msPerLine / BeatPerLine`. For the common `BeatPerLine = 1/BeatSplit`, this reconstructs the raw Gap value; non-unit Real Scroll scales it accordingly.

## Visual placement / modifiers

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RV-001 | Base note Y projection | MATCH for Skip-aware route core | `LineBase.RePos()` calls `PlayBase.GetBlockBeat(block,line)`, multiplies the returned beat distance by `_baseVelocity`, and offsets the target/local transform. | Skip-aware preview now uses native Block/Line beat projection. `_baseVelocity` scale is still approximate. |
| RV-002 | `_baseVelocity` | **OPEN, construction path recovered** | `LineBase.CreateSplits()` stores `_judgeTime = msStart + line*msPerLine`, `_lastBeat = GetBlockBeat(block,line)`, `_startPosY = 50`, and computes `_baseVelocity` from a target/local Y distance divided by `_startGapTime`. | Recover `_startGapTime` source and ArrowMaker target geometry before replacing Studio's lane-spacing scale. |
| RV-003 | Accel / Decel | **APPROXIMATION, native curve recovered** | `LineBase.GetAccDecYOffset()` uses normalized visible Y in `[yMin,yMax]`, serialized `_accPow`, `_accScale`, and a `-200` scale. Accel uses `1 - pow(t, accPow)`; Decel uses `pow(1-t, accPow)` before multiplying by `-200 * accScale`. | Studio currently applies `abs(pixels)**1.08` or `**0.92`. This is not source-derived. Exact parity also needs the prefab values of `_accPow/_accScale/yMin/yMax`. |
| RV-004 | Earthworm / Snake | **APPROXIMATION** | R!SE drives `_snakeBase`, `PlaySnakeAnim()` and SpeedMode state. | Studio currently uses a synthetic sine X offset. Exact animation assets/state still need audit. |
| RV-005 | Random Velocity | **APPROXIMATION** | R!SE exposes `GameModifier.SpeedMode.RandomVelocity` and handles SpeedMode inside `DrawStep`/visual processing. | Studio currently uses deterministic `uniform(0.65, 1.35)` per event. Native range/function still to recover. |
| RV-006 | Visibility modifier | **OPEN** | `GameModifier.Visibility`: Visible=0, Vanish=1, Appear=2, Hidden=3, separate from per-note `Effects`. | Studio combines COMMAND appearance and per-note fade through a custom opacity curve. Audit native `SpliteScript.SetVanish/SetAppear` before claiming parity. |
| RV-007 | Throw mode | **OPEN / not modeled exactly** | `GameModifier.Throw`: Flat=0, Sink=1, Rise=2; `LineBase` has `_throwAnim` / `PlayThrowAnim()`. | Studio modifier behavior needs direct comparison. |

## Judgment / note semantics

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RJ-001 | Raw note attribute bits | **PARTIALLY CLOSED; terminology mismatch remains** | `Attributes`: `0x20 NoJudge`, `0x40 JudgeMiss`, `0x60 NoMiss`; `0x10 bNoRush`; long mask `0x0C`; type mask `0x03`. `PUMPPlayer.JudgeLine()` explicitly skips notes whose JudgeMask is exactly `NoJudge (0x20)`. | Studio labels `0x20` Ghost, `0x60` Bonus, and treats Ghost as non-registering. This is directionally consistent for `0x20`, but `0x40/0x60` judgment effects need a complete JudgeUnit/JudgeNote pass before changing UI terminology. |
| RJ-002 | Note types | MATCH at raw type-mask level | Native `TypeMask=0x03`: Item=1, Special=2, Normal=3. Long state is carried separately in `0x0C`. | Studio note-type decode matches this layout. |
| RJ-003 | Long flags | MATCH at raw decode level, runtime processing open | Native `LongStart=0x04`, `LongMiddle=0x08`, `LongEnd=0x0C`, `bLong=0x1C` including NoRush. | Studio head/body/tail glyph mapping is structurally compatible. Whether every body/tail should produce the current simulator judgments is still open. |
| RJ-004 | Per-note visibility bits | MATCH at raw decode level | R!SE `Effects`: Hidden=0, Appear=1, Disappear=2, Visible=3; bit `0x10` is ZigZag. | `PreviewNoteVisibility` uses the same low two bits. Fade curve and ZigZag transform remain visual-audit items. |
| RJ-005 | Judgment timing model | **APPROXIMATION, native construction recovered** | `PUMPPlayer.SetJudgeTiming(delay=2.5)` uses a 16.666666 ms frame base, optional runtime scale, `PerfectFrame`, `Interval`, `nGrade=4`, and Delay. `Step.SetJudgeTiming` sets `Start = -(Perfect + 3*Interval + Delay)` and `End = Perfect + 3*Interval` and builds the grade table. | Studio hard-codes symmetric 41.67 / 83.33 / 125 / 166.67 windows. Default R!SE modifiers happen to start at `PerfectFrame=2.5`, `Interval=2.5`, but Delay makes the full native window asymmetric and difficulty can alter both values. |
| RJ-006 | Judge difficulty | **DIVERGENCE / not modeled** | `GameModifier.SetJudgeDifficulty(int)` changes `PerfectFrame` and `Interval`; headers/modifiers also expose Judge Bank / Difficulty / Reverse / By Note. | GameplaySession currently has one fixed judgment table regardless of profile/header metadata. |
| RJ-007 | Base score table | **DIVERGENCE** | Native base table is Perfect=1000, Great=500, Good=100, Bad=-200, Miss=-500; long-note Miss=-300. | Studio uses Perfect=1000, Great=800, Good=500, Bad=200, Miss=0. |
| RJ-008 | Native score bonuses | **NOT MODELED** | `PUMPPlayer.GetScore(judgment, combo, noteNum, isLongNote)`: Perfect/Great gain +1000 at combo >=51; for those grades, a 3-note row multiplies score by 1.5 and >3 notes doubles it. Long-note Miss returns -300. | Studio adds a simple `combo * 10` bonus and has no native chord multiplier path. |
| RJ-009 | Forced judgment / Div 999 | **OPEN in preview** | Runtime enum name is `dpAutoplay`; prior NXA/R!SE behavior establishes values 1..4 as forced Perfect/Great/Good/Bad. | Ensure Gameplay Preview honors Division metadata 999 rather than treating it as generic autoplay. Value 5 remains unverified. |

## Gauge / life

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RG-001 | Gauge defaults | **DIVERGENCE** | `Gauge.Constants`: Perfect=12, Great=10, Good=0, Bad=-50, Miss=-500; GaugeDefault=500, LimitDefault=1000, DispMaxDefault=1000. | Studio session starts at 100 and uses +8/+4/+1/-20/-40. These numbers are not R!SE-native. |
| RG-002 | Gauge dynamics | **NOT MODELED** | `Gauge.SetJudgeGauge()` applies a dynamic `Gauge_factor`, scales by an optional factor, clamps Life 0..Limit, and changes the factor after judgments. Miss damage depends on current Life and the factor state. | A static delta table cannot reproduce native life behavior. |
| RG-003 | Gauge metadata | **OPEN integration** | Chart params 80..85 map to Gauge Max, Display Max, Init, Break, Miss Combo Break, Gauge Link. | Editor metadata can preserve/show these, but GameplaySession does not yet feed them into a native gauge model. |

## Editor / authoring

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RE-001 | Encoded-row grid | MATCH by design | Native Div retains `nLine` and `BeatPerLine` even for Skip. | Editor keeps all encoded rows editable. Runtime playhead projection is separate. |
| RE-002 | Block `Speed` sign | PARTIAL MATCH | Loader uses raw sign during Gap conversion, then normalizes negative Speed to positive runtime Speed. | Editor's Freeze checkbox preserves the raw negative sign, which is appropriate for authoring; runtime preview must use loaded positive Speed semantics. |
| RE-003 | `Scroll Factor` / BeatPerLine | MATCH at storage level | Native `Div.BeatPerLine` is the raw spatial-per-line float. | Studio preserves raw Scroll. `Real Scroll = Scroll * BeatSplit` is an editor-derived convenience value, not a separate native field. |
| RE-004 | Div flag editing | **FIXED on audit branch** | Native byte is a `[Flags]` field with currently named bits 0 and 1. | UI now exposes Smooth and Skip independently and preserves unknown bits instead of normalizing the byte. |

## Native defaults relevant to preview

`GameModifier.Clear()` establishes, among other fields:

```text
Speed = 2.0
SpeedMode = Static
AccDec = Linear
Visibility = Visible
PerfectFrame = 2.5
Interval = 2.5
```

`ClearForNewStage()` establishes:

```text
_blockSpeed = 1.0
_prevBlockSpeed = 1.0
_targetBlockSpeed = 1.0
```

These are runtime defaults, not necessarily the values a Studio command/UI should display as its own neutral multiplier.

## Source anchors

Important R!SE methods/types used by this audit:

- `Attributes`, `ExtraFlags`, `Effects`, `Division`, `DivFlags`, `JUDGE`, `SCORE` in `dump.cs`.
- `GameModifier.Clear` RVA `0x517870`.
- `GameModifier.SetJudgeDifficulty` RVA `0x517900`.
- `Gauge.SetJudgeGauge` RVA `0x518C90`.
- `StepLoader.Load` RVA `0x751B80`.
- `Step.GetBlock` RVA `0x74BFA0`.
- `Step.GetLine` RVA `0x74C4C0`.
- `Step.SetCurrentTime` RVA `0x74C570`.
- `Step.currentGap` RVA `0x74C7B0`.
- `Step.DivEndTime` RVA `0x74C890`.
- `Step.SetJudgeTiming` RVA `0x74BB50`.
- `Step.Judge` RVA `0x74D100`.
- `PUMPPlayer.SetDefaultHighSpeed` RVA `0x7451B0`.
- `PUMPPlayer.SetSpeed` RVA `0x746330`.
- `PUMPPlayer.SpeedProc` RVA `0x746360`.
- `PUMPPlayer.SetJudgeTiming` RVA `0x746B00`.
- `PUMPPlayer.JudgeLine` RVA `0x7474D0`.
- `PUMPPlayer.GetScore` RVA `0x748A40`.
- `PUMPPlayer.DrawStep` RVA `0x748B50`.
- `PlayBase.GetBlockBeat` RVA `0x656220` / private overload `0x656300`.
- `LineBase.GetAccDecYOffset` RVA `0x638B20`.
- `LineBase.RePos` RVA `0x638CA0`.
- `LineBase.CreateSplits` RVA `0x639720`.

## Next audit order

1. Migrate exact `bSmooth` block-speed interpolation together with the obsolete `smooth_speed=2` tests.
2. Finish `_startGapTime` / `_baseVelocity` construction and determine how much of native vertical scale is appropriate for the Studio preview.
3. Finish `JudgeUnit` / `JudgeNote` / long-note processing, especially `JudgeMiss`, `NoMiss`, Rush and hold-body behavior.
4. Port or explicitly label judgment/score/gauge simulation levels: native R!SE vs simplified preview.
5. Audit appearance, ZigZag/Snake, Earthworm, Random Velocity and Throw transforms.
6. Audit header/division modifiers that already have known names but are not yet consumed by GameplaySession.
