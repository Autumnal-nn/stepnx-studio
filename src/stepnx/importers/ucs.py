from __future__ import annotations

from pathlib import Path

from stepnx.core.errors import ParseError
from stepnx.importers.legacy import LegacyBlock, LegacyChart, LegacyDiagnostic, LegacyRow


_UCS_MODES = {
    "single": ("Single", 5),
    "s-performance": ("S-Performance", 5),
    "double": ("Double", 10),
    "d-performance": ("D-Performance", 10),
}
_UCS_NOTES = {".": 0, "X": 1, "M": 2, "H": 3, "W": 4}


def _number(value: str, *, source: str | None, line: int, field: str) -> float:
    try:
        return float(value.strip().replace(",", "."))
    except ValueError as exc:
        raise ParseError(line, f"UCS {field}", f"invalid numeric value {value!r}", source) from exc


def parse_ucs(data: bytes, *, source: str | None = None) -> LegacyChart:
    """Parse UCS format 1 without importing PIUVisual/StepEdit implementation code."""

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError(exc.start, "UCS", "file is not valid UTF-8", source) from exc

    format_version: int | None = None
    mode_name: str | None = None
    columns: int | None = None
    diagnostics: list[LegacyDiagnostic] = []
    controls: list[tuple[str, str]] = []
    blocks: list[LegacyBlock] = []
    header: dict[str, str] | None = None
    rows: list[LegacyRow] = []

    def finish_segment(line_number: int) -> None:
        nonlocal header, rows
        if header is None:
            return
        missing = [name for name in ("bpm", "delay", "beat", "split") if name not in header]
        if missing:
            raise ParseError(
                line_number,
                "UCS timing segment",
                "incomplete timing header: " + ", ".join(missing),
                source,
            )
        bpm = _number(header["bpm"], source=source, line=line_number, field="BPM")
        delay = _number(header["delay"], source=source, line=line_number, field="Delay")
        beat_value = _number(header["beat"], source=source, line=line_number, field="Beat")
        split_value = _number(header["split"], source=source, line=line_number, field="Split")
        if bpm <= 0:
            raise ParseError(line_number, "UCS BPM", "BPM must be greater than zero", source)
        if not beat_value.is_integer() or beat_value <= 0:
            raise ParseError(line_number, "UCS Beat", "Beat must be a positive integer", source)
        if not split_value.is_integer() or split_value <= 0:
            raise ParseError(line_number, "UCS Split", "Split must be a positive integer", source)
        blocks.append(
            LegacyBlock(
                bpm,
                int(beat_value),
                int(split_value),
                delay,
                tuple(rows),
            )
        )
        header = None
        rows = []

    physical_lines = text.splitlines()
    for line_number, physical in enumerate(physical_lines, 1):
        line = physical.strip()
        if not line:
            continue
        if line.startswith(":"):
            body = line[1:]
            if "=" not in body:
                raise ParseError(line_number, "UCS directive", "missing '=' separator", source)
            raw_name, raw_value = body.split("=", 1)
            name = raw_name.strip().casefold()
            value = raw_value.strip()
            if name == "format":
                try:
                    format_version = int(value)
                except ValueError as exc:
                    raise ParseError(line_number, "UCS Format", "Format must be an integer", source) from exc
                if format_version != 1:
                    raise ParseError(line_number, "UCS Format", f"unsupported format version {format_version}", source)
                controls.append(("Format", value))
                continue
            if name == "mode":
                resolved = _UCS_MODES.get(value.casefold())
                if resolved is None:
                    raise ParseError(line_number, "UCS Mode", f"unsupported mode {value!r}", source)
                mode_name, columns = resolved
                controls.append(("Mode", mode_name))
                if "performance" in mode_name.casefold():
                    diagnostics.append(
                        LegacyDiagnostic(
                            "ucs.performance-mode",
                            f"{mode_name} is imported by lane geometry; NX20 projection does not invent a separate performance flag",
                            line_number,
                        )
                    )
                continue
            if name == "bpm":
                finish_segment(line_number)
                header = {"bpm": value}
                continue
            if name in {"delay", "beat", "split"}:
                if header is None:
                    raise ParseError(line_number, f"UCS {raw_name.strip()}", "timing directive appears before BPM", source)
                header[name] = value
                continue
            diagnostics.append(
                LegacyDiagnostic(
                    "ucs.directive.unknown",
                    f"unknown directive {raw_name.strip()!r} preserved as a control",
                    line_number,
                )
            )
            controls.append((raw_name.strip(), value))
            continue

        if header is None:
            raise ParseError(line_number, "UCS row", "note row appears before a BPM segment", source)
        if columns is None or mode_name is None:
            raise ParseError(line_number, "UCS row", "Mode must be declared before note rows", source)
        if len(line) != columns:
            raise ParseError(
                line_number,
                "UCS row",
                f"row width {len(line)} does not match {mode_name} width {columns}",
                source,
            )
        unknown = [char for char in line if char not in _UCS_NOTES]
        if unknown:
            raise ParseError(line_number, "UCS row", f"unsupported note symbol {unknown[0]!r}", source)
        rows.append(LegacyRow(tuple(_UCS_NOTES[char] for char in line), line.encode("ascii")))

    finish_segment(len(physical_lines) + 1)
    if format_version is None:
        raise ParseError(0, "UCS", "missing :Format directive", source)
    if columns is None or mode_name is None:
        raise ParseError(0, "UCS", "missing :Mode directive", source)
    if not blocks:
        raise ParseError(0, "UCS", "missing timing segments", source)

    return LegacyChart(
        "ucs",
        columns,
        tuple(blocks),
        source,
        data,
        tuple(diagnostics),
        tuple(controls),
    )


def load_ucs(path: str | Path) -> LegacyChart:
    source = Path(path)
    return parse_ucs(source.read_bytes(), source=str(source))
