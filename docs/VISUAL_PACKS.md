# Local visual packs

StepNX Studio ships an original vector glyph set drawn by Qt. It does not ship
sprites from Pump It Up, StepEdit, STEPEdit-pixi, WebPrime, or other projects.

A user may select a local visual-pack folder for private use. The folder needs
a UTF-8 `stepnx-visual-pack.json` manifest:

```json
{
  "name": "My local pack",
  "glyphs": {
    "tap": "tap.svg",
    "hold-head": "hold-head.png",
    "hold-body": "hold-body.png",
    "hold-tail": "hold-tail.png",
    "item": "item.svg",
    "division": "division.svg",
    "unknown": "unknown.svg"
  }
}
```

Lightmap channels may use `lightmap-0` through `lightmap-3`. Every referenced
file must be a PNG or SVG inside the selected folder. Missing glyphs fall back
to the built-in vector set. The application validates paths and never copies a
selected pack into the repository, workspace, recovery store, or release.

Selecting a pack does not grant permission to redistribute its assets. The
user remains responsible for the rights to any locally selected files.

## Noteskin atlases

The desktop application ships with a royalty-free static authoring pack for
banks `00` through `05`, Division cells, and standard Item cells. A local
`noteskin` directory overrides that pack when it is selected through
**File → Load local noteskin atlases**, or when `./noteskin` exists at startup.
The local directory is ignored by Git and is never copied into a chart
workspace or recovery snapshot.

Each two-digit bank directory (`00`, `01`, and so on) may contain a static
`0.png` or a complete six-frame animation named `0.png` through `5.png`. Each
frame is a `480×288` sheet of `96×96` tiles arranged as five lanes by three note
variants. The authoring viewport deliberately uses frame zero; gameplay-speed
animation is not part of authoring semantics.

Atlas row 1 supplies normal tap heads and row 2 supplies the ghost variant.
Atlas row 0 supplies the complete tail cell and the narrow repeatable shaft
strip; row 1 supplies the head artwork. The head shaft is clipped to begin at
the artwork's detected lower opaque edge, while the complete tail cell already
limits its shaft to the area above the tail. Hold-body cells stretch the narrow
strip while preserving its transparent per-direction offsets.

The following gameplay-feedback resources are optional and used by gameplay
preview:

- `6.png`, `BASE.png`, `HD1.png`, and `HD2.png`: `480×192` feedback sheets.
  The central 384 px of the first `BASE.png` row is projected as one five-pitch
  strip; its 48 px edge regions are empty atlas padding. Two Double strips are
  placed directly adjacent without a Versus gap or overlap;
- one complete `STEPFX<number>_0.png` through `_4.png` sequence at `512×512`;

Two additional atlas groups are optional; when present, the authoring viewport
uses them for typed Division and item cells:

- `DIVISION/0.png`: a `480×96` five-tile Division sheet;
- `ITEM/0.png`, or the complete sequence through `5.png`: `3072×192` sheets
  with 32 item columns;
- `ITEM/SPECIAL.png`: a `3072×288` special-item sheet.

If an animated sequence is present, it must be complete and dimensionally
valid. `ITEM/SPECIAL.png` is optional; its absence only leaves special-item
previews on the typed fallback. Asset provenance is recorded in
`src/stepnx/assets/ASSETS.md`.
