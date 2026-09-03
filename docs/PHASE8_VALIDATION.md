# Phase 8 Windows validation

> Historical validation snapshot. Phase 8 introduced the gameplay-preview gate.
> The test counts and runtime assumptions below belong to that phase and are not
> current 0.9.5 requirements. The preview has since shipped in packaged releases
> and received substantial runtime-parity work. Use `STATUS.md`, `ROADMAP.md`,
> `RISE_RUNTIME_PARITY_AUDIT.md`, and `tools/run_windows_test_gate.py` for the
> current state.

A preview is read-only, but validation should still use a copied chart folder
because the same application contains authoring and guarded save commands.

## Historical automated gate

The Phase 8 Windows gate used:

```powershell
py -3.11 -m venv .venv
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -e ".[gui]"
$Py = (Resolve-Path ".venv\Scripts\python.exe").Path
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "windows"
& $Py tools/run_windows_test_gate.py
Write-Host "Exit code: $LASTEXITCODE"
```

The historical Phase 8 threshold was at least 220 discovered tests, with the
case-collision skip allowed on Windows and Qt preview/viewport tests required to
execute rather than silently skip. That number is preserved only as phase
history; current CI output is authoritative for the current suite.

## Historical package gate

The phase also established the PyInstaller Windows bundle path:

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_windows_package.ps1
```

The preview is no longer a pending implementation candidate or an unpublished
package experiment. Windows and Linux release packaging are part of the current
release workflow.

## Manual gameplay-preview coverage established by Phase 8

The phase gate established the following invariants that remain useful as
regression categories:

- the preview opens a chosen `.NX` chart without mutating the authoring document;
- random Split decisions are session state, while non-random choices remain
  deterministic and unresolved conditions block instead of falling back to
  Block zero;
- 1x through 9x speed keys, autoplay/manual input, guide/debug controls and
  two-player pad input share one execution surface;
- preview audio uses the shared transport and session offset;
- bundled/local noteskins, sequence-zone geometry, STEPFX and fallback rendering
  do not require proprietary assets in the repository;
- preview snapshots remain immutable after the source chart is edited;
- merely opening/running preview never dirties NX/NFO files;
- authoring row geometry remains separate from gameplay projection;
- Ghost/Hidden/visibility families remain distinct and source bytes are not
  rewritten for presentation;
- event/feedback histories are bounded so old effects do not erupt after a
  delayed audio update;
- preview paint performance has an explicit frame-budget benchmark.

Several detailed timing/modifier assumptions from the original Phase 8 checklist
were later superseded by source-primary runtime work. In particular, current
judgment timing, score, combo, grade, normal-mode gauge, Smooth/Skip behavior,
Acceleration/Deceleration, Earthworm, Random Velocity, historical ZigZag/Throw,
and field transforms are documented in `RISE_RUNTIME_PARITY_AUDIT.md` rather
than frozen to the early Phase 8 interpretation.

The PIUTESTER package remains a private behavioral reference. Its executable,
DLLs, scripts, BGA archives, screenshots, manual text and extracted assets must
not enter the repository or release archive. See `PIUTESTER_BEHAVIOR_AUDIT.md`
for the evidence boundary.
