# Keyboard workflow audit

Date: 2026-09-02

Target: StepNX Studio 0.9.5 hardening item 4

Status: implementation and automated regression gate are complete on
`hardening-0.9.5-keyboard-workflow`; manual Windows re-smoke is still required
before the item is closed.

## Goal

The audit is not a count of shortcuts. Its release criterion is that an author can
perform the frequent editing loop without reaching for the mouse:

1. choose/open a chart or Lightmap;
2. move through the grid;
3. select one cell or a rectangle, including across visible Block/Split
   boundaries;
4. choose an applicable placement/function mode;
5. place, erase, copy, paste, or transform cells;
6. inspect and edit Split/Block structure and metadata;
7. switch charts and side panes;
8. start playback or open the gameplay preview;
9. save the workspace.

Shortcut **scope** is part of correctness. A key that means "Mirror" in the
Timeline must not unexpectedly fire while the user is editing another widget.

## Pre-audit findings

The editor already had useful action shortcuts, including Undo/Redo, selection
transforms, import, audio selection, Save All, gameplay preview, and Space for
playback. However, three structural gaps prevented a dependable keyboard-only
workflow:

1. `TimelineWidget` had strong focus but no authoring `keyPressEvent`, so cell
   navigation and selection still required the mouse.
2. note-selection shortcuts were attached to `QMainWindow` actions. This made
   single-letter `X`, `Y`, and `M`, plus editing keys such as Delete and
   Ctrl+C/X/V, eligible outside the note grid.
3. the Phase-10 Space shortcut used `ApplicationShortcut`, which was broader
   than the authoring context and could compete with ordinary controls.

The Workspace and Routes trees also depended primarily on double-click for
activation and exposed no compact keyboard vocabulary for structural edits.

## Manual-smoke findings and corrections

The first 586-test implementation checkpoint passed Windows and Linux CI, but
manual Windows use found four behavior errors that offscreen tests had not
captured adequately:

1. repeated `Shift+Arrow` movements recomputed from the fixed selection anchor,
   so the rectangle stopped growing after the second cell and then changed axis
   from the original anchor;
2. selection was artificially Block-local even though authoring operations are
   naturally defined by encoded row count across the active Timeline route;
3. `Enter` with Toggle selected fell through the generic bulk-placement path and
   behaved as Tap instead of toggling existing cells;
4. StepNX added `Ctrl+PageUp/PageDown` tab shortcuts even though Qt's existing
   `Ctrl+Tab` / `Ctrl+Shift+Tab` behavior already supplies the desired complete
   tab workflow.

The corrected implementation keeps the immutable selection anchor as the
rectangle origin but separately tracks the moving keyboard edge. It also
introduces a flattened **visible-row order** over the active Timeline route.
Cross-Block operations use that order directly: four encoded rows in one Block
plus eight encoded rows in the next are twelve rows regardless of Beat Split,
BPM, tick density, or elapsed time.

The manual audit also identified a previously missing authoring category:
`LM.NX`. Lightmap authoring is now implemented with three logical lanes, Toggle
and Select semantics, and lossless preservation of the fourth raw row byte. See
`LIGHTMAP_AUTHORING.md` for the corpus evidence and binary contract.

## Context rule

Keyboard behavior is split into explicit contexts.

### Window-level commands

These remain available across the main editor window because they are genuinely
workspace/application operations:

| Keys | Command |
| --- | --- |
| `Ctrl+O` | Open folder |
| `Ctrl+W` | Close folder |
| `Ctrl+I` | Import charts |
| `Ctrl+S` | Save All |
| `Ctrl+Shift+S` | Save All, retained legacy shortcut |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo |
| `Ctrl+Shift+P` | Open gameplay preview |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Next / previous chart tab, native Qt behavior |
| `Alt+1` | Focus Workspace tree |
| `Alt+2` | Focus active Timeline |
| `Alt+3` | Focus Inspector |
| `Alt+4` | Focus Diagnostics |
| `Alt+5` | Focus Routes |
| `F1` | Show the keyboard shortcut map |

StepNX deliberately does **not** install `Ctrl+PageUp/PageDown` for chart tabs.
The native tab-widget `Ctrl+Tab` behavior is retained rather than shadowed with a
second mapping.

### Timeline-only commands

The following keys are handled by the authoring Timeline itself. Their old
window-level `QAction` shortcuts are cleared, so they do not steal input from
other controls.

#### Cursor and selection

| Keys | Command |
| --- | --- |
| Arrow keys | Move by encoded row/lane |
| `Shift` + Arrow | Extend a rectangular selection across visible Blocks/Splits |
| `Home` / `End` | First / last lane |
| `Ctrl+Home` / `Ctrl+End` | First / last row of the current Block |
| `Ctrl+Up` / `Ctrl+Down` | Previous / next non-empty Timeline segment |
| `Esc` | Clear selection |

The selection anchor remains fixed while repeated Shift movement advances a
separate moving edge. Therefore `Shift+Right`, `Shift+Right`, `Shift+Down` from a
single cell produces a 2-by-3 rectangle rather than repeatedly recomputing a
one-step rectangle from the anchor.

Rectangular selections may cross visible Block and Split boundaries. The row
axis is the ordered sequence of encoded rows on the active Timeline route. It is
not normalized by musical timing. For example, selecting four rows in a
Beat-Split-4 Block and eight rows in a Beat-Split-32 Block selects twelve rows,
and Cut/Copy/Paste/vertical transform semantics operate on those twelve row
positions.

Only the currently visible/active route participates. Alternate branch Blocks
that are not projected into the Timeline are not silently included.

For `CompactRows` and `OverlayRows`, stable row IDs are read from indexed backing
storage. Keyboard selection and cross-Block range construction do not decode or
iterate complete source-backed row tables.

#### Placement state

| Keys | Command |
| --- | --- |
| `1` | Toggle |
| `2` | Select |
| `3` | Roll |
| `4` | Tap |
| `5` | Hold head |
| `6` | Hold body |
| `7` | Hold tail |
| `8` | Item |
| `9` | Division |
| `0` | Erase |
| `N` | Normal note function |
| `H` | Bonus / Hidden function |
| `G` | Ghost function |
| `T` | Focus Tool control |
| `B` | Focus Bank / ID control |
| `F` | Focus Function control |
| `V` | Focus Visibility control |

`Enter` applies the current tool to the current selection. Toggle is a real
toggle path for both single and multiple selected cells: empty playable cells
receive the current Tap encoding; occupied cells are erased; existing long-note
components retain the established whole-hold erase behavior. The entire
selection is one atomic command/undo step rather than a series of Tap rewrites.

#### Bulk editing and transport

| Keys | Command |
| --- | --- |
| `Delete` / `Backspace` | Erase selected cells |
| `Ctrl+C` | Copy |
| `Ctrl+X` | Cut |
| `Ctrl+V` | Paste |
| `X` | Flip horizontal, playable charts |
| `Y` | Flip vertical, playable charts |
| `M` | StepEdit-compatible Mirror, playable charts |
| `Space` | Play / pause |

Copy, Cut, Paste and playable-chart transforms use the active visible-row order
and can cross Block/Split boundaries. Clipboard height is encoded-row count, not
tickcount. Vertical flip reverses that row sequence even when adjacent Blocks
have different timing densities.

Space is no longer an application/window shortcut. The old Phase-10 shortcut is
disabled and Space is consumed by the Timeline only. This prevents playback from
stealing Space while another editor control owns focus.

## Lightmap workflow

`LM.NX` remains a native NX20 document but is not a playable chart. Its authoring
surface has exactly three lanes, aligned to the first three raw bytes of each
Lightmap row.

Only two tools have Lightmap meaning:

| Tool | Lightmap behavior |
| --- | --- |
| Toggle | Toggle the selected light channel for that row between off and on |
| Select | Change selection only; supports Ctrl/Shift multi-selection |

A Lightmap Select supports Cut, Copy, Paste and Delete. Those operations can
cross visible Block/Split boundaries by encoded row count. Lightmap clipboard
cells carry one raw channel byte and are deliberately incompatible with
four-byte playable-note clipboard cells.

Other placement tools remain rejected as non-chart operations. Playable-note
controls such as Bank/ID, Function, Visibility, Brain Code and Source Slot have
no effect on Lightmap Toggle/Select behavior. Horizontal/vertical note flips and
StepEdit Mirror are not Lightmap operations.

The fourth raw Lightmap byte has no editable lane. Corpus inspection found it
always zero in 2,896,556 supplied NXA/Fiesta-2/Prime-2 Lightmap rows, while the
first three bytes are binary `00`/`01`. StepNX nevertheless preserves byte 3
verbatim instead of assigning an unproven meaning or normalizing it.

## Workspace-tree workflow

With `Alt+1`, the Workspace tree becomes the structural keyboard surface.
Ordinary tree arrows continue to perform navigation; StepNX adds the following
commands:

| Keys | Command |
| --- | --- |
| `Enter` | Open / inspect selected document, Split, or Block |
| `Ctrl+Enter` | Edit metadata for Header, Split, or Block scope |
| `Alt+Enter` on Block | Edit Block timing |
| `Alt+Enter` on Split | Edit Split selection byte |
| `Alt+Enter` on Header | Edit Header metadata |
| `Insert` | Insert Block after selected Block |
| `Shift+Insert` | Insert Split after current structural selection |
| `Ctrl+Delete` | Remove Block |
| `Ctrl+Shift+Delete` | Remove Split |
| `Ctrl+Up` / `Ctrl+Down` | Move Block |
| `Ctrl+Shift+Up` / `Ctrl+Shift+Down` | Move Split |

The destructive and reorder keys are handled only while the Workspace tree owns
focus and still pass through the existing action-enabled state. The audit does
not introduce a second structural command path.

## Routes and preview

`Alt+5` focuses Routes and `Enter` activates the selected route/branch, matching
mouse activation.

The main-window `Ctrl+Shift+P` preview shortcut is retained. Once the external
gameplay preview owns focus, its existing runtime keyboard controls remain
independent from the authoring map. This audit does not remap PIUTESTER-style
preview controls.

## Discoverability

`F1` opens **Help > Keyboard shortcuts…**, which contains the compact current
map. The shortcut list lives beside the implementation so the user-facing map
and the installed behavior can be reviewed together.

## Regression coverage

The initial keyboard audit added thirteen tests over the 573-test save/recovery
checkpoint, producing a 586-test first CI checkpoint. Manual smoke testing then
found the issues above, and eleven targeted regressions were added for the
corrected behavior and Lightmap authoring. The strict discovery floor is now
**597 tests**.

The new/manual-smoke regressions explicitly cover:

- repeated Shift movement keeping a moving rectangle edge;
- Shift selection crossing a segment boundary by encoded row count;
- the concrete four-row plus eight-row equals twelve-row cross-Block case with
  different Beat Splits;
- cross-Split paste;
- cross-Split vertical flip;
- Enter Toggle dispatching the true toggle path rather than generic Tap
  placement;
- absence of custom `Ctrl+PageUp/PageDown` pane shortcuts;
- Lightmap fourth-byte preservation;
- sparse one-cell editing on a 20,000-row Lightmap with full CompactRows
  iteration forbidden;
- three-lane Lightmap rendering;
- Lightmap Toggle/Copy/Delete/Paste semantics;
- Lightmap/playable-chart clipboard type separation.

The corrected code checkpoint passed repository CI:

- Linux/glibc 2.31: **597 tests in 4.950 s, OK**;
- Windows: **597 tests in 7.161 s, OK**, with the one expected
  case-insensitive-filesystem skip.

The PR remains Draft until the corrected behaviors receive a real Windows manual
re-smoke. Later documentation-only commits are still required to pass the same
597-test PR CI before item 4 can close.

## Deliberate boundaries

- Cross-Block selection follows the active projected Timeline route only; hidden
  alternate route Blocks are not folded into one selection.
- Structural row insertion/removal remains the existing structural command path;
  the keyboard layer only dispatches existing actions.
- Lightmap authoring exposes exactly the three corpus-supported light channels;
  the fourth raw byte is preserved but not editable.
- Diagnostics currently gain focus navigation but not a new keyboard
  click-through action. Click-through diagnostics belong to later UX work if
  implemented.
- The audit does not redefine gameplay-preview runtime keys.
- Accessibility beyond keyboard reachability, such as screen-reader labeling,
  remains separate from this 0.9.5 keyboard pass.
