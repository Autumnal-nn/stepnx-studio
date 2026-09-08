from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Mp3GaplessAnalysis:
    """Gapless timing that FFmpeg derives from a Xing/Info LAME extension.

    ``encoder_delay_samples`` is the 12-bit delay stored by the encoder.
    FFmpeg presents the decoded stream after skipping that delay plus the
    Layer-III decoder delay (528 + 1 samples).  StepNX can compensate the
    resulting presentation-time shift without rewriting the source MP3.
    """

    encoder: str
    encoder_delay_samples: int
    encoder_padding_samples: int
    ffmpeg_start_skip_samples: int
    sample_rate: int

    @property
    def ffmpeg_start_skip_ms(self) -> float:
        if self.sample_rate <= 0:
            raise ValueError("gapless analysis has no valid sample rate")
        return self.ffmpeg_start_skip_samples * 1000.0 / self.sample_rate


_SAMPLE_RATES = {
    3: (44_100, 48_000, 32_000, None),
    2: (22_050, 24_000, 16_000, None),
    0: (11_025, 12_000, 8_000, None),
}


def analyze_ffmpeg_lame_gapless(
    payload: bytes,
    *,
    first_frame_offset: int = 0,
) -> Mp3GaplessAnalysis | None:
    """Return FFmpeg's leading LAME/Xing skip for one MP3, if present.

    This is a byte-level inspection only.  It never mutates the MP3 and does
    not invoke FFmpeg.  The layout mirrors the public Xing/LAME extension that
    FFmpeg's MP3 demuxer reads: the 24-bit delay/padding field stores two
    12-bit values, and FFmpeg adds 528 + 1 decoder-delay samples to the leading
    encoder delay.
    """

    offset = int(first_frame_offset)
    if offset < 0 or offset + 4 > len(payload):
        return None

    word = int.from_bytes(payload[offset : offset + 4], "big")
    if (word >> 21) & 0x7FF != 0x7FF:
        return None

    version = (word >> 19) & 0x03
    layer = (word >> 17) & 0x03
    sample_rate_index = (word >> 10) & 0x03
    mode = (word >> 6) & 0x03

    # MPEG Layer III only.  NXA mastering observed so far is MPEG-1 Layer III,
    # but the Xing side-info offsets for MPEG-2/2.5 are cheap to model safely.
    if version == 1 or layer != 1 or sample_rate_index == 3:
        return None
    sample_rate = _SAMPLE_RATES[version][sample_rate_index]
    if sample_rate is None:
        return None

    mono = mode == 3
    if version == 3:  # MPEG-1
        side_info_bytes = 17 if mono else 32
    else:  # MPEG-2 / 2.5
        side_info_bytes = 9 if mono else 17

    xing = offset + 4 + side_info_bytes
    if xing + 8 > len(payload):
        return None
    marker = payload[xing : xing + 4]
    if marker not in (b"Xing", b"Info"):
        return None

    flags = int.from_bytes(payload[xing + 4 : xing + 8], "big")
    cursor = xing + 8
    if flags & 0x01:  # frame count
        cursor += 4
    if flags & 0x02:  # byte count
        cursor += 4
    if flags & 0x04:  # TOC
        cursor += 100
    if flags & 0x08:  # quality
        cursor += 4

    # FFmpeg reads a 9-byte encoder string followed by 12 bytes of LAME fields
    # before the packed 12-bit encoder-delay / 12-bit padding value.
    if cursor + 24 > len(payload):
        return None
    version_raw = payload[cursor : cursor + 9]
    if version_raw[:4] not in (b"LAME", b"Lavf", b"Lavc"):
        return None

    delay_offset = cursor + 9 + 12
    packed = int.from_bytes(payload[delay_offset : delay_offset + 3], "big")
    encoder_delay = packed >> 12
    encoder_padding = packed & 0x0FFF

    encoder = version_raw.rstrip(b"\0 ").decode("latin-1", errors="replace")
    return Mp3GaplessAnalysis(
        encoder=encoder,
        encoder_delay_samples=encoder_delay,
        encoder_padding_samples=encoder_padding,
        ffmpeg_start_skip_samples=encoder_delay + 528 + 1,
        sample_rate=sample_rate,
    )
