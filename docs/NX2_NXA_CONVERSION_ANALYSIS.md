# NX2 -> NXA official conversion analysis

Date: 2026-08-25

Corpora: supplied `NX2 Chart Dump.zip` and `NXA Chart Dump.zip`.

Status: NX10 conversion semantics frozen for the observed official NX2 domain.

## Why this comparison is authoritative

NX2 stores its complete chart set as NX10. NXA is the direct successor and the
supplied NXA dump contains the corresponding deployed charts, overwhelmingly as
NX20. Matching the same `STEP/<song>/<slot>.NX` paths therefore gives an
independent official conversion corpus rather than another fan converter or
synthetic fixture.

The comparison deliberately treats later NXA chart edits as content changes,
not conversion rules. Format rules are accepted where they are repeated across
independent matching charts and/or cover the complete observed source-code
domain.

## Corpus inventory

| Corpus | NX files | NX10 | NX20 | zero-byte NXP |
| --- | ---: | ---: | ---: | ---: |
| NX2 | 2,125 | 2,125 | 0 | 604 |
| NXA | 4,180 | 12 | 4,168 | 1,269 |

There are 2,123 common NX paths. Twelve remain NX10 in NXA; the other 2,111
have an NX2 NX10 source and an NXA NX20 successor at the same path.

The 2,125-file NX2 source corpus contains exactly the four importer modes already
modeled by StepNX Studio:

| NX10 chart type / columns | Files | NX20 projection |
| --- | ---: | --- |
| `0 / 5` | 850 | Single `(start=0, columns=5)` |
| `0 / 10` | 588 | Double `(start=0, columns=10)` |
| `2 / 6` | 19 | Half Double `(start=2, columns=6)` |
| `10 / 3` | 668 | Lightmap `(start=0, columns=3, lightmap=1)` |

For all 2,111 common NX10->NX20 pairs, the NXA header mode matches this mapping
exactly.

## Source-domain closure

The complete NX2 corpus was scanned before comparing successor output.

- 110 distinct nonzero NX10 note codes occur. Every note type, visibility /
  function family, item selector, accumulator selector, and noteskin bank used
  by those codes is supported after the corrections below.
- BeatSplit uses 27 values with an observed maximum of 128; no official NX2
  chart requires narrowing from the NX10 `u16` to NX20 `u8` representation.
- Division min/max values never exceed the NX20 packed-u16 range.
- 1,315 zero-BPM blocks occur in 47 files.
- Division-0 random-selection markers use both proven source forms: `1/0` and
  `2/0`.

No official NX2 chart produces an approximation or unsupported diagnostic under
the frozen observed-domain mapping.

## Corrections discovered by the successor corpus

### 1. Half Double row pointer

The earlier importer treated NX10 chart type 2 as if its stored row pointer
required an additional four-byte offset. That was wrong.

The stored pointer already addresses the six active Half Double cells. The
physical placement is expressed by NX20 `start_column = 2`; no second byte
shift is applied to the row payload.

Across the 18 Half Double files that have NX20 successors, using the stored
pointer directly gives 29,748 / 29,748 matching cells on aligned non-empty rows.
The previous `+4` projection does not.

The official converter also maps 1,006 explicitly stored Half Double rows whose
six active cells are zero to NX20 `EmptyRow` markers.

### 2. Noteskin-bank encoding

NX10 bank 1 (`0x0500`) and bank 2 (`0x0A00`) are not represented only by the
NX20 bank index in bits 16.. . The official conversion carries both pieces:

```text
bank 0 -> 0x00000000
bank 1 -> 0x40000000 | (1 << 16)
bank 2 -> 0x80000000 | (2 << 16)
```

The previous importer preserved only the `bank << 16` part.

### 3. No-register long-note family

For NX10 visibility/function `0x70`, ordinary taps use the NX20 `0x20` low
family, but no-register HEAD/BODY/TAIL components use `0x30`:

```text
NX10 0x0074 -> NX20 0x00000337
NX10 0x0076 -> NX20 0x0000033B
NX10 0x0077 -> NX20 0x0000033F
```

The former projection incorrectly used `0x20` for all three.

### 4. BPM-zero warp fallback

The official NX2->NXA converter handles a zero-BPM block as an NX20 smooth warp.
Its auxiliary BPM is the previous positive finite BPM. If no previous positive
BPM exists, the fallback is 120 BPM; it does **not** look ahead to a later
positive BPM.

Using that rule matches 1,314 of the 1,315 aligned zero-BPM successor cases. The
single exception is `STEP/EF367/LM.NX`, whose NXA Lightmap was structurally
rewritten (three source Splits became one successor Split) and is therefore not
a conversion-rule sample.

## Independent confirmations that did not require code changes

Division conversion is exceptionally strong evidence. Across 18,769 aligned
blocks, every projected nonzero NX10 Division min/max pair matches the official
NXA NX20 Division metadata exactly.

The Division-0 random markers likewise project to the established Split select
bits. 16,312 / 16,331 aligned Splits match byte-for-byte. The 19 differences are
confined to three mission charts (`EF235/NM`, `EF285/NM`, `EF334/NM`) where NXA
changes the selection flags; the Division payload projection itself remains
exact.

After applying the note corrections above, all 110 / 110 distinct NX2 note
codes have matching official NXA evidence. Across 1,069,004 aligned nonzero note
occurrences, 1,068,345 (99.938%) carry the expected converted cell value. The
remaining 659 occurrences are sparse successor chart edits (for example bank
changes or removed/repositioned notes), not a competing per-code conversion
mapping: every source code's expected mapping is present, and the worst per-code
agreement is still above 99.9%.

## Why NXA is not byte-identical to a mechanical conversion

A successor corpus is also a content revision. Among structurally aligned
common files, Block Start Time differences are overwhelmingly whole-chart
retimes:

- 889 files retain the same Start Times;
- 1,183 files use one constant nonzero Start-Time delta across every aligned
  Block;
- only 24 files have varying per-Block Start-Time differences.

The first Block's `offset_or_delay` commonly moves by the same constant. This is
consistent with song/chart resynchronization in NXA and is not evidence that an
NX10 importer should alter source timing by a global formula.

A small number of charts and Lightmaps were structurally or musically edited in
NXA. Those are retained as historical/content differences rather than folded
into the codec.

## Acceptance decision

For the official NX2 source domain, the NX10 importer no longer has an open
research gate. The corpus establishes:

1. every observed NX10 chart mode;
2. every observed note code and item/accumulator selector;
3. the exact Half Double row addressing rule;
4. the NX20 noteskin-bank bit layout used by NX2 conversions;
5. the no-register long-note low-byte family;
6. Division min/max packing and random Split projection;
7. zero-BPM warp fallback behavior;
8. Lightmap inline-row interpretation.

Future NX10 inputs outside the observed domain remain protected by explicit
approximation/unsupported diagnostics. No claim is made that arbitrary unknown
NX10 extensions can be converted losslessly.
