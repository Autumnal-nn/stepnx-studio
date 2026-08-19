from __future__ import annotations

import math
import struct
import wave
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

from stepnx.authoring.snapshot import AuthoringSnapshot
from stepnx.core.model import EmptyRow, LightmapRow, PackedNoteRow


class WaveformError(ValueError):
    """Raised when an audio file cannot provide a safe waveform projection."""


class AudDecodeError(ValueError):
    """Raised when an Andamiro ENC2 AUD cannot be decoded safely."""


_BIT_REVERSE = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))
_ENCDECRYPT_PROFILE = bytes.fromhex("000000001c1d1e1f3c3e383a585b5e59")


def _looks_like_mp3(payload: bytes) -> bool:
    if payload.startswith(b"ID3") and len(payload) >= 10:
        return payload[3] in (2, 3, 4) and not any(
            byte & 0x80 for byte in payload[6:10]
        )
    return len(payload) >= 4 and payload[0] == 0xFF and payload[1] & 0xE0 == 0xE0


def decode_enc2_aud(path: str | Path) -> bytes:
    """Decode the self-contained ENC2 profile used by ENCDecrypt.exe.

    Some ENC2 files use a different machine/HASP-derived profile. Those are
    rejected after decoding instead of returning plausible-looking garbage.
    """
    try:
        source = Path(path).read_bytes()
    except OSError as exc:
        raise AudDecodeError(f"cannot read AUD: {exc}") from exc
    if len(source) < 156 or source[:4].upper() != b"ENC2":
        raise AudDecodeError("AUD is not an ENC2 stream")
    payload_size, skip = struct.unpack_from("<II", source, 0x84)
    key = source[0x8C:0x9C]
    table_offset = 0x9C + skip
    payload_offset = table_offset + 4 + 1024
    payload_end = payload_offset + payload_size
    if payload_size <= 0 or payload_end > len(source):
        raise AudDecodeError("ENC2 AUD header points outside the file")
    start_index = struct.unpack_from("<I", source, table_offset)[0]
    encrypted_table = source[table_offset + 4 : payload_offset]
    encrypted_payload = source[payload_offset:payload_end]
    profile = bytes(left ^ right for left, right in zip(_ENCDECRYPT_PROFILE, key))
    key_stream = bytes(
        value ^ profile[index & 15]
        for index, value in enumerate(encrypted_table)
    )
    decoded = bytes(
        _BIT_REVERSE[value] ^ key_stream[(start_index + index) & 1023]
        for index, value in enumerate(encrypted_payload)
    )
    if not _looks_like_mp3(decoded):
        raise AudDecodeError(
            "ENC2 AUD uses an unsupported key profile; decoded payload is not MP3"
        )
    return decoded


@dataclass(frozen=True, slots=True)
class WaveformEnvelope:
    duration_ms: float
    peaks: tuple[float, ...]

    def __post_init__(self) -> None:
        if not math.isfinite(self.duration_ms) or self.duration_ms < 0:
            raise ValueError("waveform duration must be finite and non-negative")
        if any(not 0.0 <= peak <= 1.0 for peak in self.peaks):
            raise ValueError("waveform peaks must be normalized")

    def amplitude_at(self, time_ms: float) -> float:
        if not self.peaks or self.duration_ms <= 0 or time_ms < 0:
            return 0.0
        fraction = min(1.0, time_ms / self.duration_ms)
        index = min(len(self.peaks) - 1, int(fraction * len(self.peaks)))
        return self.peaks[index]


def estimate_bpm(
    waveform: WaveformEnvelope, *, minimum: float = 60.0, maximum: float = 220.0
) -> float:
    """Estimate tempo by normalized autocorrelation of the waveform envelope.

    The result is advisory: half/double-time ambiguity cannot be eliminated
    reliably, so UI callers must confirm it before modifying chart timing.
    """
    if not 0 < minimum < maximum or not waveform.peaks or waveform.duration_ms <= 0:
        raise WaveformError("BPM estimation needs a non-empty waveform and valid range")
    interval_ms = waveform.duration_ms / len(waveform.peaks)
    mean = sum(waveform.peaks) / len(waveform.peaks)
    signal = tuple(max(0.0, value - mean) for value in waveform.peaks)
    if not any(signal):
        raise WaveformError("waveform has no usable rhythmic variation")
    first_lag = max(1, round(60_000.0 / (maximum * interval_ms)))
    last_lag = min(len(signal) // 2, round(60_000.0 / (minimum * interval_ms)))
    if first_lag > last_lag:
        raise WaveformError("waveform is too short for the requested BPM range")
    best_lag = first_lag
    best_score = float("-inf")
    for lag in range(first_lag, last_lag + 1):
        left, right = signal[:-lag], signal[lag:]
        numerator = sum(a * b for a, b in zip(left, right))
        denominator = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
        score = numerator / denominator if denominator else 0.0
        score += 1e-8 / lag
        if score > best_score:
            best_score, best_lag = score, lag
    return 60_000.0 / (best_lag * interval_ms)


def _sample(data: bytes, offset: int, width: int) -> float:
    if width == 1:
        return abs(data[offset] - 128) / 128.0
    if width == 2:
        return abs(struct.unpack_from("<h", data, offset)[0]) / 32768.0
    if width == 3:
        raw = int.from_bytes(data[offset : offset + 3], "little", signed=False)
        if raw & 0x800000:
            raw -= 0x1000000
        return abs(raw) / 8388608.0
    if width == 4:
        return abs(struct.unpack_from("<i", data, offset)[0]) / 2147483648.0
    raise WaveformError(f"unsupported PCM sample width: {width}")


def load_pcm_wav_waveform(
    path: str | Path, *, buckets: int = 4096
) -> WaveformEnvelope:
    if buckets <= 0:
        raise ValueError("waveform bucket count must be positive")
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            width = source.getsampwidth()
            rate = source.getframerate()
            frames = source.getnframes()
            compression = source.getcomptype()
            if compression != "NONE":
                raise WaveformError(f"compressed WAV is unsupported: {compression}")
            if channels <= 0 or rate <= 0:
                raise WaveformError("WAV has invalid channel or sample-rate metadata")
            payload = source.readframes(frames)
    except (OSError, EOFError, wave.Error) as exc:
        raise WaveformError(f"cannot read PCM WAV: {exc}") from exc

    frame_width = channels * width
    if frame_width <= 0 or len(payload) < frames * frame_width:
        raise WaveformError("WAV payload is truncated")
    count = min(buckets, max(1, frames))
    peaks = [0.0] * count
    for frame in range(frames):
        bucket = min(count - 1, frame * count // max(1, frames))
        base = frame * frame_width
        peak = max(_sample(payload, base + channel * width, width) for channel in range(channels))
        peaks[bucket] = max(peaks[bucket], peak)
    return WaveformEnvelope(frames * 1000.0 / rate, tuple(peaks))


@dataclass(frozen=True, slots=True)
class AudioAlignment:
    """Session-only mapping; positive offset starts chart time later in audio."""

    offset_ms: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.offset_ms):
            raise ValueError("audio offset must be finite")

    def chart_to_audio(self, chart_time_ms: float) -> float:
        return chart_time_ms + self.offset_ms

    def audio_to_chart(self, audio_time_ms: float) -> float:
        return audio_time_ms - self.offset_ms


@dataclass(frozen=True, slots=True)
class MetronomeBeat:
    block_id: int
    beat_index: int
    is_measure: bool


@dataclass(frozen=True, slots=True)
class MetronomeNote:
    block_id: int
    row_index: int


class MetronomeClock:
    """Maps chart time to beat identity without accumulating timer drift."""

    def __init__(self, snapshot: AuthoringSnapshot) -> None:
        blocks = []
        for split in snapshot.splits:
            if not split.blocks:
                continue
            block = snapshot.active_block(split.stable_id)
            if (
                block.bpm <= 0
                or block.beat_split <= 0
            ):
                continue
            end = block.start_time + block.row_count * 60_000.0 / (
                block.bpm * block.beat_split
            )
            blocks.append((block.start_time, end, block))
        self._blocks = tuple(blocks)

    def beat_at(self, chart_time_ms: float) -> MetronomeBeat | None:
        for start, end, block in self._blocks:
            if start <= chart_time_ms <= end:
                beat_duration = 60_000.0 / block.bpm
                beat = max(0, int((chart_time_ms - start) // beat_duration))
                return MetronomeBeat(
                    block.stable_id,
                    beat,
                    block.beat_measure > 0 and beat % block.beat_measure == 0,
                )
        return None


class NoteMetronomeClock:
    """Maps time to the latest tap/hold-head row on the active route.

    A chord is one audible event. Hold bodies and tails are deliberately not
    events, otherwise a sustained note degenerates into a machine-gun click.
    """

    def __init__(self, snapshot: AuthoringSnapshot) -> None:
        events = []
        for split in snapshot.splits:
            if not split.blocks:
                continue
            block = snapshot.active_block(split.stable_id)
            if (
                block.bpm <= 0
                or block.beat_split <= 0
            ):
                continue
            row_duration = 60_000.0 / (block.bpm * block.beat_split)
            for row_index, row in enumerate(block.rows):
                if isinstance(row, (EmptyRow, LightmapRow)):
                    continue
                cells = (
                    (row.cell(lane) for lane in range(row.cell_count))
                    if isinstance(row, PackedNoteRow)
                    else row.cells
                )
                if any(
                    cell.note_type in (0x3, 0x7) and cell.raw[0] & 0x40
                    for cell in cells
                ):
                    events.append(
                        (
                            block.start_time + row_index * row_duration,
                            MetronomeNote(block.stable_id, row_index),
                        )
                    )
        events.sort(key=lambda item: item[0])
        self._times = tuple(item[0] for item in events)
        self._events = tuple(item[1] for item in events)

    def note_at(self, chart_time_ms: float) -> MetronomeNote | None:
        index = bisect_right(self._times, chart_time_ms) - 1
        return None if index < 0 else self._events[index]
