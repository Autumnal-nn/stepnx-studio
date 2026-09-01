# NX20 visibility low-bit corpus audit

Date: 2026-09-01

This note records the exhaustive scan of the low three bits of note-cell byte 1
(`raw[1] & 0x07`) across the supplied NXA, Fiesta 2, and Prime 2 NX20 corpora.

The scan excludes EmptyRow markers, Lightmap rows, and type-0 decorated empty
cells. Counts below therefore refer to actual note cells only.

## Distribution

| Profile | V0 | V1 | V2 | V3 | V4 | V5 | V6 | V7 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NXA | 87,145 | 13,890 | 100,301 | 1,926,671 | 364 | 1,855 | 0 | 0 |
| Fiesta 2 | 137,122 | 22,542 | 172,385 | 3,697,639 | 0 | 0 | 0 | 0 |
| Prime 2 | 50,998 | 3,532 | 31,188 | 3,635,814 | 0 | 0 | 0 | 0 |

Therefore visibility values 4 and 5 are real official encodings in NXA. No
visibility 6 or 7 cell exists in any of the three supplied corpora.

## Visibility 4

NXA contains 364 V4 cells in 12 files. Every one is:

- Tap (`type 0x3`);
- function bits `0x20` (Ghost-family encoding).

File counts:

| Cells | File |
| ---: | --- |
| 211 | `STEP/FF704/NO.NX` |
| 24 | `STEP/FF802/NO.NX` |
| 18 | `STEP/FF401/NO.NX` |
| 18 | `STEP/FF507/NO.NX` |
| 18 | `STEP/FF711/NO.NX` |
| 15 | `STEP/FFE21/NO.NX` |
| 12 | `STEP/FF708/NO.NX` |
| 12 | `STEP/FFB01/NO.NX` |
| 12 | `STEP/FFF22/NO.NX` |
| 9 | `STEP/FFD07/NO.NX` |
| 9 | `STEP/FFF04/NO.NX` |
| 6 | `STEP/FFE15/NO.NX` |

This concentration means V4 should not be generalized into a named visibility
mode merely from its numeric value.

## Visibility 5

NXA contains 1,855 V5 cells in 23 files. Every one has function bits `0x40`
(Normal). The note-type distribution is:

| Type | Cells |
| --- | ---: |
| Division (`0x2`) | 1,735 |
| Tap (`0x3`) | 114 |
| Hold Head (`0x7`) | 1 |
| Hold Body (`0xB`) | 4 |
| Hold Tail (`0xF`) | 1 |

The six Hold cells are one complete fixture in `STEP/FF704/NO.NX`, Split 2,
Block 1, lane 4, rows 120..125 (zero-based split/block/lane indices 1/0/3):

```text
47 05 00 00
4B 05 00 00
4B 05 00 00
4B 05 00 00
4B 05 00 00
4F 05 00 00
```

Representative V5 Division encodings include `42 05 00 C6` and
`42 05 00 C7`.

## Studio policy

- V4 and V5 remain explicit raw/unknown choices. Their runtime names are not
  proven.
- V6 and V7 are preserved if encountered through raw editing/round-trip, but are
  not advertised as typed choices because the supplied official corpora contain
  zero examples.
- No raw value is normalized to another visibility value.
