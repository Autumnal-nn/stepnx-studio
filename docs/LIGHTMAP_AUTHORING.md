# Lightmap authoring

Date: 2026-09-02

Target: StepNX Studio 0.9.5 keyboard/authoring hardening

## Structural model

NX20 Lightmap files have a three-column logical field while every populated row
occupies four raw bytes. StepNX therefore treats the first three bytes as the
three editable light channels and keeps byte 3 as opaque row data.

The fourth byte is **not normalized on edit**. It is copied through unchanged
when any of the three authorable channels changes, even though the supplied
official corpus currently contains no nonzero examples.

## Corpus evidence

The supplied NXA, Fiesta 2 and Prime 2 corpora were audited at row level.

| Corpus | Lightmap rows inspected | Bytes 0..2 | Byte 3 |
| --- | ---: | --- | --- |
| NXA NX20 | 1,183,576 | only `00` / `01` | always `00` |
| NXA NX10 | 4,060 | only `00` / `01` | always `00` |
| Fiesta 2 NX20 | 945,705 | only `00` / `01` | always `00` |
| Prime 2 NX20 | 763,215 | only `00` / `01` | always `00` |
| **Total** | **2,896,556** | **binary** | **always `00`** |

The six NXA Lightmaps still stored as NX10 were included separately because the
NX10 importer also preserves each Lightmap row as four bytes while exposing a
three-column logical field.

Observed row patterns include `00 00 00 00`, `01 01 01 00`, `01 00 01 00`,
`00 01 00 00`, `00 01 01 00`, `01 00 00 00`, `00 00 01 00` and
`01 01 00 00`.

This is strong evidence for three binary light channels plus one reserved or
otherwise non-authorable byte. It is not sufficient evidence to claim what the
fourth byte would mean if a future file used it, so StepNX preserves rather than
interprets it.

## Editor behavior

A Lightmap Timeline has exactly three editable lanes, aligned one-to-one with
raw bytes 0, 1 and 2.

Only two authoring tools have Lightmap meaning:

- **Toggle** changes the targeted channel from zero to one, or any nonzero value
  to zero. It does not read Bank/ID, Function, Visibility, Brain Code, Source
  Slot or other playable-note controls.
- **Select** changes only the cell selection. Ctrl and Shift selection are
  supported, including selections that cross Block/Split boundaries.

A Select-based Lightmap selection supports:

- Cut;
- Copy;
- Paste;
- Delete / erase.

Lightmap clipboards contain one-byte channel values and are deliberately
incompatible with four-byte playable-note clipboards. Paste may cross a
Block/Split boundary because clipboard height counts encoded rows, not musical
ticks.

Other placement tools remain blocked with the existing non-playable-chart
semantics. Bank/ID, Function, Visibility, Brain Code, Source Slot and analogous
playable-note controls are ignored by Lightmap Toggle/Select. Playable-note
transforms such as horizontal/vertical flip and StepEdit Mirror are not exposed
as Lightmap operations.

## Cross-Block row semantics

The same row-order rule used by playable selection applies to Lightmaps. The
active projected Timeline route is flattened as a sequence of encoded rows. A
selection containing four rows in one Block and eight rows in the next contains
twelve rows even if their Beat Splits or timing densities differ. Cut, Copy,
Paste and Delete address those row positions directly.

Only visible/active branch Blocks participate. Alternate route Blocks that are
not projected into the Timeline remain untouched.

## Save and sparsity guarantees

Lightmap edits use stable row IDs and a dedicated atomic command. On compact
source-backed documents, only touched rows become `OverlayRows` replacements;
a one-cell edit must not iterate or materialize the complete Lightmap.

Every edit preserves:

- row stable identity;
- untouched light channels;
- the fourth raw byte;
- Block/Split timing and metadata;
- all unrelated source-backed rows.

The ordinary save/recovery durability gate applies to edited `LM.NX` exactly as
it does to playable NX20 documents.
