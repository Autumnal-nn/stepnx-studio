"""SSC tag escaping shared with the XSanity exporter.

The low-level exporter escapes characters that can terminate or reopen MSD/SSC
fields. The original importer used ``str.find(';')`` and therefore stopped at
an escaped ``\\;``. Install a scanner that recognizes only unescaped tag
terminators and reverses the exact escape sequences emitted by
``escape_tag_value`` while leaving ordinary backslashes intact.
"""
from __future__ import annotations

import re

from . import ssc as _ssc


def _find_unescaped_semicolon(text: str, start: int) -> int:
    index = start
    while True:
        found = text.find(";", index)
        if found < 0:
            return -1
        slashes = 0
        cursor = found - 1
        while cursor >= start and text[cursor] == "\\":
            slashes += 1
            cursor -= 1
        if slashes % 2 == 0:
            return found
        index = found + 1


def _unescape_tag_value(value: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(value):
        if value.startswith(r"\//", index):
            out.append("//")
            index += 3
            continue
        if (
            value[index] == "\\"
            and index + 1 < len(value)
            and value[index + 1] in "\\#:;"
        ):
            out.append(value[index + 1])
            index += 2
            continue
        out.append(value[index])
        index += 1
    return "".join(out)


def _scan_tags(text: str):
    out = []
    index = 0
    size = len(text)
    while index < size:
        marker = text.find("#", index)
        if marker < 0:
            break
        line_start = text.rfind("\n", 0, marker) + 1
        comment = text.find("//", line_start, marker)
        if comment >= 0:
            newline = text.find("\n", marker)
            index = size if newline < 0 else newline + 1
            continue
        colon = text.find(":", marker + 1)
        if colon < 0:
            break
        name = text[marker + 1 : colon].strip()
        if not name or any(character in name for character in "\r\n;#"):
            index = marker + 1
            continue

        semi = _find_unescaped_semicolon(text, colon + 1)
        next_match = re.search(r"\n\s*#", text[colon + 1 :])
        next_tag = colon + 1 + next_match.start() if next_match else -1
        if next_tag >= 0 and (semi < 0 or next_tag < semi):
            value = _unescape_tag_value(text[colon + 1 : next_tag])
            out.append(_ssc._Tag(name.upper(), value, marker))
            index = next_tag + 1
            continue
        if semi < 0:
            value = _unescape_tag_value(text[colon + 1 :])
            out.append(_ssc._Tag(name.upper(), value, marker))
            break
        value = _unescape_tag_value(text[colon + 1 : semi])
        out.append(_ssc._Tag(name.upper(), value, marker))
        index = semi + 1
    return out


def install_ssc_escape_support() -> None:
    _ssc._scan_tags = _scan_tags


__all__ = ["install_ssc_escape_support"]
