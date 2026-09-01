# NX20 visibility low-bit corpus/runtime audit

Date: 2026-09-01

This note records the exhaustive scan of the low three bits of note-cell byte 1
(`raw[1] & 0x07`) across the supplied NXA, Fiesta 2, and Prime 2 NX20 corpora,
plus runtime validation in NXA Brain Shower.

The scan excludes EmptyRow markers, Lightmap rows, and type-0 decorated empty
cells. Counts below therefore refer to actual note cells only.

## Distribution

| Profile | V0 | V1 | V2 | V3 | V4 | V5 | V6 | V7 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NXA | 87,145 | 13,890 | 100,301 | 1,926,671 | 364 | 1,855 | 0 | 0 |
| Fiesta 2 | 137,122 | 22,542 | 172,385 | 3,697,639 | 0 | 0 | 0 | 0 |
| Prime 2 | 50,998 | 3,532 | 31,188 | 3,635,814 | 0 | 0 | 0 | 0 |

Runtime validation of `STEP/FF704/NO.NX` closes the two NXA-only names:

- visibility `4` = **VanishLow**;
- visibility `5` = **AppearLow**.

Values 6 and 7 have zero occurrences in all three supplied corpora. They were a
previous speculative extension and are not typed Studio choices.

## Visibility 4: VanishLow

NXA contains 364 V4 cells in 12 files. Every one is Tap (`type 0x3`) with
function bits `0x20`.

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

Runtime example from FF704:

```text
23 02 03 00  Poker Card Skin: Vanish
23 04 02 80  Hanafuda Card Skin: VanishLow
```

## Visibility 5: AppearLow

NXA contains 1,855 V5 cells in 23 files. Every one has function bits `0x40`.
The note-type distribution is:

| Type | Cells |
| --- | ---: |
| Division (`0x2`) | 1,735 |
| Tap (`0x3`) | 114 |
| Hold Head (`0x7`) | 1 |
| Hold Body (`0xB`) | 4 |
| Hold Tail (`0xF`) | 1 |

The six Hold cells are one complete fixture in `STEP/FF704/NO.NX`, Split 2,
Block 1, lane 4, rows 120..125:

```text
47 05 00 00
4B 05 00 00
4B 05 00 00
4B 05 00 00
4B 05 00 00
4F 05 00 00
```

Brain Shower Step G blocks use encodings such as `42 05 00 C6`, confirming
AppearLow. Ordinary arrows in the same runtime can use Appear, e.g.
`43 01 00 00`.

The validated FF704 Header metadata is `901=5, 902=1, 903=7`.

## Long-note first-byte correction exposed by FF704

Visibility is independent from the long-note sustain bit. The runtime comparison
between `37 02 00 00` and `47 05 00 00` resolves the editor's old Roll mistake:

- `37`: Hold Head with bit `0x10` set. It is a sustained long, not Roll.
- `47`: Hold Head with bit `0x10` clear. It is the Roll/retrigger variant.

Therefore function bits `0x20/0x40/0x60` cannot be used to identify Roll. On
Hold Head/Body/Tail, bit `0x10` is the independent can-hold/sustain bit. This is
also consistent with the NX10 importer, whose normal non-roll long conversions
set `0x10` while roll conversions clear it.

## Studio policy

- `VanishLow` and `AppearLow` are typed options only in NXA and NXA-patched
  profiles. Fiesta/Prime+ do not expose them.
- Visibility opacity/filter cues are drawn on Tap and Hold Head only. Hold
  Body/Tail remain 100% visible in the authoring grid; the Head communicates the
  property for the complete long.
- V6/V7 are not advertised or assigned names. Raw round-trip remains lossless if
  such bytes are encountered outside the audited corpus.
- Roll artwork uses the long-note `0x10` sustain bit, not the function-bit family.
- No raw visibility value is normalized to another value.
