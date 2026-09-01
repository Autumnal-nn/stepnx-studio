# NX20 unknown-field audit — 2026-08-31

This audit covers the supplied official NXA, Fiesta 2, and Prime 2 NX20/NFO corpora. Its purpose is deliberately narrow: identify bytes that StepNX Studio still cannot explain without inventing semantics, separate active unknowns from harmless reserved storage, and turn corpus-backed meanings into typed/editor-facing behavior.

## Scope

- 12,909 NX20/NFO files in the audited gate.
- NXA: 4,168 files.
- Fiesta 2: 4,078 files.
- Prime 2: 4,663 files.
- Round-trip preservation remains mandatory even for values whose runtime meaning is unknown.

## Split selector byte

The first Split header byte is fully structurally understood:

- `0x80`: random at Split start.
- `0x40`: random on selection trigger.
- `0x20`: force/select behavior.
- `0x1F`: lower five-bit random bank/group.

The flags are independent. `0xC0` is therefore not corrupt data; it means both random flags are set. The corpus contains 44 `0xC0` Splits: 42 in NXA and two Fiesta 2 deployment copies.

Runtime shortlist:

1. NXA `STEP/EF235/NM.NX`, Split 3, four Blocks. Smallest useful early test.
2. NXA `STEP/EF334/NM.NX`, Split 340, six Blocks.
3. Fiesta 2 `D/EF1264/EF1264/D.NX` and `CONFIG/MISSION/EF1264_D.NFO`, Split 340, six Blocks. These are deployment mirrors of the same chart.
4. NXA `STEP/EF285/NM.NX`, repeated `0xC0` at Splits 134, 136, 138, 140, 142, 144, 146, 148, 150, 152, 154, 156, 158, 160, 162, 164.
5. NXA `STEP/EF552/HD.NX`, repeated pattern at Splits 5, 10, 15, 20, 25, 30, 35, 40, 47, 52, 57, 62, 69, 74, 79, 84, 88, 93, 98, 103, 108, 113, 118, 123.

The Phase 12 editor exposes all eight bits without normalizing unusual combinations. One-Block selectors and non-zero banks without random flags are warnings, not save blockers.

## Structural bytes that are not active mysteries

Across all audited files:

- Split second byte: always `0x00`.
- Split reserved `u16`: always `0x0000`.
- Block unknown flag: always `0x00`.
- Smooth values: only `0`, `1`, `2`, `3`.

These remain raw-preserved fields. There is no evidence for a useful typed editor yet.

## Note-cell audit

Observed low-nibble note types are only:

- `0`: Empty
- `1`: Item
- `2`: Division
- `3`: Tap
- `7`: Hold head
- `B`: Hold body
- `F`: Hold tail

No additional note type exists in the supplied corpus.

`00 03 00 00` is a noncanonical/decorated empty cell, not a new arrow type. It occurs 254,909 times in Fiesta 2 and 2,069,081 times in Prime 2. It must be preserved unless the user actually edits/erases that cell.

Normal Item subtype IDs remain inside the existing registry family: NXA uses `0..20`; Fiesta 2 reaches `0..23`; Prime 2 uses a subset of that family.

### Visibility 4 and 5

This is a real active gap. NXA contains 2,219 cells with low-three-bit visibility values not previously named by Studio:

- mode 4: 364 cells in 12 files.
- mode 5: 1,855 cells in 23 files.
- Fiesta 2 / Prime 2: zero occurrences.

Examples:

- mode 4: raw `23 04 00 00`, `STEP/FFF22/NO.NX`, Split 8, Block 1, row 2304, lane 1.
- mode 5: raw `42 05 00 C6`, `STEP/FFB19/NO.NX`, Split 5, Block 1, row 32, lane 0.

Old editor notes suggest relationships to low-visibility variants such as VanishLow/AppearLow, but runtime evidence is insufficient. Studio therefore exposes these as **Raw 4** and **Raw 5**, preserves them exactly, and keeps the editor badge `V4`/`V5` instead of silently aliasing them to a named effect.

## Active metadata unknowns

### Fiesta 2 Header 1006

Status: **active unknown scalar**.

- 119 occurrences, all value `1`.
- 119 chart files / 50 song IDs.
- Always coexists with Header `1000=1` and Header `1001=<chart level>`.
- Only 23/119 also have Header `1005=1`; therefore it is not merely an alias of 1005.
- Appears in both Single and Double charts.
- Corpus behavior is scalar/boolean-like. There is no evidence that it is a trailer pointer.

Policy: preserve raw, expose diagnostically, do not give it a guessed editor name.

### Fiesta 2 Split metadata 11 / 12

Status: **active Brain Shower split-control unknowns**.

Split ID 11:

- 26 entries, all value `1`.
- confined to EF1439_D and EF1440_D plus byte-identical NFO mirrors.

Split ID 12:

- 12 entries, all value `1`.
- confined to EF1439_D plus its NFO mirror.

Affected Splits use selector `0x20` and contain the known Brain Shower Division family 21/23/26/31 plus Division 11 branch conditions. The subsystem is therefore identified; the exact runtime effect is not. Keep both fields raw-only until runtime capture proves their behavior.

### Prime 2 EF2166 placeholders

Only `MISSION/EF2166_D18_MINAMI.NFO`, Split 18, contains the discarded placeholder family:

- Split metadata IDs `0,1,2,3,4 = 0`.
- Division metadata IDs `1005,1006,1007 = 0`.

These should not inherit same-number Header semantics. They are historical/discarded data and remain low priority.

### NXA Brain Shower Division 43..49

Registry holes only. The supplied NXA corpus contains zero occurrences, so there is nothing active to infer from corpus statistics.

## Trailer fields promoted from generic to corpus-backed semantics

Fiesta 2 supports stronger profile-specific labels:

| Header base ID | Typed label | Confidence |
| ---: | --- | --- |
| 1003 | Co-op companion chart reference | official-corpus strong |
| 1100 | Mission name | official-corpus strong |
| 1102 | Mission short description / banner | official-corpus strong |
| 1103 | Mission objective / full description | runtime/corpus supported |
| 1150 | Floor 1 condition | official-corpus |
| 1151 | Condition 2 | strong inference; only EF1070, `30<=Heart` |
| 1199 | Floor 1 failure / break predicate | strong inference |
| 1203 | Floor 2 objective | official-corpus strong |
| 1250 | Floor 2 condition | official-corpus |
| 1299 | Floor 2 failure / break predicate | strong inference |
| 1303 | Floor 3 objective | official-corpus strong |
| 1350 | Floor 3 condition | official-corpus |
| 1399 | Floor 3 failure / break predicate | strong inference |
| 1403 | Floor 4 objective | official-corpus strong |
| 1450 | Floor 4 condition | official-corpus |

Prime 2 intentionally retains more conservative names. In particular, 1100 and 1103 can duplicate objective strings there, so Fiesta 2 labels must not leak across profiles.

### Trailer relocation policy

Storage typing and semantic confidence are separate questions. A registered trailer-offset family can be relocated even if its human meaning is only corpus-backed. Conversely, an unknown scalar does **not** become a pointer merely because its numeric value lands on a four-byte-aligned UTF-8 string.

Phase 12 removes the previous `looks_like_unknown_pointer` heuristic. Length-changing edits now relocate registered trailer offsets only; opaque metadata remains byte-for-byte scalar storage. This avoids false-positive blockers such as Header 1006 accidentally resembling an offset.

## Editor-only noteskin semantics

The NX20 function-bit collision is resolved visually without rewriting source bytes:

- Tap + function `0x20`: normal tap artwork plus an alpha-derived white outline. This is the editor Ghost visualization.
- Hold head + function `0x20`: third atlas row, i.e. the actual roll-head artwork.
- Hidden/Bonus-family function `0x60`: 40% opacity in the authoring view.
- Invisible visibility `0`: 40% opacity in the authoring view.
- Appear visibility `1`: 100% at top to 40% at bottom.
- Vanish visibility `2`: 40% at top to 100% at bottom.
- Raw visibility 4/5: no invented effect; retain explicit `V4` / `V5` badge.

These effects are authoring aids only. Gameplay Preview is intentionally untouched.

## Remaining runtime research queue

1. Determine visibility 4/5 runtime behavior using NXA examples above.
2. Determine Header 1006 using Fiesta 2 chart pairs with and without the field while controlling 1005.
3. Determine Split 11/12 in EF1439_D / EF1440_D Brain Shower runtime.
4. Test `0xC0` selection timing/interaction using EF235 first, then EF285/EF552 for repeated behavior.
5. Leave EF2166 placeholders and Brain Division 43..49 alone until actual runtime/corpus evidence appears.
