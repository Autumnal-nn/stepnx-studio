# Phase 7 Windows validation

Phase 7 includes the accumulated Phase 6 work and the final per-column hold-shaft
fix. Run the gate on a copied chart folder before committing or publishing the
branch.

## Automated suite

The validation snapshot is self-contained source code but deliberately excludes
the virtual environment. From the extracted repository root, create or refresh
the Windows environment in PowerShell:

```powershell
py -3.11 -m venv .venv
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -e ".[gui]"
```

Then run the suite from the same repository root:

```powershell
$Py = (Resolve-Path ".venv\Scripts\python.exe").Path
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "windows"

& $Py -m unittest discover -s tests -v
Write-Host "Exit code: $LASTEXITCODE"
```

Historical expected result for this phase snapshot:

```text
Ran 179 tests
OK (skipped=1)
Exit code: 0
```

The one expected skip is the case-collision test on Windows. All Qt tests must
execute.

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
   the corrected per-column hold shaft.
9. Confirm **File → Settings** contains Engine profile and Snap, the Audio
   toolbar contains only Play/Pause, Offset, and Metronome, and the **Audio**
   menu contains source selection, metronome mode, and Follow chart.
10. Ctrl-wheel to maximum zoom and confirm fixed Beat Split rows retain usable
    hit targets. Play and Pause must preserve the selected zoom; only the Block's
    explicit `Scroll` may scale playback rows.
11. Follow playback through the final chart timing. Confirm the viewport shows
    blank space below the chart and the playhead remains at its configured anchor
    instead of sliding toward the bottom edge.

After manual edits, reopen every saved NX/NFO and run the full suite again. Do
not commit a screenshot-driven success claim without the exit code and exact
test count.
