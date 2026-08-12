# Phase 6 Windows validation

Phase 6 is implemented but remains unpublished until its native Windows and
noteskin gates pass. Run every destructive test on a copied chart
folder. `Save All` is guarded; that does not make an irreplaceable source folder
a sensible test fixture.

## Automated suite

From the repository root in PowerShell:

```powershell
$Py = (Resolve-Path ".venv\Scripts\python.exe").Path
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "windows"

& $Py -m unittest discover -s tests -v
$TestExitCode = $LASTEXITCODE

Write-Host "Exit code: $TestExitCode"
```

Expected on the validated Windows setup:

```text
Ran 147 tests
OK (skipped=1)
Exit code: 0
```

The expected skip is the case-collision test on a case-insensitive filesystem.
All nine Qt tests must run rather than skip. One constructs the multimedia
transport and verifies the 64-bit position/duration signal bridge used by
PySide6 6.11 and newer; another renders a synthetic atlas to verify that the
head shaft begins only below the opaque arrow artwork.

## Manual editor gate

Launch a copied chart folder:

```powershell
& ".venv\Scripts\stepnx-studio.exe" "C:\path\to\copied-chart-folder"
```

Validate these behaviors:

1. **Block timing**
   - Select a Block in the tree and open **Edit → Structure → Edit Block timing**.
   - Change Start Time, BPM, Scroll Factor, Offset/Delay, Speed/Freeze, Beat
     Split, Beat Measure, Smooth Speed, and Raw Flag.
   - Confirm one Undo restores all fields together and Redo reapplies them.
   - Test **Shift all Start Times** and verify it is also one Undo step.

2. **Selection and bulk operations**
   - With the Select tool, drag a rectangle; use `Shift` to extend and `Ctrl` to
     toggle cells.
   - Test copy/paste, mirror, erase, filtered replace, and application of the
     current placement tool.
   - Verify each operation takes one Undo step and paste refuses to cross a
     lane or Block boundary.

3. **Dense splits and snapping**
   - Compare a low Beat Split with a high one.
   - Under **File → Settings → Snap**, check **Off**, **1 beat**, **1/2 beat**,
     **1/4 beat**, and **1/8 beat** snapping. **Off** must be the default.
   - Confirm the active snap grid has visible blue guides and that clicks land
     on the closest guide. **Off — every row** intentionally disables rounding.
   - Confirm one wheel notch scrolls `0.5 beat` in both charts.
   - Confirm note heads remain square at minimum and maximum zoom.

4. **Noteskin holds**
   - Start with the bundled royalty-free noteskin. A local `noteskin` directory
     beside the checkout may override it but is not tracked by Git.
   - Inspect hold heads, body continuity, and tail caps at several zoom levels.
   - The body must preserve each direction's horizontal offset and remain
     continuous. The head shaft begins exactly below the opaque arrow artwork;
     the complete tail cell supplies shaft only above the arrow. No repeated
     strip may be painted behind the head artwork.

5. **Note flags**
   - Place and select taps, all hold parts, and less common odd-nibble note
     variants, then apply Normal/Hidden/Ghost functionality and
     Visible/Appear/Vanish/Invisible visibility.
   - Confirm the viewport shows `H`, `G`, `X`, `▿`, and `▵` markers in the same
     combinations as StepEdit.
   - Confirm Undo restores the exact prior four bytes. Applying flags must not
     change note type, bank, slot, Brain Shower value, or Division trigger bits.

6. **Audio**
   - Verify automatic discovery and manual selection.
   - Start playback with an active selection and confirm audio seeks to its
     anchor row. Clear the selection, scroll elsewhere, and confirm Play seeks
     to the beat at or immediately before the 7% playhead position.
   - **Follow chart** must be enabled by default under **Audio**. Confirm the red
     playhead stays near 7%
     of the viewport height while moving from the Qt audio clock at the
     expected Block Start Time/BPM.
   - Change the session offset and confirm the waveform moves without changing
     NX20 bytes.
   - Start with the bundled `BEAT.WAV`, or override it with a file beside the
     checkout or through **Audio → Select metronome WAV**. Enable the metronome and check
     beat/measure continuity after seeking; the Windows system beep must never
     be used. **Per arrow** must be the default; test it and **Per beat**. A chord must produce one
     tick, and hold bodies/tails must remain silent.
   - In **Per arrow**, Hidden and Invisible-registering taps/hold heads must
     tick, while Ghost notes must not. Visibility alone does not control sound.
   - Compare low and high Beat Split values: one beat must retain the same
     vertical height while the individual rows become denser. During playback,
     confirm each Block uses `scroll` as its vertical scale, `scroll = 0`
     collapses, and pausing restores authoring spacing. Smooth-warp Blocks
     (`smooth speed & 0x02`) must be skipped.
   - Confirm Split/Block/BPM information appears in the right-side gutter and
     never consumes a row above the chart.
   - Select `732.AUD` and confirm it decodes to a temporary MP3 and plays.
     `D91.AUD` and `508.AUD` must report an unsupported ENC2 key profile rather
     than playing corrupt output.
   - PCM WAV should show a waveform. Compressed formats use Qt playback but do
     not yet receive waveform extraction.

7. **Publication guard**
   - Save the copied folder, inspect the structural-diff confirmation, reopen
     it, and confirm every edited value remains present.
   - Run the full suite once more after the manual save test.

Record screenshots or exact error output for any failed item. “It looked odd”
is not a diagnostic; the selected tool, Beat Split, zoom, audio type, and action
sequence usually expose the actual fault in seconds.
