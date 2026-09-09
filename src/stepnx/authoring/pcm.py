from __future__ import annotations

import hashlib
import math
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

from stepnx.authoring.audio import decode_aud_bytes
from stepnx.authoring.mpeg_crc import layer3_crc_valid
from stepnx.authoring.nxa_startup import (
    NxaStartupAnalysis, NxaStartupError, _parse_header, analyze_nxa_mp3_startup,
)


DECODER_ID = "minimp3-ea99364f61c14656440e8d77e9c233ccf3124633-scalar-s16-v1"
TIMELINE_ID = "nxa-mpeg-pcm-v1"
NXA_OUTPUT_RATE = 48_000
MAX_SOURCE_BYTES = 64 * 1024 * 1024


class PcmDecodeError(ValueError):
    """The source cannot establish a reliable NXA sample timeline."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _trailer_only(tail: bytes) -> bool:
    # These bytes are never silently removed from the source; their count/hash
    # remains in the report. They do not contain complete audio frames.
    if not tail:
        return True
    if tail.startswith(b"TAG") and len(tail) == 128:
        return True
    return len(set(tail)) == 1 and tail[0] in (0, 0xFF, 0x55)


@dataclass(frozen=True, slots=True)
class CanonicalPcm:
    """One immutable S16LE stereo stream for playback, seek and waveform.

    NXA's observed output path consumes frames at 48 kHz. Samples are not
    resampled here. MPEG metadata frames and decoder priming are retained.
    ``startup`` maps this source-frame timeline to NXA chart time; no musical
    onset detection, song IDs, or decoder/backend duration estimates are used.
    """

    samples: bytes
    source_sha256: str
    payload_sha256: str
    mpeg_sample_rate: int
    source_channels: int
    startup: NxaStartupAnalysis
    mpeg_frames: int
    source_start: int
    source_end: int
    trailing_bytes: int
    missing_frame_offsets: tuple[int, ...]

    @property
    def sample_rate(self) -> int:
        return NXA_OUTPUT_RATE

    @property
    def frame_count(self) -> int:
        return len(self.samples) // 4

    @property
    def duration_ms(self) -> float:
        return self.frame_count * 1000.0 / self.sample_rate

    @property
    def startup_offset_ms(self) -> float:
        return self.startup.net_source_lead_samples * 1000.0 / self.sample_rate

    def frame_at_ms(self, milliseconds: float) -> int:
        if not math.isfinite(milliseconds):
            raise ValueError("PCM time must be finite")
        return min(self.frame_count, max(0, math.floor(milliseconds * self.sample_rate / 1000.0)))

    def slice_frames(self, first: int, last: int) -> bytes:
        if not 0 <= first <= last <= self.frame_count:
            raise ValueError("PCM range is outside the decoded stream")
        return self.samples[first * 4:last * 4]

    def report(self) -> dict:
        return {
            "schema": TIMELINE_ID,
            "decoder": DECODER_ID,
            "source_sha256": self.source_sha256,
            "payload_sha256": self.payload_sha256,
            "pcm_sha256": _digest(self.samples),
            "pcm_format": "s16le-stereo",
            "output_sample_rate": self.sample_rate,
            "mpeg_sample_rate": self.mpeg_sample_rate,
            "source_channels": self.source_channels,
            "pcm_frames": self.frame_count,
            "mpeg_frames": self.mpeg_frames,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "trailing_bytes": self.trailing_bytes,
            "missing_frame_offsets": list(self.missing_frame_offsets),
            "duration_ms": self.duration_ms,
            "startup": asdict(self.startup),
            "chart_time_of_pcm_frame_zero_ms": -self.startup_offset_ms,
            "mapping": "chart_ms = pcm_frame * 1000 / 48000 - startup_offset_ms - manual_offset_ms",
            "gapless_trim_samples": 0,
            "resampled": False,
            "startup_recovery_waveform_emulated": False,
            "tail_recovery_waveform_emulated": False,
            "parity": "deterministic sample timeline; runtime and device residual require measurement",
        }

    def write_wav(self, path: str | Path) -> None:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(self.sample_rate)
            output.writeframes(self.samples)


def decode_mp3_pcm(payload: bytes, *, source_sha256: str | None = None) -> CanonicalPcm:
    """Decode a bounded, continuous Layer III chain without backend heuristics.

    Unsupported/recovering audio inside the real source chain fails explicitly.
    The startup compatibility model is allowed to recover in the leading bytes;
    it is not treated as a general-purpose corruption-repair decoder.
    """
    if not payload or len(payload) > MAX_SOURCE_BYTES:
        raise PcmDecodeError("MP3 is empty or exceeds the 64 MiB analysis limit")
    payload = bytes(payload)
    try:
        startup = analyze_nxa_mp3_startup(payload)
    except NxaStartupError as exc:
        raise PcmDecodeError(str(exc)) from exc
    offset = startup.source_start_offset
    first = _parse_header(payload, offset)
    if first is None:
        raise PcmDecodeError("missing source MPEG header")
    frames = 0
    total = 0
    frame_offsets: set[int] = set()
    while offset < len(payload):
        header = _parse_header(payload, offset)
        if header is None or header.error:
            if _trailer_only(payload[offset:]):
                break
            raise PcmDecodeError(f"unmodeled data inside/after MPEG chain at byte {offset}")
        if header.layer != 1 or header.frame_size is None:
            raise PcmDecodeError(f"unsupported MPEG layer/free-format frame at byte {offset}")
        if (header.version, header.sample_rate, header.mode == 3) != (first.version, first.sample_rate, first.mode == 3):
            raise PcmDecodeError(f"MPEG format transition at byte {offset}")
        if offset + header.frame_size > len(payload):
            raise PcmDecodeError(f"truncated MPEG frame at byte {offset}")
        if not layer3_crc_valid(payload, offset, header):
            raise PcmDecodeError(f"MPEG CRC failure at byte {offset}")
        frame_offsets.add(offset - startup.source_start_offset)
        frames += 1
        total += header.samples_per_frame
        offset += header.frame_size
    try:
        from stepnx import _mpeg_pcm
    except ImportError as exc:
        raise PcmDecodeError("The pinned PCM decoder is unavailable. Reinstall StepNX Studio with its native extension.") from exc
    try:
        samples, missing, rate, channels = _mpeg_pcm.decode(payload[startup.source_start_offset:offset], total)
    except ValueError as exc:
        raise PcmDecodeError(str(exc)) from exc
    first_ok = startup.first_decoded_offset - startup.source_start_offset
    if any(item >= first_ok or item not in frame_offsets for item in missing):
        raise PcmDecodeError("PCM decoder could not decode a frame accepted by the startup/source model")
    if rate != startup.sample_rate:
        raise PcmDecodeError("PCM decoder sample rate disagrees with startup analysis")
    return CanonicalPcm(
        samples, source_sha256 or _digest(payload), _digest(payload), rate, channels,
        startup, frames, startup.source_start_offset, offset, len(payload) - offset,
        tuple(missing),
    )


def load_nxa_pcm(path: str | Path) -> CanonicalPcm:
    source = Path(path)
    with source.open("rb") as file:
        original = file.read(MAX_SOURCE_BYTES + 1)
    if len(original) > MAX_SOURCE_BYTES:
        raise PcmDecodeError("audio source exceeds the 64 MiB analysis limit")
    payload = decode_aud_bytes(original) if source.suffix.casefold() in {".aud", ".a"} else original
    return decode_mp3_pcm(payload, source_sha256=_digest(original))
