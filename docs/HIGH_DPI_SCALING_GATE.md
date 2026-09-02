# StepNX Studio 0.9.5 editor-field zoom gate

Date: 2026-09-02

Status: implemented for 0.9.5 hardening item 5; awaiting manual Windows validation.

## Scope

Item 5 is **not application-wide DPI scaling**. The surrounding StepNX Studio UI
keeps its normal Qt size. Only the Timeline/editor field is scaled: encoded-row
geometry, lanes, ruler, Split/Block information area, waveform, notes, Lightmap
lights, selection outlines and the hit-testing geometry that belongs to that
field.

The existing 100% editor field is the accepted baseline. The item-5 validation
matrix therefore contains the eight additional presets:

- 125%
- 150%
- 175%
- 200%
- 225%
- 250%
- 275%
- 300%

Scaling above 300% is outside the 0.9.5 gate.

Menus, toolbars, Workspace tree, chart tabs, Inspector, Diagnostics, Routes,
status bar and authoring dialogs are explicitly outside this zoom transform.
They remain at the application's ordinary UI scale.

## User-facing control

`View > Editor zoom` exposes 100% through 300% in 25% increments. The selection
is shared across currently open authoring Timeline tabs and is applied to a newly
activated Timeline tab as well.

The pre-existing Ctrl+wheel Timeline magnification remains a separate vertical
precision control. Changing Editor zoom scales the *current* row geometry and
its vertical-zoom bounds by the same ratio, so a user's Ctrl+wheel precision
level is preserved when switching between editor zoom presets.

## Geometry contract

At every preset, these values scale together relative to the previous preset:

- encoded-row height;
- lane width;
- ruler width;
- Split/Block information width;
- footer/segment spacing;
- minimum and maximum row-height bounds used by vertical precision zoom.

The Timeline layout is rebuilt after a preset change. Horizontal and vertical
scroll positions are adjusted around the viewport centre so zooming does not
arbitrarily throw the user to an unrelated chart location.

Because render and hit-test code consume the same `TimelineGeometry` and
`TimelineLayout`, the painted lane/row and the clickable lane/row must remain the
same object-space target at every preset.

## Required validation

For each of 125%, 150%, 175%, 200%, 225%, 250%, 275% and 300%, verify:

1. notes, lane boundaries and timing rows remain aligned;
2. mouse hit testing selects the visibly targeted row/lane;
3. keyboard cursor and Shift-selection outlines remain aligned;
4. cross-Block/Split selections remain coherent across different Beat Splits;
5. waveform and playhead remain aligned with chart timing;
6. Tap/Hold/Roll/Item/Division artwork stays centred on its lane;
7. scrolling can still reach the beginning and end of the editable field;
8. `LM.NX` keeps exactly three light lanes, with light rectangles and selection
   outlines aligned to the same scaled geometry;
9. Toggle/Select/Cut/Copy/Paste/Delete still target the intended Lightmap cells;
10. surrounding application chrome does **not** resize when the editor zoom
    preset changes.

The Lightmap visual baseline for this gate is 80% alpha for an active light and
5% alpha for an inactive light. Lightmap selection uses the exact light rectangle
rather than the generic playable-chart cell outline.

## Automated gate

The item-5 regression suite checks all eight new presets in one run. It verifies:

- the exact 100..300 preset sequence in 25% steps;
- proportional Timeline geometry at every new preset;
- preservation of an existing Ctrl+wheel vertical magnification ratio;
- row/lane hit testing at every preset;
- Timeline viewport size remaining unchanged while internal field geometry grows;
- Lightmap light rectangles following the same scaled lane geometry.

These are logical/offscreen assertions. They deliberately do not attempt
pixel-perfect screenshot comparison because platform font and rasterization
choices are outside the editor-field geometry contract.

## Completion criterion

Item 5 is complete when the automated 607-test hardening gate is green and the
eight new editor zoom presets have passed one manual Windows authoring smoke pass.
Any failure where the painted target and input target diverge is blocking. Purely
cosmetic issues are fixed when practical or recorded explicitly if non-blocking.
