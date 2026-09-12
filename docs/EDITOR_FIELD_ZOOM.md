# Editor field zoom

StepNX Studio exposes a Timeline-only editor zoom independent from Windows display scaling and from the existing Ctrl+wheel vertical timing magnification.

The supported editor-field presets are 100%, 125%, 150%, 175%, 200%, 225%, 250%, 275% and 300%.

The top-level menu formerly named `Preview` is now `View`. `Open gameplay preview…` remains its first action and `Editor zoom` follows below it.

`Shift+wheel` moves exactly one editor-zoom preset per wheel step and clamps at 100% and 300%. `Ctrl+wheel` remains reserved for continuous vertical timing magnification, which is especially useful for dense Beat Split charts and waveform synchronization.

Starting with 0.9.6, interactive Ctrl+wheel zoom stops at 12 pixels per encoded row. The older 4-pixel extreme could place a very large portion of a chart in one viewport and overload rendering without providing useful authoring detail. Four-pixel geometry remains representable internally for projection/tests; only the interactive zoom path is clamped. Maximum timing-precision zoom remains unchanged.

Editor zoom scales only Timeline/editor-field geometry: encoded-row spacing, lane width, ruler width, Block information gutter, footer, notes, Lightmap cells and all corresponding hit-test geometry. Application chrome, toolbars, Workspace, Inspector and dialogs are not scaled by this control.

Changing the preset preserves the current vertical magnification ratio and keeps the viewport anchored around its center rather than resetting to the top-left of the chart.
