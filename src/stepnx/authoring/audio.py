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
    """Raised when an Andamiro AUD wrapper cannot be decoded safely."""


_BIT_REVERSE = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))
_ENCDECRYPT_PROFILE = bytes.fromhex("000000001c1d1e1f3c3e383a585b5e59")
_ENC2_ZERO_SCAN_LIMIT = 64 * 1024
_ENC2_TAIL_SCAN_SIZE = 1024
_ENC2_UNIFORM_BLOCKS = 4
_MP3_LEADING_ZERO_PADDING = 576
_MP3_PROBE_SIZE = _MP3_LEADING_ZERO_PADDING + 16

# Static 1024-byte ENC1 table used by both ENCDecrypt.exe and ENCEncrypt.exe.
# The official decryptor indexes it with (start_index + payload_index) & 0x3ff
# after reversing the ciphertext byte's bit order.
_ENC1_TABLE = bytes.fromhex(
    "aeb384c2f09287b9e7a80d52eb1dea70d76bcca956dc734543f304e6e857a7b5"
    "60e653cccf959d9b83beb2b414362e9f75250ec87b3a2f0638d0a48612ec897d"
    "13a0d08e7d6dab2f3b03d2e1e4a656cf4ac6e7c1f5116ba500b5eb456046e5f9"
    "279cba64e3ed98831a0011204b101fc1d52f434d4072841830db8a42e9e87a2f"
    "2c6db6e172380955103e9f4bb142790d4b6d6ea1c235d6f5c7705d485805a8a9"
    "9069ae78ea2ac5c327918d34287e2743d5af560896f72d71d25a6818edd501e8"
    "3fb788e0dea65e1e8324fa62713db5bb6c7d48580dd4436fc9e505a597ac6e0f"
    "5a7afeb8d8369ac0822621e418677e4df995abc27b5265927324d6612c7981f7"
    "351bc297e35e58e15113664af0a186495580eabe07679b4164da94c503395b4a"
    "925b02667c7fdcb25dbff616637d31b9650a7875e2bd454f96d14e161aa26c1d"
    "0999c84ea166eee91ee011502c08dec3204697c5df4547fbf7ad0c3a19e1fbde"
    "602b11f69125f5ff8ef2460aeed9193937e299ed0ce0416949050ba5bf2e5fef"
    "3942540f164ff1cd87361c613806fa73dea2ba956bd365c715d77c13f22887b6"
    "02480399b09363053a8fc7bd061506bec535ac7e7012a42de7c9fd3cce8b767f"
    "a2511240e99b93b2d2792bf9ebb8bd9dca32ebe88b9d950424a35fd9f2070039"
    "9f210caba9dbd48df7bb336baf59e3e486259342c14c64fea4a55b344e635c78"
    "26ad26e070281f9d4bb024cc0476895568aa943dcbba238ab8c9bba98c3477fd"
    "caef328a5a533c91b7908088822bb2dda718a0ca41bcb8c48b90170f1934fda1"
    "9e1c30b07f1c292a6ccbf8ee1e09588dcab72add0b15fccd07dcd427b60ab65c"
    "d0f1fb1d62bfbf5f3a6fd74e1c3ed17417b58cfb5ad740c0f47a85281b3e23d9"
    "d8256aaf030e30f473d2a78bd4ee8fab01479fd0cb8a8721efbc596923a091ce"
    "a8e60b8489da685fd308c682891a3117aef1e6820eb35e9a30ce7ffa01943df1"
    "98ffd372f3102976c092e90af099aa2e7acd32cf5d0bfdf8d6bacc9cfc67aec8"
    "b3e755be0dc7097b0261a0e5853380b066442d54c629a3335b7159a6ececdf77"
    "14575d6d13db71076af898edf5d577d6474a77aa81c4f80f3fac686e74794def"
    "57f3153f3d96dfda9ac91e5322503b6e83467c1f4ce22e7854c122f32a48d85c"
    "b1546af6ff8419ea009467dc901723c3f2260180621ae55333ce9e10cf14224d"
    "b46f3bff632b513186addfbb123c591444c3fab7b45e3269360ce438081d96e2"
    "da0e9ccb49ec20623e6fb975af169add6cbcbdf93b64db21bcb1fe8f9b8898ad"
    "8d4cd8377ba31fc4c48eb4fc85a7743ffcd98172f6224f414988a256c65c8157"
    "02fe504fa32c40e33175d11b9e2d6552d1aa1b37448cc83c5047dd29b39c6a35"
    "b1518ef04420a837f452a68560a497747c93768cc09eac618fd37e044ccdb9f4"
)

# Original Linux NXA ENC2 wrappers do not share one fixed profile. A paired
# Windows/Linux corpus showed per-file profiles but stable mastering prefixes.
# Those prefixes recover all 16 profile lanes from the first 16 plaintext bytes.
_NXA_MP3_SIGNATURES = (
    b"\xff\xfb\xb4D" + b"\x00" * 32 + b"Info",
    b"\xff\xfb\xb4d" + b"\x00" * 32 + b"Info",
    bytes.fromhex(
        "4944330300000000086754495432000000010000005450453100000001000000"
        "54414c4200000001"
    ),
    bytes.fromhex(
        "4944330300000000077647454f4200000019000000000053664d61726b657273"
        "000c000000640000"
    ),
)


def _looks_like_mp3_at_start(payload: bytes) -> bool:
    if payload.startswith(b"ID3") and len(payload) >= 10:
        return payload[3] in (2, 3, 4) and not any(
            byte & 0x80 for byte in payload[6:10]
        )
    return len(payload) >= 4 and payload[0] == 0xFF and payload[1] & 0xE0 == 0xE0


def _looks_like_mp3(payload: bytes) -> bool:
    if _looks_like_mp3_at_start(payload):
        return True
    # Some official NXA assets contain exactly one 576-byte all-zero encoded
    # frame-sized prefix before the first real MP3 frame. FFmpeg skips it, and
    # the Windows ENCDecrypt output preserves it byte-for-byte.
    return (
        len(payload) >= _MP3_LEADING_ZERO_PADDING + 4
        and payload[:_MP3_LEADING_ZERO_PADDING]
        == b"\x00" * _MP3_LEADING_ZERO_PADDING
        and _looks_like_mp3_at_start(payload[_MP3_LEADING_ZERO_PADDING:])
    )


def _decode_enc1_source(source: bytes) -> bytes:
    if len(source) < 0x8A or source[:4].upper() != b"ENC1":
        raise AudDecodeError("AUD is not an ENC1 stream")
    encoded_size = struct.unpack_from("<I", source, 0x7E)[0]
    payload_size = encoded_size ^ 0xCCBB
    skip = struct.unpack_from("<I", source, 0x82)[0]
    start_offset = 0x86 + skip
    payload_offset = start_offset + 4
    payload_end = payload_offset + payload_size
    if payload_size <= 0 or start_offset + 4 > len(source) or payload_end > len(source):
        raise AudDecodeError("ENC1 AUD header points outside the file")
    start_index = struct.unpack_from("<I", source, start_offset)[0]
    encrypted_payload = source[payload_offset:payload_end]
    decoded = bytes(
        _BIT_REVERSE[value] ^ _ENC1_TABLE[(start_index + index) & 0x3FF]
        for index, value in enumerate(encrypted_payload)
    )
    if not _looks_like_mp3(decoded):
        raise AudDecodeError("ENC1 AUD decoded payload is not MP3")
    return decoded


def decode_enc1_aud(path: str | Path) -> bytes:
    """Decode the ENC1 AUD format implemented by the official Andamiro tool."""
    try:
        source = Path(path).read_bytes()
    except OSError as exc:
        raise AudDecodeError(f"cannot read AUD: {exc}") from exc
    return _decode_enc1_source(source)


def _enc2_key_stream(encrypted_table: bytes, profile: bytes) -> bytes:
    return bytes(
        value ^ profile[index & 15]
        for index, value in enumerate(encrypted_table)
    )


def _decode_enc2_bytes(
    encrypted_payload: bytes,
    key_stream: bytes,
    start_index: int,
    *,
    limit: int | None = None,
) -> bytes:
    payload = encrypted_payload if limit is None else encrypted_payload[:limit]
    return bytes(
        _BIT_REVERSE[value] ^ key_stream[(start_index + index) & 1023]
        for index, value in enumerate(payload)
    )


def _recover_profile_from_signature(
    signature: bytes,
    key: bytes,
    encrypted_table: bytes,
    encrypted_payload: bytes,
    start_index: int,
) -> bytes | None:
    if len(signature) < 16 or len(encrypted_payload) < len(signature):
        return None
    effective = bytearray(16)
    for index, plain in enumerate(signature[:16]):
        stream_index = (start_index + index) & 1023
        lane = stream_index & 15
        effective[lane] = (
            _BIT_REVERSE[encrypted_payload[index]]
            ^ plain
            ^ encrypted_table[stream_index]
        )
    return bytes(value ^ key[index] for index, value in enumerate(effective))


def _try_enc2_profile(
    base_profile: bytes,
    key: bytes,
    encrypted_table: bytes,
    encrypted_payload: bytes,
    start_index: int,
    *,
    signature: bytes | None = None,
) -> bytes | None:
    profile = bytes(left ^ right for left, right in zip(base_profile, key))
    key_stream = _enc2_key_stream(encrypted_table, profile)
    probe_size = (
        len(signature)
        if signature is not None
        else min(_MP3_PROBE_SIZE, len(encrypted_payload))
    )
    probe = _decode_enc2_bytes(
        encrypted_payload,
        key_stream,
        start_index,
        limit=probe_size,
    )
    if signature is not None:
        if probe != signature:
            return None
    elif not _looks_like_mp3(probe):
        return None
    decoded = _decode_enc2_bytes(encrypted_payload, key_stream, start_index)
    return decoded if _looks_like_mp3(decoded) else None


def _profile_assuming_zero_block(
    offset: int,
    key: bytes,
    encrypted_table: bytes,
    encrypted_payload: bytes,
    start_index: int,
) -> bytes:
    """Recover the base profile assuming 16 plaintext bytes are all zero."""
    effective = bytearray(16)
    for index in range(16):
        stream_index = (start_index + offset + index) & 1023
        lane = stream_index & 15
        effective[lane] = (
            _BIT_REVERSE[encrypted_payload[offset + index]]
            ^ encrypted_table[stream_index]
        )
    return bytes(value ^ key[index] for index, value in enumerate(effective))


def _recover_enc2_from_zero_run(
    key: bytes,
    encrypted_table: bytes,
    encrypted_payload: bytes,
    start_index: int,
) -> bytes | None:
    """Recover per-file ENC2 profile from a 32-byte zero run near the start."""
    prefix_size = min(len(encrypted_payload), _ENC2_ZERO_SCAN_LIMIT + 32)
    masked = bytes(
        _BIT_REVERSE[encrypted_payload[index]]
        ^ encrypted_table[(start_index + index) & 1023]
        ^ key[(start_index + index) & 15]
        for index in range(prefix_size)
    )
    stop = min(_ENC2_ZERO_SCAN_LIMIT, max(0, len(masked) - 32))
    attempted: set[bytes] = set()
    for offset in range(stop + 1):
        if masked[offset : offset + 16] != masked[offset + 16 : offset + 32]:
            continue
        base_profile = _profile_assuming_zero_block(
            offset,
            key,
            encrypted_table,
            encrypted_payload,
            start_index,
        )
        if base_profile in attempted:
            continue
        attempted.add(base_profile)
        decoded = _try_enc2_profile(
            base_profile,
            key,
            encrypted_table,
            encrypted_payload,
            start_index,
        )
        if decoded is not None:
            return decoded
    return None


def _recover_enc2_from_uniform_tail(
    key: bytes,
    encrypted_table: bytes,
    encrypted_payload: bytes,
    start_index: int,
) -> bytes | None:
    """Recover a profile from long constant-byte padding near the MP3 tail.

    A constant plaintext byte repeated for at least four 16-byte profile periods
    appears as four identical masked blocks. Assuming that byte is zero recovers
    the real profile XOR one uniform byte. The MP3 prefix determines that final
    byte, so no song-specific profile or mastering signature is required.
    """
    block_size = 16
    run_size = block_size * _ENC2_UNIFORM_BLOCKS
    if len(encrypted_payload) < run_size:
        return None

    region_start = max(0, len(encrypted_payload) - _ENC2_TAIL_SCAN_SIZE - run_size)
    masked = bytes(
        _BIT_REVERSE[encrypted_payload[offset]]
        ^ encrypted_table[(start_index + offset) & 1023]
        ^ key[(start_index + offset) & 15]
        for offset in range(region_start, len(encrypted_payload))
    )
    attempted: set[bytes] = set()
    stop = len(masked) - run_size
    for local_offset in range(stop + 1):
        first = masked[local_offset : local_offset + block_size]
        if any(
            masked[
                local_offset + block_size * block
                : local_offset + block_size * (block + 1)
            ]
            != first
            for block in range(1, _ENC2_UNIFORM_BLOCKS)
        ):
            continue

        offset = region_start + local_offset
        base_zero = _profile_assuming_zero_block(
            offset,
            key,
            encrypted_table,
            encrypted_payload,
            start_index,
        )
        zero_profile = bytes(left ^ right for left, right in zip(base_zero, key))
        zero_stream = _enc2_key_stream(encrypted_table, zero_profile)
        probe_zero = _decode_enc2_bytes(
            encrypted_payload,
            zero_stream,
            start_index,
            limit=min(_MP3_PROBE_SIZE, len(encrypted_payload)),
        )
        if not probe_zero:
            continue

        # If the tail byte is C, the zero-assumption decodes every payload byte
        # as plaintext XOR C. These three candidates cover ID3, raw MPEG sync,
        # and the official 576-byte all-zero leading pad respectively.
        constants = {
            probe_zero[0] ^ ord("I"),
            probe_zero[0] ^ 0xFF,
            probe_zero[0],
        }
        for constant in constants:
            base_profile = bytes(value ^ constant for value in base_zero)
            if base_profile in attempted:
                continue
            attempted.add(base_profile)
            decoded = _try_enc2_profile(
                base_profile,
                key,
                encrypted_table,
                encrypted_payload,
                start_index,
            )
            if decoded is not None:
                return decoded
    return None


def _decode_enc2_source(source: bytes) -> bytes:
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

    decoded = _try_enc2_profile(
        _ENCDECRYPT_PROFILE,
        key,
        encrypted_table,
        encrypted_payload,
        start_index,
    )
    if decoded is not None:
        return decoded

    attempted: set[bytes] = {_ENCDECRYPT_PROFILE}
    for signature in _NXA_MP3_SIGNATURES:
        base_profile = _recover_profile_from_signature(
            signature,
            key,
            encrypted_table,
            encrypted_payload,
            start_index,
        )
        if base_profile is None or base_profile in attempted:
            continue
        attempted.add(base_profile)
        decoded = _try_enc2_profile(
            base_profile,
            key,
            encrypted_table,
            encrypted_payload,
            start_index,
            signature=signature,
        )
        if decoded is not None:
            return decoded

    decoded = _recover_enc2_from_zero_run(
        key,
        encrypted_table,
        encrypted_payload,
        start_index,
    )
    if decoded is not None:
        return decoded

    decoded = _recover_enc2_from_uniform_tail(
        key,
        encrypted_table,
        encrypted_payload,
        start_index,
    )
    if decoded is not None:
        return decoded

    raise AudDecodeError(
        "ENC2 AUD uses an unsupported key profile or MP3 mastering signature"
    )


def decode_aud(path: str | Path) -> bytes:
    """Decode supported ENC1 or ENC2 AUD wrappers to MP3 bytes."""
    try:
        source = Path(path).read_bytes()
    except OSError as exc:
        raise AudDecodeError(f"cannot read AUD: {exc}") from exc
    magic = source[:4].upper()
    if magic == b"ENC1":
        return _decode_enc1_source(source)
    if magic == b"ENC2":
        return _decode_enc2_source(source)
    raise AudDecodeError("AUD is not an ENC1 or ENC2 stream")


def decode_enc2_aud(path: str | Path) -> bytes:
    """Backward-compatible AUD decoder entry point.

    Historically this public function was named for ENC2 because ENC1 had not
    yet been reverse engineered. It now dispatches both formats so existing GUI
    and callers gain ENC1 support without a compatibility break.
    """
    return decode_aud(path)


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
            if block.bpm <= 0 or block.beat_split <= 0:
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
            if block.bpm <= 0 or block.beat_split <= 0:
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
