# Phase 7 Windows validation

> Historical validation snapshot. This file records the Phase 7 acceptance gate
> and its then-current test count. It is not the current 0.9.5 gate. Use
> `STATUS.md`, `ROADMAP.md`, and `tools/run_windows_test_gate.py` for current
> release status and validation requirements.

Phase 7 included the accumulated Phase 6 work and the final per-column hold-shaft
fix. Run destructive validation only on copied chart folders.

## Automated suite

The validation snapshot was self-contained source code but deliberately excluded
the virtual environment. From an extracted repository root, the phase gate used:

```powershell
py -3.11 -m venv .venv
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -e ".[gui]"

$Py = (Resolve-Path ".venv\Scripts\python.exe").Path
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "windows"

& $Py -m unittest discover -s tests -v
Write-Host "Exit code: $LASTEXITCODE"
```

Historical result for this phase snapshot:

```text
Ran 179 tests
OK (skipped=1)
Exit code: 0
```

The recorded skip was the case-collision test on Windows. All Qt tests belonging
to that snapshot were required to execute rather than skip.

## Manual advanced-authoring gate

Launch with native NXA semantics:

```powershell
& ".venv\Scripts\stepnx-studio.exe" --profile nxa-native "C:\path\to\native-copy"
```

Validate:

1. Select Header metadata, a Split, and a Block in the workspace tree. Open
   **Edit → Metadata → Edit selected scope** and confirm the same numeric ID
   receives the correct contextual label.
2. Add, reorder, edit, and remove metadata. Confirm the entire dialog acceptance
   is one Undo step and duplicate IDs remain in the chosen order.
3. On a Brain Shower Block, open **Edit Brain Shower fields**. Verify packed
   ranges, answer count bounds, the inspector summary, and diagnostics for
   duplicate or unidentified fields.
4. Inspect the Routes tab. Confirm Split flags, Block condition ranges, and
   Division triggers. Double-click a branch and verify it activates the matching
   Block without dirtying the document.
5. Run both folder batches. Review the affected-file preview, confirm `LM.NX` is
   excluded, Undo an affected chart, then use guarded **Save All** on the copy.
6. For a sized-trailer fixture, inspect typed trailer strings. Safe replacements
   must preserve offset/pool invariants; invalid offsets, unterminated strings,
   non-UTF-8 data, or ambiguous relocation targets must remain blocked/raw-only.
7. Use **Compare / export NFO mirror**. Inspect the structural comparison and
   confirm no NFO changes occur merely by opening the folder.
8. Repeat the Phase 6 audio, playback geometry, note flags, snapping, and local
   noteskin checks in [`PHASE6_VALIDATION.md`](PHASE6_VALIDATION.md), including
   the corrected per-column hold shaft. Where Phase 6 documents an explicitly
   historical limitation, the newer documentation takes precedence.
9. Confirm **File → Settings** contains Engine profile and Snap, the Audio
   toolbar contains only Play/Pause, Offset, and Metronome, and the **Audio**
   menu contains source selection, metronome mode, and Follow chart.
10. Ctrl-wheel to maximum zoom and confirm fixed Beat Split rows retain usable
    hit targets. Play and Pause must preserve the selected zoom; only the Block's
    explicit `Scroll` may scale playback rows.
11. Follow playback through the final chart timing. Confirm the viewport shows
    blank space below the chart and the playhead remains at its configured anchor
    instead of sliding toward the bottom edge.

After manual edits, reopen every saved NX/NFO and run the current full suite
again. Current test counts belong in CI/output, not in this historical phase
record.
