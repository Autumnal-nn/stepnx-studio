# StepNX Studio 0.9.5 high-DPI/scaling gate

Date: 2026-09-02

Status: planned 0.9.5 hardening item 5; starts after item 4 manual keyboard/Lightmap re-smoke closes successfully.

## Scope

Validate the desktop editor at every 25% Windows display-scaling increment from
100% through 300% inclusive:

- 100%
- 125%
- 150%
- 175%
- 200%
- 225%
- 250%
- 275%
- 300%

Scaling above 300% is outside the 0.9.5 gate unless a defect found inside the
gated range clearly indicates the same root cause would continue upward.

The gate is not a screenshot-comparison exercise. It verifies that authoring
semantics, hit testing, layout, rendering and external-preview behavior remain
usable and internally consistent at each supported scale.

## Validation areas

At every scale, exercise at least the following surfaces:

1. **Main-window composition**
   - menu bar, both toolbars and status bar remain readable;
   - toolbar controls do not overlap or become inaccessible;
   - splitters, Workspace tree and side tabs remain usable at ordinary window
     sizes;
   - no important label is clipped solely because of scaling.

2. **Timeline geometry and input**
   - timing lines, lanes, notes and selection outlines remain aligned;
   - mouse hit testing resolves the visibly targeted row/lane;
   - keyboard cursor/selection remains aligned with the same cells;
   - cross-Block/Split selection outlines remain coherent across changes in
     Beat Split/timing density;
   - the three `LM.NX` light lanes remain aligned with their corresponding
     clickable/selectable cells;
   - Ctrl-wheel zoom does not introduce scale-dependent drift;
   - scrollbars can still reach the first and final editable timing positions.

3. **Note and noteskin rendering**
   - Tap, Hold, Roll, Item and Division visuals remain centered;
   - hold heads/bodies/tails remain continuous enough for editing;
   - glyphs and noteskin atlases do not acquire obvious integer-scaling seams,
     clipping or misplaced source rectangles;
   - selection and drag-preview artwork tracks the underlying note geometry.

4. **Dialogs and typed editors**
   - Block timing, metadata, Split selector, trailer and other authoring dialogs
     fit their controls without hidden fields;
   - standard keyboard traversal and OK/Cancel controls remain reachable;
   - warnings and explanatory labels wrap rather than disappear horizontally.

5. **Inspector, Diagnostics and Routes**
   - table/tree headers and contents remain legible;
   - row heights do not clip text;
   - horizontal scrolling, where genuinely required, remains possible;
   - double-click/Enter activation targets the visible row.

6. **Split/Block structure affordances**
   - gutter summaries remain readable;
   - context menus open at sensible positions;
   - tree selection and structure editing target the intended Split/Block.

7. **Audio and waveform UI**
   - transport controls remain accessible;
   - waveform stays aligned to timing positions;
   - playhead/follow behavior does not shift relative to chart geometry.

8. **External gameplay preview**
   - the preview opens on the intended screen and remains independently usable;
   - playfield/receptors scale without clipping or geometry drift;
   - keyboard/pad input remains mapped correctly;
   - F6 debug text remains readable and contained within the preview;
   - editor/preview synchronization remains correct after moving either window
     between displays with different scale factors when such a setup is
     available.

## Required outcomes

A scale passes when:

- no crash, assertion or Qt warning indicates broken scaling behavior;
- all authoring targets remain reachable by mouse and keyboard;
- visible note/Lightmap/timing geometry agrees with hit testing;
- dialogs do not hide required controls;
- no destructive action can be accidentally targeted because visual and input
  geometry diverged;
- the external preview remains usable and synchronized;
- any cosmetic degradation is recorded and classified rather than silently
  accepted.

Defects that reproduce at one or more gated scales are part of item 5 even when
they also happen at 100%. The goal is to validate scaling as a system, not merely
to special-case high percentages.

## Automation strategy

Where Qt permits deterministic offscreen assertions, add regression tests for
logical geometry, size hints, hit targets and layout constraints at representative
scale factors. Pixel-perfect screenshots are not a release requirement because
font rasterization and platform theme details vary across environments.

Manual Windows validation remains required for the complete 100%..300% matrix,
including real OS display scaling and at least one packaged-build smoke pass.

## Completion criterion

Item 5 is complete when all nine scale points have been exercised, every
blocking defect found in the matrix has been fixed or explicitly deferred with a
non-blocking rationale, automated regressions cover reproducible logical bugs,
and the final validation record identifies the Windows/Qt environment used.
