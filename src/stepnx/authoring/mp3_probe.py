from __future__ import annotations

from pathlib import Path

_PROBE_BYTES = 256 * 1024
_MPEG1_L3_BITRATES = (
    0,
    32,
    40,
    48,
    56,
    64,
    80,
    96,
    112,
    128,
    160,
    192,
    224,
    256,
    320,
    0,
)
_MPEG2_L3_BITRATES = (
    0,
    8,
    16,
    24,
    32,
    40,
    48,
    56,
    64,
    80,
    96,
    112,
    128,
    144,
    160,
    0,
)
_SAMPLE_RATES = {
    3: (44_100, 48_000, 32_000),
    2: (22_050, 24_000, 16_000),
    0: (11_025, 12_000, 8_000),
}


def _parse_layer3_header(payload: bytes, offset: int) -> tuple[int, int, int] | None:
    if offset < 0 or offset + 4 > len(payload):
        return None
    word = int.from_bytes(payload[offset : offset + 4], "big")
    if word & 0xFFE00000 != 0xFFE00000:
        return None

    version_bits = (word >> 19) & 0x03
    layer_bits = (word >> 17) & 0x03
    bitrate_index = (word >> 12) & 0x0F
    sample_rate_index = (word >> 10) & 0x03
    padding = (word >> 9) & 0x01

    if version_bits == 1 or layer_bits != 1:
        return None
    if bitrate_index in (0, 15) or sample_rate_index == 3:
        return None

    rates = _SAMPLE_RATES.get(version_bits)
    if rates is None:
        return None
    sample_rate = rates[sample_rate_index]
    bitrates = _MPEG1_L3_BITRATES if version_bits == 3 else _MPEG2_L3_BITRATES
    bitrate_kbps = bitrates[bitrate_index]
    if bitrate_kbps <= 0:
        return None

    coefficient = 144_000 if version_bits == 3 else 72_000
    frame_size = coefficient * bitrate_kbps // sample_rate + padding
    if frame_size <= 4:
        return None
    return sample_rate, frame_size, version_bits


def detect_mp3_sample_rate_bytes(payload: bytes) -> int | None:
    """Return the sample rate of a stable MPEG Layer III frame chain.

    A single sync-looking word is not enough because metadata and arbitrary
    binary prefixes can contain false MPEG headers. Three consecutive Layer III
    frames with the same MPEG version and sample rate are required.
    """

    data = bytes(payload)
    limit = max(0, len(data) - 4)
    for offset in range(limit + 1):
        first = _parse_layer3_header(data, offset)
        if first is None:
            continue
        sample_rate, frame_size, version_bits = first
        cursor = offset + frame_size
        valid = True
        for _ in range(2):
            header = _parse_layer3_header(data, cursor)
            if header is None:
                valid = False
                break
            next_rate, next_size, next_version = header
            if next_rate != sample_rate or next_version != version_bits:
                valid = False
                break
            cursor += next_size
        if valid:
            return sample_rate
    return None


def _id3v2_payload_end(header: bytes) -> int:
    if len(header) < 10 or header[:3] != b"ID3":
        return 0
    size_bytes = header[6:10]
    if any(value & 0x80 for value in size_bytes):
        return 0
    size = 0
    for value in size_bytes:
        size = (size << 7) | value
    footer = 10 if header[5] & 0x10 else 0
    return 10 + size + footer


def detect_mp3_sample_rate(path: str | Path) -> int | None:
    """Probe an MP3 file without decoding it or depending on Qt metadata."""

    source = Path(path)
    try:
        with source.open("rb") as stream:
            header = stream.read(10)
            stream.seek(_id3v2_payload_end(header))
            payload = stream.read(_PROBE_BYTES)
    except OSError:
        return None
    return detect_mp3_sample_rate_bytes(payload)
