# StepNX Studio 0.9.5 editor UX cleanup audit

Date: 2026-09-02

Status: implementation complete enough for focused Windows smoke; automated PR
CI has not yet run because item 6 intentionally has no pull request yet.

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

This preserves the specialized Timeline workflow without maintaining misleading
states or destructive wording drift.

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
document (`notes` versus `lightmap`) and a selection anchor exists. This removes
an avoidable click-then-error path.

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

The Tool control remains enabled because Toggle and Select are meaningful and the
existing blocked-tool behavior is intentional. Cut/Copy/Paste/Delete remain
available according to selection/clipboard state.

## Routes terminology

Routes no longer renders legacy selector wording and then patches strings in a
second pass. It renders directly from the canonical `SplitSelectionByte`
projection.

Consequently:

- `0x80` is `random at chart load`;
- raw `0x40` is `random at block start` because an unbanked follower lookup
  falls back to random;
- `0x41..0x5F` are `follower block, bank N`;
- the old UI terms `random trigger` and `group` are not generated.

## Inspector state

The Inspector now remembers the scope it is displaying. After a mutation to that
scope it refreshes automatically when the values visible in Inspector change.

The refresh signature includes:

- Header metadata/trailer envelope state;
- Split selector, Brain byte and Split metadata;
- Block timing/flags and Division metadata.

Row/note payloads are intentionally excluded from the signature so a fast note
gesture does not rebuild the Inspector table on every cell edit.

If a structural command removes the inspected Split/Block, Inspector is cleared
instead of displaying stale data. If the user is currently viewing Diagnostics
or Routes, an Inspector refresh does not steal the side-panel focus.

## Context-sensitive metadata actions

`Edit Division metadata…` is now disabled when its remembered Block belongs to a
chart that is no longer current or when that Block no longer exists. A valid
current metadata/tree context or currently inspected Block keeps it enabled.

`Edit chart scope / field…` follows the document selected in the Workspace tree,
matching the command's actual target-selection rules rather than merely looking
at the currently visible tab.

## Shortcut/help truth

F1 help now documents both independent Timeline zoom controls:

- Ctrl+wheel: vertical timing precision zoom;
- Shift+wheel: Editor field zoom in 25% preset steps.

`View > Editor zoom` advertises the same distinction in its tooltip.

The initial Alt+wheel binding was removed after real Windows use showed that Qt
could route it to native horizontal scrolling instead of StepNX. Exact
Shift+wheel is now intercepted only over the Timeline viewport; Ctrl+wheel is
left untouched for precision zoom and Alt+wheel is left to the platform.

## Destructive operations

The audit retained the existing guarded destructive flows:

- Remove Split names the Split-wide Block/note loss and requires confirmation;
- Remove Block names note loss and requires confirmation;
- chart-field shrink reports the exact number of non-empty cells that would be
  discarded;
- Delete NX names the file, states that the operation cannot be undone and is
  blocked for `LM.NX`;
- Save All still goes through validation and structural-diff preview.

The Timeline Remove Block affordance is disabled before invocation when the
last-Block invariant would reject it, and its confirmation now matches the
canonical Structure wording/buttons.

## Automated regressions

Item 6 adds 22 focused regressions over the item-5 610-test checkpoint. They
cover:

- direct Routes selector terminology;
- rectangular versus sparse selection summaries;
- Lightmap selection wording;
- note/Lightmap clipboard compatibility;
- canonical Workspace context-action reuse;
- Inspector target lifetime and refresh signatures;
- rectangle/Mirror action applicability;
- Timeline structure-menu enable states;
- chart-field target selection;
- stale Division-metadata context rejection;
- F1 zoom-help truth;
- Shift+wheel ownership with Ctrl/Alt left unintercepted;
- canonical Timeline Remove Block confirmation wording.

The strict Windows discovery floor is therefore **632 tests**.

## Focused manual smoke

Before item 6 is closed, verify on Windows:

1. Right-click a Workspace Split and Block. The menu text/state must match Edit >
   Structure and invoke the same operations.
2. Right-click `LM.NX` in Workspace. `Edit chart scope / field…`, Duplicate and
   Delete must be disabled.
3. On a Split with one Block, Timeline right-click > Block > Remove Block… must
   be disabled. On a multi-Block Split it must be enabled, and its confirmation
   must say `Remove Block` with Cancel as the safe default.
4. Make a rectangular multi-row selection and then a sparse Ctrl selection.
   Status text and Flip/Mirror enabled state must follow the actual shape.
5. Copy from a playable chart, switch to LM.NX and select a light cell. Paste
   must remain disabled; repeat in the opposite direction.
6. In LM.NX, Bank/ID, Function, Visibility and note-only advanced controls must
   be disabled while Tool remains available.
7. Inspect a Block, edit BPM/timing or Division metadata, and confirm Inspector
   refreshes without another click. Then remove the inspected Block and confirm
   Inspector clears.
8. Inspect a Block, switch to another chart, and verify Edit Division metadata…
   does not target the old chart.
9. Open Routes on charts using `0x40`, `0x41` and `0x80`; no `random trigger` or
   `group` terminology should remain.
10. Press F1 and confirm Ctrl+wheel and Shift+wheel are documented. Over the
    Timeline, Shift+wheel must step Editor zoom; Ctrl+wheel must retain vertical
    precision zoom; Alt+wheel must not be claimed by StepNX.

Any stale target, enabled impossible action, context menu that executes a
different command from its matching canonical action, or input shortcut whose
visible behavior contradicts Help is blocking for item 6.
