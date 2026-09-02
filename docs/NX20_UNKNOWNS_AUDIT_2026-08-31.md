# NX20 unknown-field audit — 2026-08-31

This audit covers the supplied official NXA, Fiesta 2, and Prime 2 NX20/NFO
corpora. Its purpose is to separate true unknowns from reserved storage and from
fields that later evidence has since resolved.

> **2026-09-02 correction:** several items that were active unknowns on August 31
> are now closed. Visibility 4/5 are runtime-confirmed as VanishLow/AppearLow,
> Fiesta Header1006 is the legacy `Another` classification, and the Fiesta+
> Header1000..1008 family is documented separately. The remaining raw-only cases
> are intentionally narrow. This file preserves the useful corpus counts while
> updating their current status.

## Scope

- 12,909 NX20/NFO files in the audited gate.
- NXA: 4,168 files.
- Fiesta 2: 4,078 files.
- Prime 2: 4,663 files.
- Round-trip preservation remains mandatory even for values whose runtime
  meaning is unknown.

## Split selector byte

The first Split header byte is structurally understood, but the two selector
bits act at different phases:

- `0x80`: random Block selection is decided when the chart is loaded;
- `0x40`: perform a bank lookup when the Split is reached;
- lower five bits `1..31`: selection banks;
- lower five bits `0`: **no bank**. There is no bank 0;
- `0x20`: force/select behavior.

That makes the raw values importantly different:

- `0x40`: there is no bank to follow, so the bank lookup fails and the runtime
  falls back to a fresh random Block choice when the Split is reached;
- `0x41..0x5F`: follower Splits for banks `1..31`, reusing the latest Block index
  selected for that bank;
- `0x01..0x1F`: valid banked selectors even without either random bit. A
  condition or explicit active candidate can establish the bank state that a
  later follower reuses;
- `0x81..0x9F`: load-time random selectors whose chosen Block index also becomes
  the state of the corresponding bank.

For example, `0x01 -> 0x41` is meaningful: the first Split selects a candidate
through its normal condition/active-Block logic and records the chosen index for
bank 1; the following `0x41` reuses that same index. Likewise `0x81 -> 0x41`
records a load-time random choice and later follows it.

The flags remain independently encodable. `0xC0` is therefore not corrupt data;
it means both selector bits are set. Existing runtime validation shows `0x80`
precedence for the combined form, while the raw combination is preserved exactly.
The corpus contains 44 `0xC0` Splits: 42 in NXA and two Fiesta 2 deployment
copies.

Useful runtime examples remain:

1. NXA `STEP/EF235/NM.NX`, Split 3, four Blocks;
2. NXA `STEP/EF334/NM.NX`, Split 340, six Blocks;
3. Fiesta 2 `D/EF1264/EF1264/D.NX` and
   `CONFIG/MISSION/EF1264_D.NFO`, Split 340, six Blocks;
4. NXA `STEP/EF285/NM.NX`, repeated `0xC0` Splits 134..164 on even indices;
5. NXA `STEP/EF552/HD.NX`, repeated `0xC0` pattern across the chart.

The editor exposes the complete selection byte without normalizing unusual
combinations. A non-zero bank without `0x80`/`0x40` is valid and no longer emits
an "active bank without selector" warning. One-Block selectors may still warn as
redundant. Further `0xC0` runtime testing is useful historical validation, not an
unresolved serialization problem.

## Structural bytes that are not active mysteries

Across all audited files:

- Split second byte: always `0x00`;
- Split reserved `u16`: always `0x0000`;
- Block unknown flag: always `0x00`;
- Smooth values: only `0`, `1`, `2`, `3`.

These remain raw-preserved. Lack of a typed authoring control for a reserved
field is not a format gap.

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

`00 03 00 00` is a decorated empty cell, not a new arrow type. It occurs 254,909
times in Fiesta 2 and 2,069,081 times in Prime 2. It is preserved byte-for-byte
unless the user actually edits/erases that cell.

Normal Item subtype IDs remain inside the existing registry family: NXA uses
`0..20`; Fiesta 2 reaches `0..23`; Prime 2 uses a subset of that family.

### Visibility 4 and 5 — resolved

The August 31 corpus counts remain useful:

- mode 4: 364 cells in 12 NXA files;
- mode 5: 1,855 cells in 23 NXA files;
- Fiesta 2 / Prime 2: zero occurrences.

Runtime validation of NXA `STEP/FF704/NO.NX` closed the meanings:

- visibility `4` = **VanishLow**;
- visibility `5` = **AppearLow**.

These are now typed NXA authoring options. Values 6 and 7 remain unobserved in
the supplied corpora and are not assigned invented names. See
`NX20_VISIBILITY_4_7_CORPUS.md` for the detailed evidence.

## Metadata status

### Fiesta 2 Header1006 — resolved

The original corpus observation was:

- 119 occurrences, all value `1`;
- 119 chart files / 50 song IDs;
- always alongside Header1000/1001;
- only 23/119 also contain Header1005=1;
- observed in Single and Double charts.

Later executable/LIST/corpus evidence identifies Header1006 as **Another**, the
Fiesta through Fiesta 2 Select Screen classification. It is retired after Fiesta
2 and should not be offered as Prime+ authoring metadata. It is not a trailer
pointer. `NX20_HEADER_1000_1008.md` is the canonical reference.

### Fiesta 2 Split metadata 11 / 12 — still unresolved

These are Split-scope Brain Shower controls and must not be confused with the
known Division11/12 O/X condition family.

Split ID 11:

- 26 entries, all value `1`;
- confined to EF1439_D and EF1440_D plus NFO mirrors.

Split ID 12:

- 12 entries, all value `1`;
- confined to EF1439_D plus its NFO mirror.

The subsystem is identified but the exact Split-level runtime effect is not.
Both remain visible/raw-only and non-authorable until direct evidence exists.

### Prime 2 EF2166 placeholders — preservation-only

Only the discarded `MISSION/EF2166_D18_MINAMI.NFO`, Split 18, contains:

- Split metadata IDs `0,1,2,3,4 = 0`;
- Division metadata IDs `1005,1006,1007 = 0`.

They must not inherit same-number Header semantics. They remain historical raw
placeholder data, not an editor research blocker.

### NXA Brain Shower Division 43..49 — unresolved but inactive

Direct native consumers exist, but the supplied NXA corpus contains zero
occurrences. Individual meanings remain unknown/raw and non-authorable. No
current editor feature depends on guessing them.

## Trailer fields and relocation

Later-generation trailer storage is structurally understood where registered:
composite Header IDs retain their full 32-bit serialized identity, registered
trailer fields use offsets relative to the trailer start, and proven UTF-8/NUL
strings may be edited with guarded relocation.

Storage typing and semantic confidence remain separate. A registered trailer
offset may be relocated even when its human label is corpus-backed. Conversely,
an arbitrary scalar is not promoted to a pointer merely because its numeric
value happens to land on string-like bytes.

The August 31 statement that the ambiguous-pointer guard had been removed was
incorrect for the current implementation. Length-changing relocation remains
**conservative**: every known affected offset is updated, shared aliases are
preserved, and an ambiguous untyped value that plausibly points into the moving
trailer region blocks the operation rather than being guessed. This matches the
Qt editor and regression fixtures.

Fiesta-and-later Header1000..1008 semantics are now closed separately in
`NX20_HEADER_1000_1008.md`; they are no longer part of the unknown-field queue.

## Editor note semantics closed after the audit

The editor preserves raw note bytes while giving proven semantics a usable
visual projection:

- Ghost taps use normal arrow artwork with an editor-only outline;
- long-note Roll versus sustained Hold is determined by the independent `0x10`
  sustain bit, not by Ghost/function bits;
- Hidden/Invisible/Appear/Vanish/VanishLow/AppearLow receive editor presentation
  cues without rewriting the chart;
- decorated empty cells remain empty visually while preserving their raw bytes.

Gameplay behavior is documented separately from authoring visualization.

## Remaining research queue

Current format/metadata research is intentionally small:

1. determine Fiesta 2 **Split** metadata 11/12 runtime behavior;
2. identify NXA Brain Division 43..49 individually if a concrete use case or
   corpus fixture appears;
3. retain Prime 2 EF2166 placeholders as raw historical data unless new evidence
   makes them relevant;
4. optionally runtime-test `0xC0` examples for historical selection timing, not
   because the selector byte is structurally unknown.

Visibility 4/5 and Header1006 are no longer on this queue.
