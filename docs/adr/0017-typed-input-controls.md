# ADR 0017: Typed controls for every editable field

Status: **Accepted for the StepNX Studio 1.0 UX migration**  
Baseline: `main` at `9b75a27` (0.9.6b).

## Decision

All editable fields in Studio must expose input widgets appropriate to their *semantic type*. Free-form text fields must be used only for genuine text (names, paths, encoded strings, condition expressions that are intentionally textual). Do not require a user to encode a structured value as `74|1|2`, `0..500`, or `1/-2`.

| Semantic input | Required control | Fidelity rule |
|---|---|---|
| Signed/unsigned integer | bounded spin box with explicit signedness | distinguish raw uint32 and signed int32 interpretation |
| Floating-point number | bounded, precision-aware double spin box | do not rewrite untouched raw float bits; explicitly warn when editing changes bit representation |
| Enum | non-editable combo box | preserve unknown raw enum values and offer raw mode |
| Bit flags | named checkboxes plus raw override | preserve undocumented bits; toggling a known bit must not clear unknown bits |
| Packed min/max | two integer spin boxes | pack/unpack without reinterpreting signedness; never silently reorder endpoints |
| DM120 mode/weight | enum or mode spin + signed weight spin | preserve signed weight semantics and input validation |
| Measure/Beat/Row | grouped spin boxes | convert through the current MBR helpers; Beat in `0..beat_measure-1` and Row in `0..beat_split-1` |
| Split resize | dedicated From (read-only) / To (editable) MBR dialog | preview requested/applied row count and downstream timing changes; keep current confirmation and undo |
| Hex/raw scalar | validated hex/decimal editor | permit exact raw input even when typed interpretation is unknown |
| Paths/text/encoded strings | text editor with explicit encoding and size validation | protect lossless trailer and source data |
| Multiline intentional scripts/conditions | multiline text editor with validation | no arbitrary numeric coercion |

## Scope

This is a **repository-wide input migration**, not just Split resize. Audit context menus, side panels, document/metadata editors, block fields, conditions, range fields, trailers, Split header, workspace creation tools, import options, and preferences. The profile/feature gates remain authoritative. For values without proved semantics, retain raw editing instead of inventing types.

Use reusable controls rather than separate one-off dialogs. Centralize typed range conversion and validity. Keep existing application language (English).

## Migration constraints

1. Canonical NX20 model, codec, import/export, command stack, and raw values are unchanged.
2. Opening/canceling a dialog must not dirty the document; accepting unchanged values must be a no-op.
3. All edits go through the existing command/validation/undo mechanism.
4. Out-of-range or unrepresentable values are rejected with an intelligible message; never silently clamp during initialization.
5. Preserve unknown metadata/flags/opaque trailer bytes, and allow raw access when meaningful.
6. Dynamic bounds must derive from Block `beat_split` and `beat_measure`, not from UI constants.
7. Split resize still cascades into all downstream Blocks and retains its destructive shrink confirmation; show when alternatives are proportionally adjusted.
8. One drag/gesture is one undo transaction. No full-chart scan for local UI updates.
9. All dialogs remain keyboard-accessible; signed negative values and decimal/hex representation must be testable.
10. GUI changes are incremental: no rewrite of core or removal of existing functionalities.

## Required test gates

- Round-trip of MBR, unsigned 16-bit min/max packed ranges, signed DM120, enum and raw flags.
- Invalid input and cancel paths leave serialized chart byte-identical.
- No-effect accept leaves document and undo history untouched.
- Structured controls can express the complete supported value range, including unsigned 32-bit raw values.
- Unknown raw bit combinations survive editing of a neighboring known field.
- Resize Split preserves cascade, alternate Block scaling, shrink warning and undo/redo.
- Profile-specific meanings and disabled options remain correct.
- Existing corpus gates, Windows/Linux CI and compact-row performance gate remain green.

## Delivery

Work in reviewable PRs: (1) common widgets + isolated tests; (2) Resize Split; (3) packed ranges and DM120; (4) metadata and Split header raw controls; (5) numeric Block/structure/workspace fields; (6) trailers, preferences and remaining inputs; (7) systematic audit showing no unreviewed `getText` for numeric/structured values. No 1.0 completion claim before the inventory and regression matrix are closed.
