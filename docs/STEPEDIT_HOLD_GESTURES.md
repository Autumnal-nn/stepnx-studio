# M5: STEPEdit-style Hold gestures (experimental)

Status: opt-in Qt editor, stacked on PR #38. The normal Studio editor and
all existing codecs remain unchanged.

## Workflow

- Under **Toggle tap**, a same-lane drag between two **different** rows of
  the **same selected Block** creates a complete Hold as a single operation.
- The lowest index becomes 0x7 (head); the highest becomes 0xF (tail).
  All intervening rows become 0xB (body). Reversing the drag direction
  produces the same canonical result.
- The raw composer is the existing Studio `_regular_note_raw` with the
  active bank, function, visibility, source/player slot and Brain Shower
  context. Missing or nonmatching raw types are rejected.
- Every cell in the intended range must be exactly `00 00 00 00`.
  Existing taps, Holds, items, Divisions and opaque bytes prevent the edit.
- Clicking a cell belonging to a **complete** Hold removes the entire
  contiguous Hold span in one undo step. Incomplete Holds remain untouched
  and require explicit inspection.
- Mouse drag preview is read-only. Invalid release, Escape, focus loss,
  document switch and Block switch cannot commit a partial Hold.
- The authoring engine executes exactly one `SetNotesAt` through
  `EditorController.apply_note_batch`, retaining one undo boundary.
- **Paint taps** and **Erase cells** remain the existing M4 behavior:
  they are separate tools and refuse to cross existing Hold parts.

## Exclusions

The M5 slice does not edit Holds across Split boundaries, join neighboring
holds, resize a Split, infer malformed terminal topology, touch Lightmap,
or change the existing StepNX transport/audio-timing behavior.

Retain the normal editor for these operations until its semantics have
been extracted and validated. M5 is not a claim of complete STEPEdit
runtime parity or readiness for StepNX Studio 1.0.
