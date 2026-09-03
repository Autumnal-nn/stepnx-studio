# StepNX Studio 0.9.5 editor UX cleanup audit

Date: 2026-09-02

Status: complete; automated gate green and focused Windows GUI smoke passed.

## Purpose

Item 6 is a consistency audit, not a visual redesign. The goal is to remove
places where the UI advertises an operation that cannot run, duplicates the same
operation with different state/text, shows stale model data, or hides useful
selection context.

The existing command/undo/validation architecture remains authoritative. UX
cleanup must reuse it rather than inventing alternate mutation paths.

## Context menus

### Workspace tree

Split, Block and Header context menus now reuse the same canonical `QAction`
objects exposed by the Edit menu. This means text, shortcut, enabled state and
handler cannot drift between the two surfaces.

Split context:

- Insert empty Split after;
- Remove Split…;
- Move Split up/down;
- Edit Split selection….

Block context:

- Insert empty Block after;
- Remove Block…;
- Move Block up/down;
- Edit Block timing…;
- Edit Split selection…;
- Edit Division metadata….

Header context reuses the canonical metadata action.

Document context keeps its file-specific Open/Duplicate/Delete commands, but
reuses the canonical chart-field action. `LM.NX` therefore presents the field
action disabled instead of accepting a click and explaining afterwards that its
three-channel Lightmap field is fixed.

### Timeline

The Timeline right-click menu is intentionally *not* collapsed into Edit >
Structure. Its Split Here, Merge Splits, Resize Split and Duplicate Block
commands have specialized row/viewport semantics.

The overlapping operations were normalized where their meaning is actually the
same:

- `Create Block after` -> `Insert empty Block after`;
- `Delete Block…` -> `Remove Block…`;
- Remove Block is disabled when the Split contains only one Block;
- Merge Splits is disabled on the final Split;
- Split Here is disabled at the first row.

Timeline Remove Block now uses the same `Remove Block` title, explanatory text,
Yes/Cancel buttons and default Cancel behavior as the canonical Structure
operation. The specialized viewport entry point still executes the same
`remove_block` command and ordinary undo/document-refresh path.

## Selection feedback and action state

Multi-cell selection status now reports the actual selection topology rather
than only a cell count. Examples:

- `4 cells selected · 2 rows × 2 lanes · across 2 Blocks`;
- `2 cells selected · 2 rows · 2 lanes · across 2 Blocks` for sparse Ctrl
  selections;
- `3 light cells selected · 1 row × 3 lanes` for Lightmap.

A single playable cell keeps the existing detailed raw/note status. A single
Lightmap cell now has explicit feedback instead of collapsing to `Ready`.

Transform actions are enabled only when their selection shape is applicable:

- horizontal/vertical Flip require a complete rectangle;
- StepEdit Mirror additionally requires a supported Single/Half Double/Double
  lane shape;
- playable transforms remain disabled for Lightmap.

Paste is enabled only when the current clipboard kind matches the active
document (`notes` versus `lightmap`) and a selection anchor exists.

## Lightmap control state

When `LM.NX` is active, controls that are deliberately ignored by Lightmap edits
are visibly disabled:

- Bank / ID;
- Function;
- Visibility;
- Brain Code;
- Special/advanced note controls;
- Apply flags;
- note transforms and Replace note type.

The Tool control remains enabled because Toggle and Select are meaningful.
Cut/Copy/Paste/Delete remain available according to selection/clipboard state.

## Routes terminology

Routes now renders directly from the canonical `SplitSelectionByte` projection:

- `0x80` is `random at chart load`;
- raw `0x40` is `random at block start` because an unbanked follower lookup
  falls back to random;
- `0x41..0x5F` are `follower block, bank N`;
- the old UI terms `random trigger` and `group` are not generated.

## Inspector state

The Inspector remembers the scope it is displaying. After a mutation it refreshes
when values visible in Inspector change. The refresh signature includes Header
metadata/trailer envelope state, Split selector/Brain/metadata, and Block
timing/flags/Division metadata.

Row/note payloads are intentionally excluded so fast note gestures do not rebuild
the Inspector table on every cell edit. If a structural command removes the
inspected Split/Block, Inspector clears. If the user is viewing Diagnostics or
Routes, an Inspector refresh does not steal side-panel focus.

## Context-sensitive metadata actions

`Edit Division metadata…` is disabled when its remembered Block belongs to a
chart that is no longer current or when that Block no longer exists.

`Edit chart scope / field…` follows the document selected in the Workspace tree,
matching the command's actual target-selection rules.

## Shortcut/help truth

F1 help and `View > Editor zoom` now document the independent Timeline zooms:

- Ctrl+wheel: vertical timing precision zoom;
- Shift+wheel: Editor field zoom in 25% preset steps.

The initial Alt+wheel binding was removed after real Windows use showed that Qt
could route it to native horizontal scrolling. Exact Shift+wheel is intercepted
only over the Timeline viewport. The handler accepts either vertical or
platform-horizontalized Shift-wheel delta, so Qt converting Shift-wheel into a
horizontal wheel event cannot steal the Editor-zoom operation. Ctrl+wheel is
left untouched for precision zoom and Alt+wheel is left to the platform.

## Destructive operations

The existing guarded destructive flows remain. Remove Split and Remove Block
name the structural/note loss and require confirmation; chart-field shrink
reports the exact count of discarded non-empty cells; Delete NX names the file,
states that it cannot be undone and is blocked for `LM.NX`; Save All still uses
validation and structural-diff preview.

Timeline Remove Block is disabled before invocation when the last-Block invariant
would reject it, and its confirmation matches the canonical Structure wording.

## Automated regressions and final checkpoint

Item 6 adds 22 focused regressions over the item-5 610-test checkpoint. They
cover Routes terminology, selection topology, Lightmap wording and clipboard
compatibility, canonical Workspace action reuse, Inspector lifetime/signatures,
Flip/Mirror applicability, Timeline menu state, chart-field targeting, stale
Division context, F1/zoom truth, Shift-wheel ownership including horizontalized
delivery, and Timeline Remove Block wording.

The strict Windows discovery floor is **632 tests**.

Final automated checkpoint on functional/test head
`7a5dcbe9eb3f8e5f33430f4effc4213b9114bf70`:

- Windows: **632 tests in 7.190 s, OK**, with the one expected
  case-insensitive-filesystem skip;
- Linux/glibc 2.31: **632 tests in 5.253 s, OK**.

CI was enabled temporarily for direct pushes to the item-6 branch solely to run
this gate without creating a pull request. The workflow was restored afterwards
to its normal `pull_request` plus `push: main` policy.

## Focused manual smoke

The focused Windows smoke passed. The validation covered:

1. Workspace Split/Block context menus matching the canonical Edit > Structure
   actions and state.
2. `LM.NX` chart-field/Duplicate/Delete state and note-only control disabling.
3. Timeline Remove Block state for single- versus multi-Block Splits, including
   canonical wording and Cancel as the safe default.
4. Rectangular versus sparse Ctrl selection feedback and Flip/Mirror
   applicability.
5. Playable-chart versus Lightmap clipboard incompatibility in both directions.
6. Lightmap Tool availability with Bank/ID, Function, Visibility and advanced
   note controls disabled.
7. Inspector refresh after timing/Division edits and clearing after structural
   removal.
8. Stale Division-metadata target rejection after switching charts.
9. Routes wording for `0x40`, `0x41` and `0x80` without legacy `random trigger`
   or `group` labels.
10. F1 shortcut truth plus Shift+wheel Editor zoom on a Timeline where horizontal
    scrolling was available, while Ctrl+wheel retained precision zoom and
    Alt+wheel remained unclaimed by StepNX.

Result: **PASS**. Item 6 is closed and the six-item 0.9.5 hardening cycle is
complete.