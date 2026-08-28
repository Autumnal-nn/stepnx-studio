# R!SE Runtime Parity Audit — Fresh-Chat Handoff

This file is the continuity anchor for continuing the StepNX Studio audit against Pump It Up R!SE without depending on prior chat state.

## Working branch

`audit/rise-runtime-parity`

This branch starts from the PUPA Skip-timing hotfix work and keeps the broader runtime-parity audit isolated from the release hotfix.

## Primary-source corpus

Local analysis was performed against:

- `GameAssembly.dll` — Pump It Up R!SE IL2CPP runtime
- `dump.cs` — IL2CPP metadata dump
- `script.json` — IL2CPP metadata/method map

Treat `GameAssembly.dll` + `dump.cs` as the primary specification whenever Studio behavior conflicts with older assumptions/tests.

## Validated PUPA / bSkip findings

`DivFlags`:

```text
bSmooth = 0x01
bSkip   = 0x02
```

Therefore:

```text
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

Key runtime methods already ported for Skip-aware timing:

- `Step.GetBlock` RVA `0x74BFA0`
- `Step.GetLine` RVA `0x74C4C0`
- `Step.SetCurrentTime` RVA `0x74C570`
- `Step.DivEndTime` RVA `0x74C890`
- `PlayBase.GetBlockBeat` RVA `0x656220`, private overload RVA `0x656300`

PUPA validated the resulting model in gameplay preview, authoring playback, and metronome. The important semantic separation is:

- judgment time
- Block/Line beat-space position
- visual speed multiplier

These must not be collapsed into one concatenated timing axis.

## Item 0 — COMPLETE SMOOTH MIGRATION

This is the next task to implement.

### Primary-source behavior

`PUMPPlayer.DrawStep()` RVA `0x748B50` tests only:

```text
currentDiv.flags & 0x01
```

A Skip-only Div (`flags == 2`) MUST NOT trigger Smooth interpolation.

Recovered state fields:

```text
_blockSpeed       +0x13C
_prevBlockSpeed   +0x140
_targetBlockSpeed +0x144
_modeSpeedExt     +0x138
_modeSpeed        +0x134
pHighSpeed        +0x100
```

`ClearForNewStage()` initializes:

```text
_blockSpeed = 1.0
_prevBlockSpeed = 1.0
_targetBlockSpeed = 1.0
```

When the current Div changes, `_prevBlockSpeed` is updated from the immediately preceding loaded Div Speed. Loaded negative Speed has already been normalized positive by `StepLoader`.

For a current Div with `bSmooth`, `DrawStep()` computes:

```text
prevEnd = 0                    if current Block == 0
prevEnd = DivEndTime(block-1)  otherwise
curEnd  = DivEndTime(current)

if curEnd > prevEnd:
    ratio = (msCurTime - prevEnd) / (curEnd - prevEnd)
else:
    ratio = 1

ratio = clamp(ratio, 0, 1)

_blockSpeed = _prevBlockSpeed
            + (_targetBlockSpeed - _prevBlockSpeed) * ratio
```

If the current Div is not Smooth, block speed is the current normalized Div Speed directly.

Important: the interpolation endpoint is the CURRENT Div end time. The old Studio approximation using the next Block StartTime is incorrect.

### Current Studio divergence

`src/stepnx/preview/events.py` still does:

```python
smooth_transition = block.smooth_speed != 0
```

and models the transition from current local `motion_start` toward the next Block StartTime.

This makes `Smooth Speed = 2` incorrectly behave as Smooth even though it is Skip only.

### Required migration

1. Move runtime block-speed calculation into the native timing layer, ideally `NativeTimingProjection.block_speed_at(time_ms)`.
2. Use `DIV_FLAG_SMOOTH = 0x01` only.
3. Use immediately previous Div normalized Speed, initial value `1.0`.
4. Use `prevDivEnd -> currentDivEnd` for the interpolation interval.
5. Clamp the ratio to `[0,1]`.
6. Preserve `2` as Skip-only, and make `3` Smooth+Skip.
7. Make `RuntimeEventStream.speed_factor_at()` use the native calculation instead of `PreviewTimingSegment`'s old transition approximation.
8. Replace the obsolete unit test `test_smooth_speed_two_keeps_notes_and_interpolates_speed`.
9. Add explicit tests for raw values 0, 1, 2, 3 and for the previous-Div-speed handoff.
10. Re-run the full test suite and visually re-check PUPA to ensure the validated Skip projection remains unchanged.

### UI fix already present on audit branch

`BlockTimingDialog` has been changed to independent Smooth and Skip bit toggles while preserving unknown upper bits. Do not revert this.

## Audit ledger

See:

`docs/RISE_RUNTIME_PARITY_AUDIT.md`

It contains the current classified findings for timing, visual placement, judgment, score, gauge, modifiers, and editor behavior.

## Planned order after Item 0

1. Header/Split `ApplyStepParamToMod` -> effective gameplay modifier state.
2. Speed / Gap / `_baseVelocity`.
3. `JudgeLine` / `JudgeNote` / `JudgeUnit` / long-note processing.
4. Native judgment windows.
5. Native scoring and gauge.
6. Accel/Decel and remaining visual modifiers.

## Other primary-source anchors already identified

- `PUMPPlayer.SetSpeed` RVA `0x746330`
- `PUMPPlayer.SpeedProc` RVA `0x746360`
- `PUMPPlayer.SetJudgeTiming` RVA `0x746B00`
- `PUMPPlayer.JudgeLine` RVA `0x7474D0`
- `PUMPPlayer.JudgeUnit` RVA `0x747A60`
- `PUMPPlayer.JudgeStep_PostProcess` RVA `0x748000`
- `PUMPPlayer.GetScore` RVA `0x748A40`
- `PUMPPlayer.DrawStep` RVA `0x748B50`
- `LineBase.GetAccDecYOffset` RVA `0x638B20`
- `LineBase.RePos` RVA `0x638CA0`
- `LineBase.CreateSplits` RVA `0x639720`
- `Gauge.SetJudgeGauge` RVA `0x518C90`

## Important policy for this audit

Do not change Studio behavior merely because a pre-existing unit test expects it. If a test contradicts `GameAssembly.dll`, treat the test as the regression artifact and replace it with a source-derived invariant.
