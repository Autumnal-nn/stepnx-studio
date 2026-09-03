# NX20 note byte 3: corpus notes

`raw[3]` is split into two independent bit fields:

```text
bits 7..6  slot = raw[3] >> 6       (0..3)
bits 5..0  low6 = raw[3] & 0x3F     (0..63)
```

The old NX10/NX20 editor confirms that the two-bit slot is inherited from the
NX10 note byte: NX10 `b1 & 0x03` becomes NX20 `(slot << 6)` and projects back to
the same low two NX10 bits. It is therefore not a field invented for Brain
Shower.

A direct scan of the supplied official corpora found:

| corpus | NX20 parsed | non-empty cells | low6 2..5 |
|---|---:|---:|---:|
| NXA | 4,168 | 2,130,226 | 0 |
| Fiesta 2 | 4,078 | 4,284,597 | 0 |
| Prime 2 quick scan | 4,655 | 5,790,613 | 0 |

The quick Prime 2 scanner skipped eight files that the established full corpus
audit classifies as structurally valid, so these counts are evidence about note
usage, not a replacement for the canonical 4,663-file structural result.

Slot usage is highly structured:

- Slot 0, 1 and 2 occur on normal Tap/Hold families and correlate strongly with
  noteskin-bank families modulo three.
- Slot 3 is overwhelmingly a system/special channel: Item and Division cells,
  including known Brain Shower C6/C7 markers.
- This evidence does **not** prove `0=P1, 1=P2, 2=P3, 3=P4`. The editor therefore
  labels the field simply `Slot` and preserves all raw values.

On Division notes the low six bits can participate in a 14-bit contextual
Division ID, so `low6` is deliberately not globally renamed to `Brain Code` in
forensic output.

## NXA runtime normalization

For REGISTER Tap/Hold cells, the source bits 7..6 are cleared during chart
preparation and rebuilt as a runtime judgment/statistics group. With Multibank
(`COMMAND b`) disabled the runtime group is 0; with Multibank enabled it is
`payload14 % 3`, where `payload14 = raw[2] | ((raw[3] & 0x3F) << 8)`. For
ordinary arrows (`low6 == 0`) this is therefore `bank % 3`, yielding the
families `0/3`, `1/4`, `2/5`. REGISTER Item/Division cells are normalized to
group 3. The statistics structures for groups 0, 1, 2 and aggregate are spaced
by 0x6C bytes and feed `Perfect0`, `Miss1`, `MaxCombo2`, etc.

The original high two bits remain a **Source Slot**, not the runtime judgment
group. Row-null markers are one confirmed consumer of the source value. The GUI
therefore keeps Source Slot under Advanced raw fields.
