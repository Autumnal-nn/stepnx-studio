from __future__ import annotations

from pathlib import Path


def bundled_noteskin_root() -> Path:
    """Return the installed royalty-free authoring noteskin directory."""

    return Path(__file__).with_name("assets") / "noteskin"


def bundled_metronome_path() -> Path:
    """Return the installed default PCM metronome sample."""

    return Path(__file__).with_name("assets") / "BEAT.WAV"
