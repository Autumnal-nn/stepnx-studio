# Experimental STEPEdit-inspired Qt editor (M4)

Status: **opt-in, not production-ready**. Stacked after M1/M2/M3.
The current Timeline and gameplay preview remain unchanged.

## Trying it

1. Start StepNX Studio with the normal `stepnx-studio` launcher and open a chart.
2. Use **Experimental → STEPEdit-inspired editor (experimental)…**.
3. A **modal** editing window opens with Toggle tap, Paint taps, Erase cells, Select, Split, Block, and zoom selectors.
4. The experimental viewport edits the **same** `CommandStack` as the normal editor. Changes stay in memory until you return to Studio and use the existing **Save All** workflow. Closing the window does not save or discard edits.
5. Use `Ctrl+Z` / `Ctrl+Y` inside the window to undo/redo. Hit Escape to cancel an in-progress pointer gesture.

## Implemented interaction contract

- Toggle: click an empty cell to place the selected Tap preset; click a populated non-Hold cell to clear it.
- Paint taps / Erase cells: left drag inside one selected Block, commit one atomic undo step on release. Repeated visits to a cell are deduplicated.
- Shift+drag or Select: rectangular selection inside one Block. Ctrl+click toggles an individual cell.
- The indicator at the left of a Split cycles the visible Block; Split and Block selectors provide explicit navigation.
- Zoom presets and hit testing follow M3 per-BeatSplit geometry. The widget draws only the visible row window, not all chart rows.
- Whole-Hold erase/toggle, Hold creation, Lightmap editing, cross-Block selection and structural resize are intentionally not implemented here. Hold operations are **rejected rather than altered unsafely**.
- The current engine-dependent Tap composition is reused from `phase10_install._regular_note_raw`, including the selected noteskin bank and flags.

## Safety boundaries

- The experimental editor runs modally so the legacy editor cannot execute concurrent GUI mutations on the same stack.
- An `EditorEventScope` is captured for each pointer-down and a `StrokeLease` is required on pointer-up. Changing Split/Block, cancelling a stroke, or returning to the main editor prevents an earlier pointer event from committing.
- Visual painting uses `StepEditGridLayout`; it does not serialize NX20 or build a second persistence path.
- The existing main-window `_apply_document` is invoked on return **only if** the command stack's current document has changed. That method continues to own tab state, diagnostics, routes and workspace save visibility.
- The experimental renderer now uses a fixed-size provisional vector tile artist and is **not yet** sprite- or noteskin-identical to STEPEdit.
- Dense rows may require higher zoom to distinguish physically adjacent input targets.

## Visual matching against STEPEdit

The original 5.63 static analysis confirms a 24-pixel lane/tile pitch and
`SetScrollSizes(..., sizeLine.cy = 24 * zoom)`; the legacy wheel handler
delegates to `CScrollView::OnMouseWheel`. The experimental Qt surface now uses
the OS-provided wheel-lines-per-notch setting (normally three), rather than
Qt's unrelated default scrollbar step; one normal notch therefore travels
`24 * zoom * system_lines` logical pixels. High-resolution wheel deltas
accumulate without losing fractional movement.

Reference screenshot measurements (280x844, provided during the M4 review):

- Grid background: `#FFFFEB`; indicator: `#D4D0C8`.
- Vertical and main beat-grid lines: `#005494`; intermediate grid lines:
  `#B2D7EB`; border/seam: `#FF0000`.
- Grid lane pitch: 24 px. **All note tiles are 24x24 px at every zoom.**
- Sprite origins are the **top-left of their encoded logical row**, not
  centered in a row; sprites may overlap at dense zoom/BeatSplit.
- Draw the grid in its own pass before drawing sprites, so a later grid line
  cannot obscure a note.

**Fidelity limitation:** the M4 application uses a provisional 24x24 vector
tile artist. It does not contain the copyrighted STEPEdit bitmap/mask atlas,
whose exact color, transparency, animation frames and item glyph mappings
cannot be reconstructed reliably from one screenshot. Pixel-identical note
rendering is therefore **not yet achieved**, despite pixel-accurate geometry
and palette sampled from the image. An original sprite atlas or suitably
licensed equivalent is needed for that part of the comparison.

## Release gates before promotion to default

Run `python -m unittest tests.unit.test_stepedit_experimental_qt -v` with `QT_QPA_PLATFORM=offscreen`, strict Windows CI, Linux CI, and manual interactive validation in Windows. Validate single/half/double/lightmap viewports, hidden Blocks, note types, press/release outside, Escape/focus loss, modal close with unsaved changes, Save All, import materialization, undo/redo after return, and performance on large source-backed charts.

The following require dedicated subsequent work, not automatic delegation to a second editor engine: whole-Hold semantics; note/item/division editing; context menus and Split resize; clipboard and transforms; noteskin rendering, transport synchronization, high-DPI screenshot fidelity, and mixed BeatSplit cross-Split selection.

This is an experimental test surface for collecting UX findings, not evidence that StepNX Studio 1.0 is release-ready.
