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
