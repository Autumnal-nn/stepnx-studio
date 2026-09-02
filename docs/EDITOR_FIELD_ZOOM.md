# Editor field zoom

StepNX Studio 0.9.5 exposes a Timeline-only editor zoom independent from Windows display scaling and from the existing Ctrl+wheel vertical timing magnification.

The supported presets are 100%, 125%, 150%, 175%, 200%, 225%, 250%, 275% and 300%.

The top-level menu formerly named `Preview` is now `View`. `Open gameplay preview…` remains its first action and `Editor zoom` follows below it.

`Alt+wheel` moves exactly one editor-zoom preset per wheel step and clamps at 100% and 300%. `Ctrl+wheel` remains reserved for continuous vertical timing magnification, which is especially useful for dense Beat Split charts and waveform synchronization.

Editor zoom scales only Timeline/editor-field geometry: encoded-row spacing, lane width, ruler width, Block information gutter, footer, notes, Lightmap cells and all corresponding hit-test geometry. Application chrome, toolbars, Workspace, Inspector and dialogs are not scaled by this control.

Changing the preset preserves the current vertical magnification ratio and keeps the viewport anchored around its center rather than resetting to the top-left of the chart.
