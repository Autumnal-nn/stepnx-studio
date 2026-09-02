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

Public authoring profiles are:

- `nxa-native`;
- `fiesta2`;
- `prime2`.

Item availability and labels are profile-aware. Unknown or unsupported item
identifiers remain preserved rather than being assigned semantics from another
engine family.

The basic Brain Code selector exposes only documented common values. Source Slot
and remaining raw low-six-bit values are available under Advanced so existing
chart data stays lossless without pretending every value has known semantics.

## Gameplay preview

Gameplay Preview opens as a fixed 640x480 external always-on-top window.
It is synchronized to the shared transport and remains usable without chart
audio. Single uses one centered five-lane field at the same receptor/note pitch
as Double instead of enlarging the five lanes to fill the viewport. Scroll
projection uses that rendered receptor pitch rather than the source atlas tile
size. Event culling returns empty after the chart endpoint instead of
resurrecting final notes.

## Audio

Chart audio accepts MP3, AUD, and A. WAV remains reserved for the metronome.
Temporary `stepnx-aud-*` staging is created lazily only when AUD decoding is
actually required.

Automatic audio loading is deliberately conservative and has subsequently been
expanded beyond the original Phase 10 behavior; current lookup rules are
maintained in README/STATUS rather than frozen here.

## Manual acceptance

The historical Windows validation included:

- external preview fixed at 640x480;
- advanced Source Slot/Brain raw controls;
- Space Play/Pause with and without MP3;
- preview scroll-speed comparison;
- sibling audio auto-load behavior.

Later releases supersede this snapshot where README, STATUS or ROADMAP document
newer behavior.
