# StepNX Studio 1.0: STEPEdit-inspired viewport geometry

Status: opt-in pure geometry, no Qt connection yet (stacked after PR #35)
Evidence: static STEPEditor 5.63 Coxed/REA/Ghidra UI analysis of 2026-10-26.

## Source-derived conventions

- Hit-test regions: body (0), left indicator (1), properties (2), ground (3), terminal resize band (4).
- Indicator begins at x=0 and occupies about 31 logical pixels.
- The legacy note lanes use a 24-pixel horizontal pitch.
- Per-block row pitch is `48 × vertical_zoom / BeatSplit`, independently of BPM, audio offsets, and Scroll.
- Observed vertical zoom commands use 1, 2, 3, 4, 6, 8, 12, 16.
- Selecting a different alternative changes the displayed Block within one Split; it does not mutate encoded rows or timing.

This evidence describes the inspected binary; it is **not** proof of visual or click behavior in every running configuration. Notably, a STEPEdit display-width helper returns suspicious widths for Single and Half Double. StepNX therefore derives its view lane count from the canonical snapshot (3/5/6/10), not from that helper.

## Deliberate StepNX safety policies

- The module is only a projection. It never writes NX20.
- The existing `TimelineLayout` remains unchanged. Its fixed encoded-row height is an independent mode, not an error to be corrected globally.
- Hit targets carry **local** lanes; `source_lane` is exposed separately as `lane + start_column` for diagnostics.
- The bottom resize band is capped at 25% of the local row pitch. This keeps the center of even very dense last rows reachable and differs intentionally from blindly reserving 5 px.
- Subpixel rows may be impossible to select uniquely with physical-pixel mouse coordinates. The layout exposes `required_zoom_for_pixel_rows`; Qt must offer zoom/keyboard editing, not silently round BeatSplit or change row data.
- Mouse hit tests accept explicit scroll offsets, never reusing a hidden global last-pointer coordinate.
- Zoom anchoring operates on a concrete Split/row, independent of mouse hover. The Qt host will be responsible for setting the scroll bar while preserving the viewport anchor.
- Negative, zero or non-finite geometry/BeatSplit is rejected; it is not silently normalized.

## Next integration gate

Do not connect pointer events to `EditorController` until Qt integration:

1. Captures `EditorEventScope` at hit-test time and keeps a `StrokeLease` for exactly one gesture.
2. Transforms Qt client coordinates into this layout's logical coordinates consistently for notes, selections, overlays and split resize.
3. Uses the selected route only and never edits hidden alternatives.
4. Handles Escape, capture loss, tab/document switch and structural changes by cancelling gestures.
5. Runs performance/culling and DPI tests on Windows before replacing the existing Timeline.
6. Preserves existing Lightmap, timing, split cascade, Hold and special-note semantics through their current services.

The currently added pure-geometry tests do not claim runtime UI parity or perform a visual screenshot review.
