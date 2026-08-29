# R!SE Runtime Parity Audit — Fresh-Chat Handoff

This file is the continuity anchor for continuing the StepNX Studio audit against Pump It Up R!SE without depending on prior chat state.

## Working branch

`audit/rise-runtime-parity`

The branch starts from the PUPA Skip-timing hotfix and keeps the broader runtime-parity work isolated from the release hotfix.

## Primary-source corpus

Primary specification:

- `GameAssembly.dll` — Pump It Up R!SE IL2CPP runtime
- `dump.cs` — IL2CPP metadata dump when available
- `script.json` — IL2CPP metadata/method map when available

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

Primary binary anchor: `ApplyStepParamToMod` RVA `0x659F00`.

### Scope finding

The recovered R!SE path reads the loaded Step's global Header StepParam array at `Step + 0x28`.

Split metadata is stored separately (`Split + 0x18`), but no second `ApplyStepParamToMod` path applying Split metadata to `GameModifier` has been recovered. Therefore the preview now:

- preserves both Header and Split StepParams in `PreviewSnapshot`;
- applies only Header StepParams to `EffectiveModifier`;
- does **not** invent Header -> Split modifier overrides from the editor registry's historical `_HEADER_SPLIT` scope.

Revisit this only if a direct runtime consumer of Split StepParams is recovered.

### Lookup behavior

R!SE scans the serialized `(id, value)` pairs from the beginning and returns the first matching ID. Duplicates are therefore **first-wins**. Never convert StepParams to a normal dict for runtime projection.

The float getter does not numerically cast the uint32 payload. It preserves the four raw bytes and reinterprets them as IEEE-754 `float`.

### GameModifier defaults

`GameModifier.Clear()` RVA `0x517870` establishes at least:

```text
Speed        = 2.0
SpeedMode    = Static (0)
AccDec       = Linear (0)
Visibility   = Visible (0)
PerfectFrame = 2.5
Interval     = 2.5
```

### Implemented StepParam projections

`src/stepnx/preview/modifiers.py` now contains `StepParam`, `EffectiveModifier`, enums, and `apply_step_params()`.

Recovered scalar effects currently projected:

```text
0    Speed
1    SpeedMode: 0 Static, 1 Earthworm, 2 RandomVelocity
2    AccDec: 0 Linear, 1 Acceleration, 2 Deceleration
16   Visibility: 0..3
17   Freedom
18   Flash
19   Random skin selector
21   X / EXCEED mode side state
22   NX mode side state
32   Under Attack / Drop bit state
33   Throw: 0 Flat, 1 Sink, 2 Rise
34   Snake
35   ZigZag
48   Mirror
49   Alternate Random
50   Runner
64   legacy Judge-by-Note field
65   PerfectFrame / Interval decimal decoder
66   Reverse Grade
67   Judge Hide
68   Judge by Note
69   three-state modifier, retained neutrally until enum name is reverified
70   two float fields, retained neutrally until names are reverified
71   boolean modifier, retained neutrally until name is reverified
80   gauge maximum
81   gauge display maximum
82   starting gauge
83   Stage Break
84   forced Stage Break miss-combo threshold
85   global integer side state, retained neutrally until name is reverified
1111 multiplier applied to already-effective Speed
```

ID 20 uses a non-scalar helper and is intentionally not guessed. ID 1110 is looked up by this method but its scalar result is not directly stored there, so it is also not invented.

Header Speed (`ID 0`) uses the float-bit getter. After decoding:

```text
if 0 < speed <= 255:
    speed *= 0.25
else:
    speed remains direct
```

`-1.0` is the no-value sentinel from the float lookup.

ID 65 currently updates only `EffectiveModifier.perfect_frame` and `.interval_frame`. It does not yet alter `GameplaySession` judgment windows; that belongs to the native judgment-window item.

COMMAND remains a separate launch/runtime input. It is deliberately not folded into `EffectiveModifier` yet because speed priority and visual modes are audited separately.

### Tests

The first Item-1 run exposed nine failures caused only by inserting `PreviewSplit.step_params` before the existing positional `blocks` field. That API break was corrected by keeping `blocks` in its old position and making `step_params` an appended defaulted field. Runtime-correct Skip tests were retained.

Final full suite after Item 1:

```text
Ran 430 tests
OK
```

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
