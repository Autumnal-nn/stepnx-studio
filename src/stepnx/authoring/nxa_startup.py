from __future__ import annotations

from dataclasses import dataclass


class NxaStartupError(ValueError):
    """Raised when MP3 startup cannot be modeled safely for the NXA runtime."""


@dataclass(frozen=True, slots=True)
class NxaStartupRecovery:
    error: str
    offset: int
    synthesized_samples: int


@dataclass(frozen=True, slots=True)
class NxaStartupAnalysis:
    source_start_offset: int
    first_decoded_offset: int
    source_samples_before_first_decoded: int
    synthesized_samples_before_first_decoded: int
    net_source_lead_samples: int
    sample_rate: int
    recoveries: tuple[NxaStartupRecovery, ...]

    @property
    def offset_ms(self) -> float:
        if self.sample_rate <= 0:
            raise NxaStartupError("NXA startup analysis has no valid sample rate")
        return self.net_source_lead_samples * 1000.0 / self.sample_rate


# Header tables intentionally describe behavior, not libmad source code. The
# analyzer is a clean-room model derived from runtime observations of the NXA
# executable and MPEG framing rules.
_SAMPLE_RATES = {
    3: (44_100, 48_000, 32_000, None),
    2: (22_050, 24_000, 16_000, None),
    0: (11_025, 12_000, 8_000, None),
}
_BITRATES_LAYER_I = {
    3: (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0),
    2: (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0),
    0: (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256, 0),
}
_BITRATES_LAYER_II = {
    3: (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0),
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
    0: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
}
_BITRATES_LAYER_III = {
    3: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0),
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
    0: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),
}
_STARTUP_SCAN_LIMIT = 128 * 1024
_MAX_RECOVERIES = 128


@dataclass(slots=True)
class _Header:
    offset: int
    version: int
    layer: int
    protection: int
    bitrate_index: int
    sample_rate_index: int
    padding: int
    mode: int
    emphasis: int
    error: str | None = None
    sample_rate: int | None = None
    bitrate_kbps: int | None = None
    frame_size: int | None = None

    @property
    def samples_per_frame(self) -> int:
        if self.layer == 3:
            return 384
        if self.layer == 2:
            return 1152
        return 1152 if self.version == 3 else 576

    @property
    def mono(self) -> bool:
        return self.mode == 3


def _syncword(payload: bytes, offset: int) -> bool:
    return (
        offset + 1 < len(payload)
        and payload[offset] == 0xFF
        and payload[offset + 1] & 0xE0 == 0xE0
    )


def _parse_header(payload: bytes, offset: int) -> _Header | None:
    if not _syncword(payload, offset) or offset + 4 > len(payload):
        return None
    word = int.from_bytes(payload[offset : offset + 4], "big")
    version = (word >> 19) & 0x03
    layer = (word >> 17) & 0x03
    protection = (word >> 16) & 0x01
    bitrate_index = (word >> 12) & 0x0F
    sample_rate_index = (word >> 10) & 0x03
    padding = (word >> 9) & 0x01
    mode = (word >> 6) & 0x03
    emphasis = word & 0x03
    header = _Header(
        offset,
        version,
        layer,
        protection,
        bitrate_index,
        sample_rate_index,
        padding,
        mode,
        emphasis,
    )

    # Runtime ordering matters. In particular, all-ones headers are reported as
    # forbidden bitrate before their also-reserved sample-frequency field.
    if version == 1:
        header.error = "lost synchronization"
        return header
    if layer == 0:
        header.error = "reserved layer value"
        return header
    if bitrate_index == 15:
        header.error = "forbidden bitrate value"
        return header
    if sample_rate_index == 3:
        header.error = "reserved sample frequency value"
        return header

    header.sample_rate = _SAMPLE_RATES[version][sample_rate_index]
    if bitrate_index == 0:
        header.bitrate_kbps = 0
        return header

    tables = {
        3: _BITRATES_LAYER_I,
        2: _BITRATES_LAYER_II,
        1: _BITRATES_LAYER_III,
    }
    header.bitrate_kbps = tables[layer][version][bitrate_index]
    if not header.bitrate_kbps or not header.sample_rate:
        header.error = "forbidden bitrate value"
        return header

    if layer == 3:
        header.frame_size = (
            (12 * header.bitrate_kbps * 1000) // header.sample_rate + padding
        ) * 4
    elif layer == 2:
        header.frame_size = (
            144 * header.bitrate_kbps * 1000 // header.sample_rate + padding
        )
    else:
        coefficient = 144 if version == 3 else 72
        header.frame_size = (
            coefficient * header.bitrate_kbps * 1000 // header.sample_rate + padding
        )
    return header


def _compatible(left: _Header, right: _Header | None, *, free: bool = False) -> bool:
    if right is None or right.error:
        return False
    if (
        left.version != right.version
        or left.layer != right.layer
        or left.sample_rate != right.sample_rate
    ):
        return False
    if free and left.mono != right.mono:
        return False
    return True


def _infer_free_frame_size(payload: bytes, header: _Header) -> int | None:
    stop = min(len(payload) - 4, header.offset + _STARTUP_SCAN_LIMIT)
    for offset in range(header.offset + 1, stop + 1):
        if not _syncword(payload, offset):
            continue
        candidate = _parse_header(payload, offset)
        if candidate is None or candidate.error:
            continue
        if (
            candidate.version != header.version
            or candidate.layer != header.layer
            or candidate.sample_rate != header.sample_rate
        ):
            continue
        distance = offset - header.offset
        if header.layer == 3:
            # Black-box probes show bitrate inference quantized to 1 kbit/s,
            # followed by Layer-I's four-byte slot calculation. Simply rounding
            # the byte distance up is wrong at 48 kHz and on padded headers.
            inferred_kbps = ((distance - 4 * header.padding + 4) * header.sample_rate) // 48_000
            if inferred_kbps < 8:
                continue
            return 4 * (12_000 * inferred_kbps // header.sample_rate + header.padding)
        return distance
    return None


def _confirm_next_header(payload: bytes, header: _Header) -> bool:
    if header.frame_size is None:
        return False
    next_offset = header.offset + header.frame_size
    # Resynchronization checks the next syncword, not format compatibility.
    # A false Layer-I header can therefore consume real Layer-III bytes.
    return _syncword(payload, next_offset)


def _find_source_start(payload: bytes) -> tuple[int, _Header]:
    # Require three exact Layer-III frame boundaries. This rejects sync-looking
    # bytes in ID3 text while accepting the real MPEG stream without relying on
    # metadata, file names, or one mastering-specific prefix.
    stop = min(max(0, len(payload) - 4), _STARTUP_SCAN_LIMIT)
    for offset in range(stop):
        header = _parse_header(payload, offset)
        if (
            header is None
            or header.error
            or header.layer != 1
            or header.bitrate_index == 0
            or header.frame_size is None
        ):
            continue
        second = _parse_header(payload, offset + header.frame_size)
        if not _compatible(header, second) or second is None or second.frame_size is None:
            continue
        third = _parse_header(payload, offset + header.frame_size + second.frame_size)
        if _compatible(second, third):
            return offset, header
    raise NxaStartupError("no stable MPEG Layer III source chain near MP3 start")


def _main_data_begin(payload: bytes, header: _Header) -> int:
    base = header.offset + 4 + (0 if header.protection else 2)
    if base + 2 > len(payload):
        raise NxaStartupError("truncated Layer III side information")
    if header.version == 3:
        return (payload[base] << 1) | (payload[base + 1] >> 7)
    return payload[base]


def _main_data_capacity(header: _Header) -> int:
    if header.frame_size is None:
        return 0
    if header.version == 3:
        side_info = 17 if header.mono else 32
    else:
        side_info = 9 if header.mono else 17
    return max(
        0,
        header.frame_size - 4 - (0 if header.protection else 2) - side_info,
    )


def _source_sample_map(payload: bytes, source_start: int) -> dict[int, int]:
    samples: dict[int, int] = {}
    offset = source_start
    cumulative = 0
    previous: _Header | None = None
    for _ in range(256):
        header = _parse_header(payload, offset)
        if (
            header is None
            or header.error
            or header.layer != 1
            or header.frame_size is None
            or (previous is not None and not _compatible(previous, header))
        ):
            break
        samples[offset] = cumulative
        cumulative += header.samples_per_frame
        offset += header.frame_size
        previous = header
        if offset > source_start + _STARTUP_SCAN_LIMIT:
            break
    return samples


def _layer1_recovery(payload: bytes, header: _Header) -> str:
    """Prove a recoverable Layer-I failure without decoding Layer-I audio."""
    channels = 1 if header.mono else 2
    bound = (((payload[header.offset + 3] >> 4) & 3) + 1) * 4 if header.mode == 1 else 32
    allocation_bits = 4 * (bound * channels + 32 - bound)
    base = header.offset + 4 + (0 if header.protection else 2)
    size = (allocation_bits + 7) // 8
    if base + size > len(payload):
        raise NxaStartupError("truncated Layer I allocation during startup")
    allocations = payload[base:base + size]
    if not header.protection:
        crc = 0xFFFF
        for value in payload[header.offset + 2:header.offset + 4] + allocations:
            for bit in range(8):
                feedback = bool(crc & 0x8000) != bool(value & (0x80 >> bit))
                crc = (crc << 1) & 0xFFFF
                if feedback:
                    crc ^= 0x8005
        expected = int.from_bytes(payload[header.offset + 4:header.offset + 6], "big")
        if crc != expected:
            return "CRC check failed"
    if any(value >> 4 == 15 or value & 15 == 15 for value in allocations):
        return "forbidden bit allocation value"
    raise NxaStartupError("potentially decodable Layer I startup is outside the supported timeline contract")


def analyze_nxa_mp3_startup(payload: bytes) -> NxaStartupAnalysis:
    """Model NXA/libmad startup displacement from exact MP3 bytes.

    The result is derived from MPEG framing and the recovery behavior observed
    in the NXA runtime. It does not decode audio, call libmad, or identify songs.
    Positive ``net_source_lead_samples`` means NXA reaches source content earlier
    than a conventional decoder; negative means it trails by that many source
    sample frames. ``offset_ms`` uses the same sign as ``AudioAlignment``.
    """

    if not isinstance(payload, bytes):
        payload = bytes(payload)
    if len(payload) < 12:
        raise NxaStartupError("MP3 payload is too short for startup analysis")

    source_start, _ = _find_source_start(payload)
    source_samples = _source_sample_map(payload, source_start)

    cursor = 0
    synchronized = True
    last_layer = 0
    last_samples = 1152
    synthetic_samples = 0
    recoveries: list[NxaStartupRecovery] = []
    reservoir = 0

    def recover(error: str, offset: int, samples: int) -> None:
        nonlocal synthetic_samples
        synthetic_samples += samples
        recoveries.append(NxaStartupRecovery(error, offset, samples))

    def update_header_state(header: _Header) -> None:
        nonlocal last_samples, last_layer
        # Parsing mutates the synthesis header even when the candidate is
        # subsequently rejected. Reserved version fails before layer is read;
        # it clears the low-sampling-frequency flag but preserves the layer.
        if header.version != 1:
            last_layer = header.layer
        last_samples = (384 if last_layer == 3 else
                        576 if last_layer == 1 and header.version in (0, 2) else
                        1152)

    for _ in range(_MAX_RECOVERIES):
        if synchronized:
            header = _parse_header(payload, cursor)
            if header is None:
                recover("lost synchronization", cursor, last_samples)
                cursor += 1
                synchronized = False
                continue
            update_header_state(header)
        else:
            header = None
            stop = min(len(payload) - 4, cursor + _STARTUP_SCAN_LIMIT)
            for offset in range(cursor, stop + 1):
                candidate = _parse_header(payload, offset)
                if candidate is None:
                    continue
                update_header_state(candidate)
                if candidate.error:
                    header = candidate
                    break
                if candidate.bitrate_index == 0:
                    candidate.frame_size = _infer_free_frame_size(payload, candidate)
                    if candidate.frame_size is None:
                        header = candidate
                        break
                if _confirm_next_header(payload, candidate):
                    header = candidate
                    break
            if header is None:
                raise NxaStartupError("cannot locate a decodable MPEG frame during startup")
        if header.error:
            recover(header.error, header.offset, last_samples)
            cursor = header.offset + 1
            synchronized = False
            continue
        if header.bitrate_index == 0 and header.frame_size is None:
            header.frame_size = _infer_free_frame_size(payload, header)
            if header.frame_size is None:
                recover("lost synchronization", header.offset, last_samples)
                cursor = header.offset + 1
                synchronized = False
                continue

        if header.frame_size is None:
            raise NxaStartupError("MPEG frame has no resolved size")

        candidate_offset = header.offset
        cursor = candidate_offset + header.frame_size
        synchronized = True

        if not header.protection and header.layer == 1:
            from stepnx.authoring.mpeg_crc import layer3_crc_valid

            if not layer3_crc_valid(payload, candidate_offset, header):
                recover("CRC check failed", candidate_offset, last_samples)
                reservoir = min(511, reservoir + _main_data_capacity(header))
                continue
        if header.layer == 3:
            error = _layer1_recovery(payload, header)
            recover(error, candidate_offset, last_samples)
            continue
        if header.layer != 1:
            raise NxaStartupError("Layer II startup decoding is outside the supported timeline contract")

        main_data_begin = _main_data_begin(payload, header)
        if main_data_begin > reservoir:
            recover("bad main_data_begin pointer", candidate_offset, last_samples)
            reservoir = min(511, reservoir + _main_data_capacity(header))
            continue

        samples_before = source_samples.get(candidate_offset)
        if samples_before is None:
            # Extend the source chain deterministically if the successful frame
            # sits beyond the startup map.
            offset = source_start
            samples_before = 0
            for _ in range(10_000):
                if offset == candidate_offset:
                    break
                source_header = _parse_header(payload, offset)
                if (
                    source_header is None
                    or source_header.error
                    or source_header.layer != 1
                    or source_header.frame_size is None
                ):
                    raise NxaStartupError(
                        "successful startup frame is not on the source MPEG chain"
                    )
                samples_before += source_header.samples_per_frame
                offset += source_header.frame_size
            if offset != candidate_offset:
                raise NxaStartupError(
                    "successful startup frame is not on the source MPEG chain"
                )

        if not header.sample_rate:
            raise NxaStartupError("successful MPEG frame has no sample rate")
        net = samples_before - synthetic_samples
        return NxaStartupAnalysis(
            source_start_offset=source_start,
            first_decoded_offset=candidate_offset,
            source_samples_before_first_decoded=samples_before,
            synthesized_samples_before_first_decoded=synthetic_samples,
            net_source_lead_samples=net,
            sample_rate=header.sample_rate,
            recoveries=tuple(recoveries),
        )

    raise NxaStartupError("NXA startup recovery did not converge")
