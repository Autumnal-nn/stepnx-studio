# NX20, NFO, and folder-layout corpus analysis

Date: 2026-08-10

Corpus: NXA, Fiesta 2, and Prime 2

Status: NFO and folder architecture frozen.

## Executive conclusions

1. `.NFO` is not a separate companion format. Every Fiesta 2 and Prime 2 NFO
   begins with `NX20` and contains a complete NX20 chart.
2. Fiesta 2 duplicates all 267 NFO files byte-for-byte as NX files. Prime 2 has
   the same pattern with a small set of missing or renamed deployment copies.
3. The post-chart trailer is not NFO-specific. It occurs in every analyzed
   Fiesta 2 and Prime 2 NX20 file, regardless of extension, and in no analyzed
   NXA NX20 file.
4. The final `u32` is the complete trailer size, including the marker itself.
5. Global metadata may contain offsets relative to the trailer start. Composite
   metadata IDs use high bits for a variant/language and low bits for a field ID.
6. `.NXP` is a zero-byte StepEdit workflow sentinel, not a container or runtime
   requirement. StepNX Studio will not support it.
7. `LM.NX` is the only required deployment document for `Save All`.

## Material analyzed

| Game | `.NX` | `.NFO` | `.NXP` | Structural result |
| --- | ---: | ---: | ---: | --- |
| NXA | 4,180 | 0 | 1,269 | 4,168 NX20; 12 official/legacy NX10 |
| Fiesta 2 | 3,811 | 267 | 0 | 4,078/4,078 valid NX20 |
| Prime 2 | 4,375 | 288 | 0 | 4,663/4,663 valid NX20 |
| **Total** | **12,366** | **555** | **1,269** | **12,909 NX20 + 12 NX10** |

Executables used as independent loader evidence:

- `piu_nxa`;
- `piu_nx2`;
- `piuf2_160_io`;
- `piu_prime`;
- `exec_HDfix`.

| Executable | SHA-256 | Relevant path strings |
| --- | --- | --- |
| `piu_nxa` | `48b23613f9a059d5893332671b5ef2a4bc0a892dffb35692eba3dfbb6797ca3d` | `STEP/%s/LM.NX`; `STEP/%s/%s.NX` |
| `piuf2_160_io` | `acf0cec9d5d500241a69585848baf4ed8a9b3d24e385a7423f453936d665a83f` | `config/mission/%03X_`; `%s%s.NFO`; `D/%03X/%03X/%s.NX` |
| `piu_prime` | `9abb6563927eeaae4fe5272446ab382f35a1b106312a972155278f46cc35e746` | `D/%03X/%03X/%s.NX`; `config/mission/%03X_`; `%s%s.NFO` |
| `exec_HDfix` | `bcb9ed0535c5f9d2c6125a1f7be489efb46a278619a94e844b817264e70b3d8c` | `D/%03X/%03X/%s.NX`; `LM.NX`; `mission/%03X_`; `%s%s.NFO` |

No unpacked runtime image contains `.NXP` in ASCII or UTF-16. This absence is
supporting evidence, not the entire argument: the direct NX/NFO path xrefs feed
the chart readers in all inspected engine generations.

## NXP is not a runtime format

The NXA dump contains 1,269 NXP files. Every one is zero bytes and corresponds
to a folder of the same basename. StepEdit removes the extension, opens that
folder, and attempts known chart slots; it reads no NXP payload.

The NXA runtime instead formats `STEP/%s/LM.NX` and `STEP/%s/%s.NX`. Fiesta 2,
Prime 1, and unpacked Prime 2 likewise construct direct NX and mission-NFO
paths. Prime 2 xrefs additionally show `LM.NX` passed to a chart parser that
checks `NX20` magic.

Decision: `.NXP` has no parser, entry point, exporter, or compatibility path in
StepNX Studio. The editor opens the folder itself.

## LM.NX is the real folder requirement

All 1,269 NXA chart folders contain `LM.NX`, and the runtime references it
directly. A blank Lightmap means no light events; it does not mean a zero-byte
file.

Two minimal official NXA Lightmaps are 72-byte valid NX20 documents with:

- `start_column = 0`;
- `columns = 3`;
- an active Lightmap flag;
- one split, one block, one row, and one `00 00 00 00` channel value.

Two controlled StepEdit 5.63 regenerations produced 1,664-byte NX10 Lightmaps
that differed in exactly one byte inside the inherited BPM float. The fixed
layout is 4/4, BeatSplit 2, default scroll 0.5, and 400 zeroed Lightmap rows.
Changing the source chart's scroll, BeatSplit, and row count did not propagate;
only its BPM did. Their synthetic reconstructions match both samples byte for
byte, and their imported NX20 projections match the native generator output.

Folder contract:

1. missing `LM.NX` does not block opening a folder for repair;
2. `Save All` cannot complete without a valid `LM.NX`;
3. `Generate Blank LM.NX` creates the native NX20 equivalent of the observed
   StepEdit layout with an explicit BPM;
4. an existing valid `LM.NX` is reused unchanged;
5. an existing invalid or case-colliding Lightmap requires explicit repair and
   is never replaced with a blank file.

## NFO is an NX20 mission chart

All 555 NFO files have normal NX20 headers, metadata, splits, blocks, Divisions,
rows, notes, and the same later-generation trailer used by NX files.

Fiesta 2 maps, for example:

```text
CONFIG/MISSION/EF1307_D.NFO
D/EF1307/EF1307/D.NX
```

The pair is byte-identical, as are all 267 Fiesta 2 pairs.

For Prime 2:

- 280/288 NFO files have an identical conventional-path NX counterpart;
- 282/288 have some byte-identical NX copy in the corpus;
- four `EF2166_*` files have no `D/EF2166` folder in the dump;
- four long `EF2167` aliases lack a literally matching NX filename;
- two aliases map exactly to abbreviated NX names;
- the remaining two aliases differ from their likely NX counterpart by six
  bytes and one byte respectively.

Therefore NFO is a deployment role, not an encoding. Mirrors may legitimately
diverge, so the editor must never synchronize them merely by basename.

## Later-generation trailer

For Fiesta 2 and Prime 2:

```text
trailer_size  = read_u32_le(file_size - 4)
trailer_start = file_size - trailer_size
nx20_body_end = trailer_start
```

The marker is part of the trailer. A canonical empty trailer is therefore
`04 00 00 00`.

| Game | Files with trailer | Valid size marker | Parsed body end matches |
| --- | ---: | ---: | ---: |
| Fiesta 2 | 4,078 | 4,078 | 4,078 |
| Prime 2 | 4,663 | 4,663 | 4,663 |

| Game/extension | Total | Size 4 | Size 8 | Size > 8 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fiesta 2 `.NX` | 3,811 | 3,337 | 195 | 279 | 1,508 |
| Fiesta 2 `.NFO` | 267 | 0 | 11 | 256 | 1,508 |
| Prime 2 `.NX` | 4,375 | 3,881 | 214 | 280 | 804 |
| Prime 2 `.NFO` | 288 | 0 | 0 | 288 | 804 |

All 4,168 analyzed NXA NX20 files end immediately after their last row.

### Metadata offsets

Scalar values and offsets coexist in global metadata. Small values must not be
blindly treated as pointers. The localized-field pattern is:

```text
base_field_id = metadata_id & 0xFFFF
variant_index = metadata_id >> 16
string_offset = metadata_value
string_address = trailer_start + string_offset
```

Observed offset-like base fields include `1100`, `1102`, `1103`, `1150`,
`1151`, `1199`, `1203`, `1250`, `1299`, `1303`, `1350`, `1399`, `1403`, and
`1450`, depending on the engine profile. This list is evidence, not a universal
schema. Fiesta 2 and Prime 2 do not use exactly the same set.

Length-changing trailer edits must rebuild the blob, relocate every typed
offset, and update the final marker. If an unknown field could be invalidated,
save must preserve the region or stop with a diagnostic.

## Other confirmed variants

### NX10 inside the NXA dump

Twelve official NXA files use `NX10` magic:

- `EF008`: `LM.NX`, `NO.NX`;
- `EF085`: `LM.NX`, `NM.NX`;
- `EF158`: `HD.NX`, `LM.NX`;
- `EF253`: `LM.NX`, `NO.NX`;
- `EF256`: `HD.NX`, `LM.NX`;
- `EF309`: `CR.NX`, `LM.NX`.

Extension and game profile do not determine the codec. Detection starts with
the magic; NX10 is an import concern and is never tolerated by the NX20 parser.

The isolated importer was run over all twelve files on 2026-08-11. Every file
produced a semantically lossless report, a structurally valid canonical
document, and a native NX20 byte stream that reparsed and rebuilt exactly. The
twelve byte streams were also byte-identical to NXConvert v4 output. The v61a
reference differed only in its Lightmap start-column projection and some NM
note rows; those differences are not adopted because the importer and v4 agree
on the NXA-native representation.

### Implicit Prime 2 Lightmaps

Eight Prime 2 `LM.NX` files use `columns = 3` and `is_lightmap = 0` while their
rows still use the four-byte Lightmap encoding. The compatible rule is:

```text
effective_lightmap = (is_lightmap != 0) or (columns == 3)
```

### Fields that must not be normalized

- `smooth_speed` uses 0, 1, 2, and 3 in official charts;
- observed split padding is zero, but remains raw;
- the observed final block-header byte is zero, but remains raw;
- no special float appeared in the corpus, which does not permit rewriting
  unedited floats by value.

## Codec and workspace decisions

One body codec supports three envelope policies: NXA immediate EOF, Fiesta 2
sized trailer, and Prime 2 sized trailer. NX and NFO select deployment roles,
not different parsers.

The lossless model preserves ordered metadata, complete composite IDs, raw
floats, flags, padding, note cells, source regions, unknown trailer data, and
the final size marker.

Folder rules are frozen:

1. load every immediate `*.NX` file;
2. do not recurse or require known slot names;
3. isolate a parse failure to its file;
4. use `nxa-native` as the default profile without normalizing raw bytes;
5. keep audio selection and caches outside chart data;
6. require a valid `LM.NX` only for `Save All`;
7. allow individual NX/NFO open and save.

## Remaining research

- fully type trailer fields and string encodings by engine profile;
- test length-changing trailer edits in real runtimes;
- determine whether the missing Prime 2 `EF2166` NX copies are dump omissions;
- execute the generated blank Lightmap in NXA as an independent runtime gate.

These gaps block semantic editing of every trailer field. They do not block the
lossless raw codec, structural viewer, or raw-preserving writer.

## Derived acceptance criteria

1. NXA NX20 parses to EOF with no trailer.
2. The 12 NXA NX10 files are classified, never accepted as NX20.
3. Fiesta 2/Prime 2 body end equals `file_size - eof_u32` for every corpus file.
4. Unedited NX and NFO round-trip byte-exactly.
5. All eight implicit Prime 2 Lightmaps parse without overrun.
6. Typed trailer relocation updates offsets and the final size marker.
7. Unknown relocatable fields block unsafe saves.
8. Mirror export never overwrites another deployment copy silently.
9. Folder open ignores NXP and isolates per-file errors.
10. `Save All` ends with a valid NX20 `LM.NX`, never a zero-byte placeholder.
