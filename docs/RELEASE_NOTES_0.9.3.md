# StepNX Studio 0.9.3

This update focuses on semantics, chart metadata, presentation, and handling previously unknown or ambiguous fields.

## Note authoring and editor visuals

- FIX: Corrected Roll detection. Hold heads with the `0x10` sustain bit cleared use Roll artwork, while ordinary sustained longs retain normal Hold artwork.
- FIX: Ghost taps and Ghost hold heads now use their normal arrow artwork with a clearer editor-only white outline rather than incorrectly borrowing Roll graphics.
- FIX: Long-note shafts now connect consistently beneath all Hold Heads, including Hidden, Ghost, Invisible, Appear, Vanish, VanishLow and AppearLow variants.
- ADD: Added a dedicated Roll authoring tool. Rolls are now encoded and displayed using the NX20 long-note sustain bit rather than being inferred from Ghost/function bits.
- ADD: Added editor visualization for Hidden, Invisible, Appear, Vanish, VanishLow and AppearLow note states without altering chart data.

## Split selection authoring

- ADD: Split selection bytes can now be edited through a typed UI directly from the chart structure/sidebar.
- ADD: Split entries now show their decoded selection mode and bank in the structure view.

## Metadata

- ADD: Finalized typed Fiesta-and-later semantics for Header IDs `1000` through `1008`.
- ADD: Expanded Fiesta 2 mission trailer labels using runtime and official-corpus evidence.

## Assets

- CHANGE: Replaced the bundled metronome sample with CC0 `BEAT.wav`.
- CHANGE: Replaced the previous bundled arrow graphics with the new six-frame noteskin assets.
- ADD: Bundled noteskins now include proper animation frames, press overlays and gameplay feedback artwork across all included banks.
- ADD: Added asset attribution and licensing information for the bundled noteskins and metronome.

## NX20 compatibility

- ADD: Added corpus-backed documentation for Split selectors, visibility modes, Header `1000..1008`, trailer fields and remaining NX20 unknowns.
- FIX: Prime 2 decorated empty cells such as `00 03 00 00` are preserved byte-for-byte while rendering as empty cells in both editor and gameplay preview.
- CHANGE: Unknown and unusual Split selector values remain round-trip safe even when the typed editor warns that the combination is suspicious.
- CHANGE: Unknown visibility encodings remain raw-preserved instead of being normalized into known modes.
