# STEPEdit experimental: context-menu structural editing (M6)

This surface is opt-in and runs in a modal session on the same CommandStack
as the existing StepNX Studio interface. Right-click a displayed Split's
grid, indicator, or properties gutter to open the context menu.

## Available context actions

| Action | Semantics |
| --- | --- |
| Split here | Uses the existing multi-Block-aware `_SplitHereCommand` at the selected row (not row zero), preserving alternative Block splits at matching musical positions. |
| Insert empty Split after | Uses `insert_empty_split_after` and explicitly warns that the new one-row Split inherits timing fields; review its Start Time. |
| Resize Split | Requests Measure / Beat / Row. Uses `resize_split_boundary_cascade_document`: all alternatives are resized proportionally to their BeatSplit, and **all downstream Blocks in all Splits** shift by one identical time delta. No resize of the final Split. |
| Merge with next Split | Uses the existing `_MergeSplitsCommand` with a destructive confirmation detailing possible loss of lower Block variants and separate timing. |
| Delete Split | Uses `remove_split`; disabled when it is the sole remaining Split, and requires confirmation. |
| Insert empty Block | Creates a blank alternative of the same row count as the selected Block, retaining timing context. |
| Duplicate Block | Duplicates the selected Block as a distinct alternative with freshly allocated IDs. |
| Delete Block | Removes one alternative, disabled when it is the only Block, and requires confirmation. |
| Previous / Next Block | Switches the authoring projection only, without changing chart data. |

## Safety properties

- Every right-click captures a fresh `EditorEventScope`; after the nested
  context menu or confirmation dialog returns, stale scopes are rejected.
- An operation commits through the existing domain CommandStack and
  `EditorController.execute` as **one undoable edit**. No direct disk writes.
- Resize truncation is explicitly confirmed, with a count of discarded
  nonzero note cells in all alternatives.
- Adding a placeholder Split warns about inherited timing. Do not infer
  matching gameplay timestamps solely from the stacked viewport geometry.
- Split merges may discard lower timing or extra branches; they require
  explicit approval.
- After a successful edit, the viewport geometry/route selectors refresh,
  the transient note selection clears, and the normal Save All pipeline
  receives the modified document when the modal editor closes.

Manual Windows testing remains mandatory for high-DPI hit-testing, confirmation
flows, large charts, keyboard focus, and Save All. The new surface is not yet
a default StepNX Studio editor.
