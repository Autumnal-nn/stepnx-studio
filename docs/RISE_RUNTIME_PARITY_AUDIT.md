# R!SE Runtime Parity Audit

This document tracks source-primary comparisons between StepNX Studio and the Pump It Up R!SE IL2CPP runtime (`GameAssembly.dll` + `dump.cs`).

The audit deliberately separates three states:

- **MATCH**: Studio behavior is supported by the native runtime.
- **DIVERGENCE**: Studio behavior conflicts with the native runtime.
- **APPROXIMATION**: Studio intentionally provides a simplified simulation; native parity has not yet been implemented.
- **OPEN**: native behavior still needs to be recovered before changing Studio.

The NX20 codec remains lossless unless a finding explicitly says otherwise. Most findings here concern runtime/editor semantics rather than serialization.

## Timing / Div semantics

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RT-001 | Div flag byte | MATCH after PR #10 core timing work | `DivFlags`: `bSmooth = 0x01`, `bSkip = 0x02`. | `native_timing.py` uses independent bits. Raw byte must remain lossless. |
| RT-002 | Timing dialog flag UI | **DIVERGENCE** | Same `DivFlags` enum. | `timing_dialog.py` still treats any nonzero byte as Smooth and can erase `0x02` when the Smooth checkbox is cleared. Replace with independent Smooth / Skip toggles that preserve all other bits. |
| RT-003 | Preview Smooth trigger | **DIVERGENCE** | `PUMPPlayer.DrawStep()` tests `bmFlags & 0x01` specifically. | `events.py` still uses `block.smooth_speed != 0`, so Skip-only `0x02` incorrectly enters speed interpolation. |
| RT-004 | Skip timing | MATCH after PR #10 | `StepLoader`: Skip sets `msPerLine = 0`; `DivEndTime = msStart + nLine*msPerLine`; `GetBlock` advances on `end <= currentTime`; rows remain present/judgeable. | Native Block/Line projection added and validated against PUPA. |
| RT-005 | Normal Div inside a Skip route | MATCH after PR #10 | `PlayBase.Update`/`GetBlockBeat` continuous float32 projection. | Corrected `Player.Beat` sign and float32 boundary arithmetic. Validated against PUPA splits with Smooth=0 between Skip snapshots. |
| RT-006 | Loader Gap conversion | **DIVERGENCE / OPEN visual consumer** | `StepLoader.Load`: after `msPerLine` is calculated, `Gap = rawGap / (BeatSplit * msPerLine)` only when `msPerLine > 0` **and raw Speed > 0**; otherwise Gap becomes 0. Negative Speed is then normalized to positive. | Legacy preview still models negative Speed as `motion_start = StartTime + raw Delay`. Judgment timing does not do this natively. Need finish `LineBase`/`currentGap()` audit before replacing visual behavior globally. |
| RT-007 | Smooth speed interpolation curve | **DIVERGENCE** | `PUMPPlayer.DrawStep`: when current Div has `bSmooth`, interpolation ratio is based on native Div end times and is clamped 0..1; block speed interpolates from previous block speed to current target speed. | Current `PreviewTimingSegment` approximates transition using current motion start and the next block StartTime. Replace with native end-time interpolation. |

## Visual placement / modifiers

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RV-001 | Base note Y projection | MATCH for Skip-aware route core | `LineBase.RePos()` calls `PlayBase.GetBlockBeat(block,line)` and multiplies the returned beat distance by `_baseVelocity`. | Skip-aware preview now uses native Block/Line beat projection. `_baseVelocity` parity remains to audit. |
| RV-002 | Accel / Decel | **APPROXIMATION** | R!SE has `LineBase.GetAccDecYOffset()` with serialized `_accPow` / `_accScale` and native modifier state. | Studio currently applies `abs(pixels)**1.08` or `**0.92`. This is not source-derived. |
| RV-003 | Earthworm / Snake | **APPROXIMATION** | R!SE drives `_snakeBase` / animation state in `LineBase`; exact transform path still under audit. | Studio currently uses a synthetic sine X offset. |
| RV-004 | Random Velocity | **APPROXIMATION** | R!SE exposes `GameModifier.SpeedMode.RandomVelocity` and native speed processing. | Studio currently uses deterministic `uniform(0.65, 1.35)` per event. Native range/function still to recover. |

## Judgment / note semantics

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RJ-001 | Raw note attribute bits | **OPEN / terminology mismatch** | R!SE `Attributes`: `0x20 NoJudge`, `0x40 JudgeMiss`, `0x60 NoMiss`; long mask `0x0C`; type mask `0x03`. | Studio labels high-bit functions as Ghost / Normal / Bonus. Rendering may be useful, but judgment semantics must be audited against the native meanings before renaming or changing behavior. |
| RJ-002 | Visibility bits | MATCH at raw decode level | R!SE `Effects`: Hidden=0, Appear=1, Disappear=2, Visible=3. | `PreviewNoteVisibility` uses the same low two bits. Fade curves still need visual parity audit. |
| RJ-003 | Judgment windows | **APPROXIMATION** | R!SE has `JudgeTiming { Perfect, Interval, Delay, Start, End, nGrade }`; `SetJudgeTiming()` derives the full window table from those values. | Studio uses fixed 41.67 / 83.33 / 125 / 166.67 ms windows. Do not present these as engine-exact. |
| RJ-004 | Score constants | **DIVERGENCE** if preview claims native scoring | R!SE `SCORE`: Perfect=1000, Great=500, Good=100, Bad=-200, Miss=-500, long-note miss=-300, item=100. | Studio simulator currently uses 1000 / 800 / 500 / 200 / 0. Decide whether preview stats should become native or remain explicitly synthetic. |
| RJ-005 | Gauge deltas | **APPROXIMATION** | Gauge behavior is runtime/profile dependent and has dedicated classes + metadata (80..85). | Studio uses fixed +8/+4/+1/-20/-40. Native parity requires a separate gauge audit. |

## Editor / authoring

| ID | Area | Status | Native evidence | Studio state / action |
|---|---|---|---|---|
| RE-001 | Encoded-row grid | MATCH by design | Native Div retains `nLine` and `BeatPerLine` even for Skip. | Editor keeps all encoded rows editable. Runtime playhead projection is separate. |
| RE-002 | Block `Speed` sign | PARTIAL MATCH | Loader uses raw sign during Gap conversion, then normalizes negative Speed to positive runtime Speed. | Editor's Freeze checkbox preserves raw negative sign, which is appropriate for authoring. Preview must not treat that sign as a persistent negative runtime multiplier. |
| RE-003 | `Scroll Factor` / BeatPerLine | MATCH at storage level | Native `Div.BeatPerLine` is the raw spatial-per-line float. | Studio preserves raw Scroll. `Real Scroll = Scroll * BeatSplit` is an editor-derived convenience value, not a separate native field. |

## Source anchors

Important R!SE methods/types used by this audit:

- `DivFlags` in `dump.cs`: `bSmooth=1`, `bSkip=2`.
- `StepLoader.Load` RVA `0x751B80`.
- `Step.GetBlock` RVA `0x74BFA0`.
- `Step.GetLine` RVA `0x74C4C0`.
- `Step.SetCurrentTime` RVA `0x74C570`.
- `Step.currentGap` RVA `0x74C7B0`.
- `Step.DivEndTime` RVA `0x74C890`.
- `Step.Judge` RVA `0x74D100`.
- `PUMPPlayer.DrawStep` RVA `0x748B50`.
- `PUMPPlayer.SetSpeed` RVA `0x746330`.
- `PUMPPlayer.SpeedProc` RVA `0x746360`.
- `PlayBase.GetBlockBeat` RVA `0x656220` / private overload `0x656300`.
- `LineBase.RePos` RVA `0x638CA0`.
- `LineBase.GetAccDecYOffset` RVA `0x638B20`.
- `LineBase.CreateSplits` RVA `0x639720`.

## Next audit order

1. Finish exact `bSmooth` speed interpolation and update the flag UI.
2. Resolve raw Gap / negative Speed / freeze semantics through `Step.currentGap`, `LineBase.CreateSplits`, and `LineBase.RePos`.
3. Port `_baseVelocity` and Accel/Decel geometry where practical.
4. Audit raw note attribute judgment semantics (`NoJudge`, `JudgeMiss`, `NoMiss`) and long-note processing.
5. Audit judgment timing tables, combo/scoring, items, and gauge behavior.
6. Audit remaining COMMAND/modifier visual transforms (Earthworm, Random Velocity, appearance effects).
