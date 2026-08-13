# Phase 8 Windows validation

Run this gate on a copied chart folder. A preview is read-only, but the same
application still contains authoring and guarded save commands.

## Automated suite

From the repository root in PowerShell:

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

Expected on Windows: at least 220 tests discovered, the existing case-collision
test skipped, no other skips, and exit code 0. All five `test_qt_preview` tests
and all existing Qt viewport tests must execute rather than skip. The gate
rejects a superficially successful run if PySide6 is missing.

## Windows package

To build the unsigned Windows artifact after the strict gate:

```powershell
py -3.12 -m venv .venv-package
powershell -ExecutionPolicy Bypass -File tools/build_windows_package.ps1 `
  -Python ".\.venv-package\Scripts\python.exe"
```

The resulting archive is `dist\StepNX-Studio-Windows.zip`. Extract the whole
directory before running `StepNX-Studio.exe`; its `_internal` directory is
required by the application.

## Manual gameplay-preview gate

Launch the application with a copied native NXA chart folder:

```powershell
& ".venv\Scripts\stepnx-studio.exe" --profile nxa-native "C:\path\to\chart-copy"
```

Validate:

1. Open **Preview → Open gameplay preview**. Confirm one dialog contains only
   `.NX` filenames, 1x–9x, and COMMAND. Select a file other than the current
   timeline and confirm that exact file opens. No redundant Single/Double,
   legacy difficulty name, or seed control may appear.
2. Open the same chart containing random Splits several times. Confirm random
   choices vary without exposing a seed, while non-random Splits keep their
   active Block choice. Within one run, `81/41` must always select the same
   Block index, as must `82/42` and `83/43`; bank 1 must not force bank 2 or 3.
   `80` and `40` have no bank: each occurrence must resolve independently, and
   a `40` must not reuse a preceding `80` result.
3. Press `F8` during playback. Confirm it switches between autoplay and pad
   input without opening a separate simulation mode. Test P1 with `Q E S Z C`
   and P2 with `Home PageUp Num5 End PageDown`. Confirm top-row `5` changes speed
   to 5x while numeric-keypad `5` presses only the P2 center receptor.
4. Add an applause/Cheer condition or create an ambiguous non-random Split.
   Confirm preview is blocked with a diagnostic instead of selecting Block zero.
5. Seek and play audio. Confirm notes move toward the receptor using the shared
   audio offset, Pause freezes the frame, and changing the session offset moves
   authoring and preview together.
6. Press every key from `1` through `9`; confirm speeds 1x through 9x.
   Toggle F6, F9, and F11, and confirm their overlays/flags update. Press Space
   and confirm audio seeks forward exactly five seconds.
7. Load the bundled noteskin and a valid local animated noteskin. Confirm tap,
   hold, item, Division, receptor, press-overlay, and STEPFX assets render
   without copying anything into the chart folder. Remove an optional asset and
   confirm fallback shapes remain. STEPFX must use black-neutral additive
   composition and must not display an opaque black 512×512 rectangle. Every
   note, receptor, press overlay, and STEPFX frame must use the exact same lane
   centre. Draw the central 384 px of the `BASE.png` row as a five-pitch strip;
   the two 48 px edge regions are empty atlas padding. The two Double strips
   must be exactly adjacent, with neither a
   special centre gap nor overlap. No vertical lane divider lines may appear.
8. Compare a simple NXA chart at two BPM values and a discontinuous explicit
   Block Start Time against NXA capture. Note arrival times must match the stored
   anchors and `60000 / (BPM * Beat Split)` row duration.
9. Exercise Smooth Speed values 0 through 3, negative Speed/Freeze, zero Scroll,
   and a non-finite Scroll fixture. All Smooth Speed Blocks must retain their
   notes. Nonzero Smooth Speed interpolates the fifth Block float rather than
   suppressing events; zero Scroll is a valid stationary display segment.
10. Keep a preview tab open, edit the source timeline, and confirm the preview
   remains the immutable run created at opening. Open a new preview to observe
   the new document state.
11. Close preview tabs, reopen charts, and run guarded Save All. Confirm merely
    previewing never dirties or changes an NX/NFO file.
12. Enable the existing **Audio → Metronome** toggle and test both per-arrow and
    per-beat modes while the preview tab is active. Confirm it follows the
    immutable chart snapshot opened by that preview and that no second preview-
    specific metronome control appears.
13. In the authoring editor, compare Beat Split 8 and Beat Split 128 Blocks.
    While paused, every encoded row must retain the same 48 px default height;
    one beat must occupy respectively 8 and 128 rows. During Play, projection
    must use `Scroll × Beat Split`: ordinary blocks retain the selected zoom
    and a zero-Scroll block consumes no vertical space.
14. Set a usable authoring zoom, start Play, then Pause. The row zoom must not
    remain perceptually continuous at either transition. Scroll to the middle
    of the chart and repeat: Pause must leave the playhead at the exact same
    screen position. Beat Split, Scroll, and Smooth Speed must not rescale the
    paused authoring grid.
15. Build a short chart containing Normal, Appear, Vanish, Invisible, Bonus,
    Hidden(Vanish), Hidden, Ghost, Ghost(Appear), and Ghost(Vanish). Confirm
    Ghost uses atlas row 2 and produces no judgment or STEPFX; Invisible and
    Hidden remain visually absent but still register; Appear/Vanish affect only
    presentation. Repeat with COMMAND `n`, `v`, `w`, `f`, `m`, `r`, `j`, and
    `e`. Non-Step must hide moving notes, Freedom only the sequence zone, Flash
    must not create/destroy judgments, and remapped manual input must follow the
    displayed lane.
16. Force one audio-position update to cross several rows. Confirm only effects
    younger than 250 ms are shown; old notes must not erupt together across all
    ten receptors and the first STEPFX must not stall PNG decoding.
17. In autoplay, test a chord and a hold. A chord must produce one visible
    judgment/combo increment for the row, not one per lane. Hold head, body, and
    tail rows must all contribute, while STEPFX fires only for the initial pad
    press. Repeat with F8 disabled and manual input.
18. Keep F6 visible through a Smooth Speed 2 section. Record displayed FPS and
    PAINT ms; paint cost should remain below the frame budget and should not
    spike merely because the chart contains many earlier events or holds. Also
    from an installed package, run
    `stepnx-preview-benchmark CHART.NX --noteskin PATH`. From an extracted
    source ZIP in PowerShell, use
    `$env:PYTHONPATH="src"; python -m stepnx.preview.benchmark CHART.NX --noteskin PATH`.
    Retain the exact output; the default gate is 30 fps over 600 actual Qt
    paints.
19. In the editor, play across two overlapping explicit Block time ranges where
    the earlier Block uses Smooth Speed 2. The playhead must switch to the most
    recently started Block rather than remaining stuck in the earlier range.

The PIUTESTER package is a private reference. Do not place its executable, DLLs,
scripts, BGA archives, screenshots, or extracted assets in the repository or
validation archive. See `PIUTESTER_BEHAVIOR_AUDIT.md` for the evidence boundary.

Do not mark the phase complete without the exact automated count, exit code,
and the NXA timing comparison notes.
