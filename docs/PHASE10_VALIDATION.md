# Phase 10 validation

## Authoring and input

- Toggle is the default note tool: empty click places a Tap, vertical drag
  creates a complete Hold, and clicking an existing note removes it.
- Tap remains an explicit overwrite tool.
- Shift extends rectangular selection; Ctrl toggles individual cells.
- Clicking outside the chart clears the current selection.
- Space toggles Play/Pause even when no chart audio is loaded.
- Positive Scroll uses the same row geometry in Pause and Play. Beat Split
  contributes through rows-per-beat rather than multiplying row height.
- Mouse-wheel scrolling remains half of the active split beat.

## Split and Block editing

The chart context menu exposes Split Here, Merge Splits, Resize Split, and
Block create/duplicate/delete actions. Resize accepts Measure|Beat|Row
coordinates. Absolute Start Time for later Blocks is hidden unless
`Show advanced Split timing` is enabled; Offset/Delay remains editable.

## Profile-aware note authoring

Profiles available in the GUI:

- `nxa-native`;
- `fiesta2`;
- `prime2`;
- `nxa-step5-patched`.

Item IDs 21-23 are hidden in native NXA and exposed in Fiesta 2, Prime 2, and
patched NXA. Known names are Random Velocity, Death / Nuclear, and Hyper
Potion.

The basic Brain Code selector exposes only 00, 01, 06, and 07. Source Slot
and the remaining raw low-six-bit values are available under Advanced.

## Patched-NXA SPECIAL support

```text
SPECIAL cell:  01 03 (64+cell) (SourceSlot<<6)        cell 0..96
Number Block:  02 03 (100+n)   ((SourceSlot<<6)|01)  n 00..99
```

SPECIAL.PNG is indexed row-major. Number Blocks are rendered by composing
the tens and units cells from the same atlas. Physical artwork is drawn only
when the loaded atlas actually contains the referenced cell.

## Gameplay preview

Gameplay Preview opens as a fixed 640x480 external always-on-top window.
It is synchronized to the shared transport and remains usable without chart
audio. Single uses one centered five-lane field at the same receptor/note pitch
as Double instead of enlarging the five lanes to fill the viewport. Scroll
projection uses that rendered receptor pitch rather than the source atlas tile
size, matching PIUTESTER/arcade spacing at 4x in the validated 640x480 Double
comparison. Event culling returns empty after the chart endpoint instead of
resurrecting final notes.

## Audio

Chart audio accepts MP3, AUD, and A. WAV remains reserved for the metronome.
Temporary `stepnx-aud-*` staging is created lazily only when AUD decoding is
actually required.

Automatic audio loading is deliberately strict. Opening a chart folder
`<FolderName>` checks only for the sibling `<FolderName>.mp3`. If it does not
exist, no chart audio is loaded automatically.

## Manual acceptance

The final Windows validation included:

- SPECIAL atlas picker and composed Number Blocks;
- external preview fixed at 640x480;
- advanced Source Slot/Brain raw controls;
- Space Play/Pause with and without MP3;
- PIUTESTER comparison for preview scroll speed;
- exact sibling MP3 auto-load behavior.
