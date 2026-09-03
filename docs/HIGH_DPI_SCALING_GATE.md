# StepNX Studio 0.9.5 editor-field zoom gate

Date: 2026-09-02

Status: **complete** for 0.9.5 hardening item 5.

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

Scaling above 300% is outside the 0.9.5 gate. The 300% preset is intentionally
retained despite being unusually large because it is useful for fine waveform
synchronization and for very high-resolution displays.

Menus, toolbars, Workspace tree, chart tabs, Inspector, Diagnostics, Routes,
status bar and authoring dialogs are explicitly outside this zoom transform.
They remain at the application's ordinary UI scale.

## User-facing control

The former top-level `Preview` menu is now `View`. Its first command remains
`Open gameplay preview…`; `Editor zoom` follows it and exposes 100% through 300%
in 25% increments.

The selection is shared across currently open authoring Timeline tabs and is
applied to a newly activated Timeline tab as well.

- **Alt+wheel** steps Editor zoom by one 25% preset and clamps at 100%/300%.
- **Ctrl+wheel** remains the independent vertical precision/timing zoom.

Changing Editor zoom scales the *current* row geometry and its vertical-zoom
bounds by the same ratio, so an existing Ctrl+wheel precision level is preserved
when switching between editor zoom presets.

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

## Manual validation

The 100% baseline and all eight additional presets were exercised on Windows
while implementing the gate. The validation covered:

1. notes, lane boundaries and timing rows remaining aligned;
2. mouse hit testing selecting the visibly targeted row/lane;
3. keyboard cursor and Shift-selection outlines remaining aligned;
4. cross-Block/Split selections across different Beat Splits;
5. waveform/playhead alignment;
6. Tap/Hold/Roll/Item/Division centering;
7. scrolling through the editable field;
8. `LM.NX` retaining exactly three scaled light lanes and matching selection
   bounds;
9. Toggle/Select/Cut/Copy/Paste/Delete targeting the intended Lightmap cells;
10. application chrome remaining unchanged while the field scales.

The Lightmap visual baseline for this gate is 80% alpha for an active light and
5% alpha for an inactive light. Lightmap selection uses the exact light rectangle
rather than the generic playable-chart cell outline.

## Automated gate

The item-5 regression suite verifies:

- the exact 100..300 preset sequence in 25% steps;
- proportional Timeline geometry at every new preset;
- preservation of existing Ctrl+wheel vertical magnification;
- row/lane hit testing at every preset;
- Timeline widget size remaining unchanged while internal field geometry grows;
- Lightmap light rectangles following the same scaled lane geometry;
- `Alt+wheel` changing exactly one preset at a time and respecting bounds;
- `Ctrl+wheel` not being intercepted by the Editor-zoom shortcut;
- `View` containing `Open gameplay preview…` before `Editor zoom`.

Final item-5 CI checkpoint, PR #24 / run 49:

- Windows: **610 tests in 6.240 s, OK**, with the one expected
  case-insensitive-filesystem skip;
- Linux/glibc 2.31: full suite, OK.

## Completion

Item 5 is closed. The editor-field zoom contract is now part of the 0.9.5
hardening baseline; application-wide DPI scaling remains a separate concern and
was never claimed by this gate.
