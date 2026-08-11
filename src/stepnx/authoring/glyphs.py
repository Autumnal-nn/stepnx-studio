from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_GLYPH_SUFFIXES = frozenset({".png", ".svg"})
KNOWN_GLYPHS = frozenset(
    {
        "tap",
        "hold-head",
        "hold-body",
        "hold-tail",
        "item",
        "division",
        "unknown",
        "lightmap-0",
        "lightmap-1",
        "lightmap-2",
        "lightmap-3",
    }
)


class VisualPackError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VisualPack:
    name: str
    root: Path
    glyphs: tuple[tuple[str, Path], ...]

    def path_for(self, glyph: str) -> Path | None:
        for name, path in self.glyphs:
            if name == glyph:
                return path
        return None


def load_visual_pack(path: str | Path) -> VisualPack:
    """Validate a user-selected local pack without copying it into the project."""

    root = Path(path).resolve()
    manifest = root / "stepnx-visual-pack.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VisualPackError(f"cannot read visual-pack manifest: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise VisualPackError(f"invalid visual-pack JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise VisualPackError("visual-pack manifest must be a JSON object")
    name = payload.get("name")
    entries = payload.get("glyphs")
    if not isinstance(name, str) or not name.strip():
        raise VisualPackError("visual-pack name must be a non-empty string")
    if not isinstance(entries, dict):
        raise VisualPackError("visual-pack glyphs must be a JSON object")

    glyphs: list[tuple[str, Path]] = []
    for glyph, raw_path in entries.items():
        if glyph not in KNOWN_GLYPHS:
            raise VisualPackError(f"unknown glyph name: {glyph}")
        if not isinstance(raw_path, str) or not raw_path:
            raise VisualPackError(f"glyph path for {glyph} must be a non-empty string")
        relative = Path(raw_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise VisualPackError(f"glyph path for {glyph} must stay inside the pack")
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise VisualPackError(f"glyph path for {glyph} escapes the pack") from exc
        if resolved.suffix.lower() not in SUPPORTED_GLYPH_SUFFIXES:
            raise VisualPackError(f"glyph {glyph} must use PNG or SVG")
        if not resolved.is_file():
            raise VisualPackError(f"glyph file does not exist: {relative}")
        glyphs.append((glyph, resolved))
    return VisualPack(name.strip(), root, tuple(sorted(glyphs)))
