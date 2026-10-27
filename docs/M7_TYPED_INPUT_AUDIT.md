# M7 input migration inventory and pre-audit gate

Baseline: PR #41 on `agent/1.0-m7-typed-inputs` (stacked after M6).
This is a **source inventory and test plan**, not proof of runtime or corpus parity.

| Surface | Input | State | Audit requirement |
|---|---|---|---|
| `phase10_install.py` | Resize Split MBR | migrated | zero rows, shrink confirmation, last Split disabled, alternative Blocks and downstream timing |
| `stepedit_experimental_dialog.py` | experimental Resize Split MBR | migrated | same dialog and semantics as legacy timeline |
| `typed_inputs.py` | `MbrSpinRow`, `LabeledRangeRow`, DM120, U32 and bitmask | migrated | boundaries, cancellation, unknown bits, signed range, no silent coercion |
| `metadata_dialog.py` | packed range / DM120 / enums / bitmasks / raw U32 | mostly migrated | float32 bit-preservation, enum unknowns, signed 32-bit, patched profile, duplicate metadata |
| `phase12_split_header.py` | selection flags/bank, raw selector byte | **pending refinement** | replace raw `QLineEdit` with reusable validated byte editor; accept uncommon raw combinations (e.g. 0xC0) and keep the typed controls in sync |
| `timing_dialog.py` | BPM, scroll, beat split/measure, flags | typed already | test no-edit float-bit preservation and ensure min/max ranges cannot clamp loaded raw values |
| `phase10_install.py` | chart session offset and start time | typed already | preserve units, precision, and session-only semantics; monitor for clamping |
| `phase11_workspace.py` | chart geometry | typed already | geometry validation and chart creation |
| `phase11_workspace.py` | chart filename (create/duplicate) | legitimate text | filename/path validation, cancel without mutation |
| `phase11_trailer_edit.py` | UTF-8 text | legitimate text | preserve relocation/encoding guard and cancel/no-op |
| `phase11_import.py` | diagnostic text | read-only | ensure no editable numeric free text |
| `phase11_preferences.py` | existing preferences | inspect per-control | ensure persistence and no accidental profile conversion |
| `phase10_install.py` | tool type picker | `getItem` typed enum | unknown/raw tool value must not be silently replaced |
| `metadata_dialog.py` | metadata field picker | `getItem` typed enum | patched Custom raw ID only Header/Division; all uint32 IDs/values accepted |
| `stepedit_structure_actions.py` | planning only | no input | test current scope/row validation before execution |

## Explicit user requirements

- In `nxa-step5-patched`, any Header/Division metadata ID/value can be **authored** as raw uint32 even if undocumented or outside known semantic limits. This does **not** assert runtime support.
- Unknown patched Division metadata defaults to the low16/high16 Min/Max presentation, with raw override.
- Other profiles still preserve unknown bytes but retain their typed editing gates.
- No-op and cancel must not dirty the NX20 model.
- No new text parsing for composite numeric input. Preserve encoded strings as strings.

## Pre-audit test matrix

1. Qt offscreen: instantiate all edited dialogs; every boundary, invalid edit and cancel.
2. NX20: untouched parse/serialize byte exact; unchanged metadata preserves original raw scalar spans and duplicate order.
3. Patched Header/Division: `0`, `0xFFFFFFFF`, unknown ID, unknown Division min/max, abnormal DM120, out-of-range recognized values.
4. Split: 1 block, multiple alternatives, arbitrary BeatSplit/BeatMeasure, shrink/grow, cancellation and destructive confirmation, downstream timing shifts.
5. Raw selector: `0x00`, `0x40`, `0x80`, `0xC0`, `0xFF`; warn but preserve combinations.
6. Performance: no whole-chart materialization for small UI edits; 50/500/5000-cell selection gates.
7. Imports: STX/SEE Half Double regression, NX10 materialization, NX20 unknown metadata, audio timing fixtures.
8. Windows CI and Linux CI must both complete successfully at the *same head commit*.
9. Manual Qt interactive smoke: legacy Timeline, experimental STEPEdit viewport, dialog keyboard navigation and save/undo.

## Outstanding risks

- Existing `QDoubleSpinBox` editors use finite decimal precision and may rewrite a raw float32 payload on acceptance. Verify bitwise no-op behavior, not approximate numeric equality.
- `QSpinBox` is signed 32-bit, so raw unsigned IDs/values must use the dedicated full-range editor.
- The experimental STEPEdit viewport formerly used a second MBR text prompt. This PR now routes it through `ResizeSplitDialog`.
- Bitmask checkboxes must not normalize unknown or multi-bit flags.
- Several CI runs were still in progress during the inventory. Do not claim the M7 gate has passed until a completed run is inspected.

## Completion

M7 is ready for a **code/behavior audit** only after pending selector/float work is addressed, all targeted tests pass, and the full CI results are reviewed. Merge order remains M1→M7.
