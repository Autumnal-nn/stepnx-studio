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
- The experimental renderer now uses the available 96px noteskin atlas with a vector fallback; its sprite content is **not** identical to STEPEdit's proprietary textures.
- Dense rows may require higher zoom to distinguish physically adjacent input targets.

## Visual matching and field zoom

The static STEPEdit 5.63 analysis confirms a 24-pixel lane pitch in the
original implementation and `SetScrollSizes(..., sizeLine.cy = 24 * zoom)`;
its wheel handler delegates to `CScrollView::OnMouseWheel`. The experimental
Qt implementation retains OS wheel-lines-per-notch behavior, adapted to its
new base grid scale.

For the StepNX viewport we deliberately use the project's **existing 96×96
noteskin atlas tiles**, rather than copying STEPEdit's copyrighted sprites or
drawing reduced provisional icons. The bundled royalty-free pack and the
locally selected noteskin are both supported, including bank-aware taps, Hold
terminals/bodies, normal items and Division artwork. Unsupported/raw variants
retain a vector fallback without modifying the chart. Frame zero is used for
deterministic authoring display.

- **Field zoom: 25%, 50%, 75%, 100%, 125%, 150%, 175%, 200%.**
- At 100%, the lane and noteskin tile are 96px; at 25%, 24px; at 200%, 192px.
  Horizontal lane width, sprite dimensions, indicator, and horizontal grid
  pitch change together. The underlying BeatSplit/timing never changes.
- Vertical beat-space uses 192px at 100%, scaled with the same factor. The
  tile does **not** shrink merely because adjacent note rows are closer than
  its displayed height. Sprites may overlap at dense subdivisions.
- Notes are top-aligned at each encoded row origin, not centered.
- Grid palette **cycles by physical Split order**, independently of its
  selected alternative: `#FFFFEB`, `#EBFFFF`, `#EBFFEB`, `#FFEBFF`;
  Split 5 restarts with Split 1's color.
- The selected cells use opaque `#C8C8C8` behind grid lines and sprites.
- Vertical/main grid `#005494`; minor grid `#B2D7EB`; border `#FF0000`;
  indicator `#D4D0C8`.
- Original source lanes are honored when looking up atlas tiles. Half Double
  chart local lanes 0..5 are not confused with source lanes 2..7.

This is **not a pixel-perfect STEPEdit clone**. The existing StepNX noteskin
assets match the native 96×96 rendering contract but not necessarily the
original STEPEdit 5.63 textures, masks or menu chrome. The visual coordinate
contract and asset provenance remain separate.

## Release gates before promotion to default

Run `python -m unittest tests.unit.test_stepedit_experimental_qt -v` with `QT_QPA_PLATFORM=offscreen`, strict Windows CI, Linux CI, and manual interactive validation in Windows. Validate single/half/double/lightmap viewports, hidden Blocks, note types, press/release outside, Escape/focus loss, modal close with unsaved changes, Save All, import materialization, undo/redo after return, and performance on large source-backed charts.

The following require dedicated subsequent work, not automatic delegation to a second editor engine: whole-Hold semantics; note/item/division editing; context menus and Split resize; clipboard and transforms; noteskin rendering, transport synchronization, high-DPI screenshot fidelity, and mixed BeatSplit cross-Split selection.

This is an experimental test surface for collecting UX findings, not evidence that StepNX Studio 1.0 is release-ready.
