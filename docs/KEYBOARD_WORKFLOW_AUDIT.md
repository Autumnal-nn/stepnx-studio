# Keyboard workflow audit

Date: 2026-09-02

Target: StepNX Studio 0.9.5 hardening item 4

Status: implementation complete on `hardening-0.9.5-keyboard-workflow`; pull-request CI validation pending.

## Goal

The audit is not a count of shortcuts. Its release criterion is that an author can
perform the frequent chart-editing loop without reaching for the mouse:

1. choose/open a chart;
2. move through the note grid;
3. select one cell or a rectangle;
4. choose a placement/function mode;
5. place, erase, copy, paste, or transform notes;
6. inspect and edit Split/Block structure and metadata;
7. switch charts and side panes;
8. start playback or open the gameplay preview;
9. save the workspace.

The implementation also treats shortcut **scope** as part of correctness. A key
that means "Mirror" in the chart must not unexpectedly fire while the user is
editing another widget.

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

## Context rule

Keyboard behavior is now split into explicit contexts.

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
| `Ctrl+PageUp` / `Ctrl+PageDown` | Previous / next open chart tab |
| `Alt+1` | Focus Workspace tree |
| `Alt+2` | Focus active Timeline |
| `Alt+3` | Focus Inspector |
| `Alt+4` | Focus Diagnostics |
| `Alt+5` | Focus Routes |
| `F1` | Show the keyboard shortcut map |

### Timeline-only commands

The following keys are handled by the authoring timeline itself. Their old
window-level `QAction` shortcuts are cleared, so they do not steal input from
other controls.

#### Cursor and selection

| Keys | Command |
| --- | --- |
| Arrow keys | Move by row/lane |
| `Shift` + Arrow | Extend a rectangular selection |
| `Home` / `End` | First / last lane |
| `Ctrl+Home` / `Ctrl+End` | First / last row of the current Block |
| `Ctrl+Up` / `Ctrl+Down` | Previous / next non-empty timeline segment |
| `Esc` | Clear selection |

Rectangular selections remain intentionally Block-local. When a Shift movement
crosses a Block boundary, the destination becomes a fresh cursor/anchor rather
than inventing a cross-Block rectangle that the authoring command model does not
support.

The cursor uses stable row IDs directly. For `CompactRows` and `OverlayRows`, it
reuses the source-backed row-ID table and binary-search helpers; keyboard
navigation does not decode or iterate the complete Block.

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

`Enter` applies the current tool to the current selection. For one selected cell
with Toggle active, Enter deliberately follows the same Toggle path as a mouse
click, so an existing note is erased instead of being blindly overwritten.

#### Bulk editing and transport

| Keys | Command |
| --- | --- |
| `Delete` / `Backspace` | Erase selected notes |
| `Ctrl+C` | Copy |
| `Ctrl+X` | Cut |
| `Ctrl+V` | Paste |
| `X` | Flip horizontal |
| `Y` | Flip vertical |
| `M` | StepEdit-compatible Mirror |
| `Space` | Play / pause |

Space is no longer an application/window shortcut. The old Phase-10 shortcut is
disabled and Space is consumed by the Timeline only. This prevents playback from
stealing Space while another editor control owns focus.

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

The keyboard hardening branch adds 13 dedicated tests over the 573-test
save/recovery checkpoint, raising the intended strict Windows discovery floor to
586.

Coverage includes:

- stable arrow navigation and Shift rectangle extension;
- Home/End and Ctrl navigation boundaries;
- direct timeline key-event navigation without mouse input;
- a guard that rejects complete `CompactRows` iteration during keyboard
  selection movement;
- numeric tool selection;
- H/G/N function selection;
- removal of chart-edit shortcuts from window scope;
- removal of the old application-wide Space shortcut;
- standard `Ctrl+S` plus retained `Ctrl+Shift+S` Save All shortcuts;
- pane and chart-tab focus shortcuts;
- Workspace-tree activation, metadata access, and structural-key dispatch;
- Routes activation with Enter;
- F1 Help-menu discoverability.

The branch does not currently receive CI on ordinary pushes: `.github/workflows/ci.yml`
runs for pull requests and pushes to `main`. Therefore the 586-test floor is an
**intended gate, not yet a recorded Windows/Linux validation checkpoint**. The
existing last confirmed checkpoint remains the item-3 result of 573 passing tests
on both platforms until this branch is exercised by pull-request CI.

## Deliberate boundaries

- Cross-Block rectangular note selections remain unsupported; keyboard behavior
  does not weaken that invariant.
- Structural row insertion/removal remains the existing structural command path;
  the keyboard layer only dispatches existing actions.
- Diagnostics currently gain focus navigation but not a new keyboard
  click-through action. Click-through diagnostics belong to later UX work if
  implemented.
- The audit does not redefine gameplay-preview runtime keys.
- Accessibility beyond keyboard reachability, such as screen-reader labeling,
  remains separate from this 0.9.5 keyboard pass.
