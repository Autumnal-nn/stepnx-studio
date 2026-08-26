from __future__ import annotations

import argparse
import struct
from collections import Counter, defaultdict
from pathlib import Path

from stepnx.authoring.audio import AudDecodeError, decode_enc2_aud


_BIT_REVERSE = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))
_ZERO_SCAN_LIMIT = 64 * 1024


def _parse_enc2(source: bytes):
    if len(source) < 156 or source[:4].upper() != b"ENC2":
        return None
    payload_size, skip = struct.unpack_from("<II", source, 0x84)
    key = source[0x8C:0x9C]
    table_offset = 0x9C + skip
    payload_offset = table_offset + 4 + 1024
    payload_end = payload_offset + payload_size
    if payload_size <= 0 or payload_end > len(source):
        return None
    start_index = struct.unpack_from("<I", source, table_offset)[0]
    return (
        key,
        start_index,
        source[table_offset + 4 : payload_offset],
        source[payload_offset:payload_end],
    )


def _looks_like_mp3(payload: bytes) -> bool:
    if payload.startswith(b"ID3") and len(payload) >= 10:
        return payload[3] in (2, 3, 4) and not any(
            byte & 0x80 for byte in payload[6:10]
        )
    return len(payload) >= 4 and payload[0] == 0xFF and payload[1] & 0xE0 == 0xE0


def _decode_with_profile(
    base_profile: bytes,
    key: bytes,
    start_index: int,
    encrypted_table: bytes,
    encrypted_payload: bytes,
) -> bytes:
    effective = bytes(left ^ right for left, right in zip(base_profile, key))
    key_stream = bytes(
        value ^ effective[index & 15]
        for index, value in enumerate(encrypted_table)
    )
    return bytes(
        _BIT_REVERSE[value] ^ key_stream[(start_index + index) & 1023]
        for index, value in enumerate(encrypted_payload)
    )


def _zero_run_recovery(source: bytes):
    parsed = _parse_enc2(source)
    if parsed is None:
        return None
    key, start_index, encrypted_table, encrypted_payload = parsed
    prefix_size = min(len(encrypted_payload), _ZERO_SCAN_LIMIT + 32)
    masked = bytes(
        _BIT_REVERSE[encrypted_payload[index]]
        ^ encrypted_table[(start_index + index) & 1023]
        ^ key[(start_index + index) & 15]
        for index in range(prefix_size)
    )
    stop = min(_ZERO_SCAN_LIMIT, max(0, len(masked) - 32))
    attempted: set[bytes] = set()
    for offset in range(stop + 1):
        # With the unknown profile removed, two equal 16-byte blocks imply
        # a 32-byte repeated plaintext block. Treating that block as zeros
        # yields a candidate profile; the decoded MP3 header is the independent
        # validation step, so a coincidental ciphertext repetition is rejected.
        if masked[offset : offset + 16] != masked[offset + 16 : offset + 32]:
            continue
        effective = bytearray(16)
        for index in range(16):
            stream_index = (start_index + offset + index) & 1023
            lane = stream_index & 15
            effective[lane] = (
                _BIT_REVERSE[encrypted_payload[offset + index]]
                ^ encrypted_table[stream_index]
            )
        base_profile = bytes(
            value ^ key[index] for index, value in enumerate(effective)
        )
        if base_profile in attempted:
            continue
        attempted.add(base_profile)
        decoded = _decode_with_profile(
            base_profile,
            key,
            start_index,
            encrypted_table,
            encrypted_payload,
        )
        if _looks_like_mp3(decoded):
            return offset, decoded
    return None


def _magic(source: bytes) -> str:
    raw = source[:16]
    text = "".join(chr(value) if 32 <= value < 127 else "." for value in raw)
    return f"{raw.hex()}  {text}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify AUD corpus formats and ENC2 recovery candidates."
    )
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    paths = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".aud", ".a"}
    )
    current_ok = 0
    zero_ok: list[tuple[str, int]] = []
    unresolved: list[str] = []
    enc1: list[tuple[str, str]] = []
    other: list[tuple[str, str]] = []

    for path in paths:
        relative = path.relative_to(root).as_posix()
        source = path.read_bytes()
        magic = source[:4].upper()
        if magic == b"ENC1":
            enc1.append((relative, _magic(source)))
            continue
        if magic != b"ENC2":
            other.append((relative, _magic(source)))
            continue
        try:
            decode_enc2_aud(path)
        except AudDecodeError:
            recovered = _zero_run_recovery(source)
            if recovered is None:
                unresolved.append(relative)
            else:
                offset, _decoded = recovered
                zero_ok.append((relative, offset))
        else:
            current_ok += 1

    print(f"TOTAL: {len(paths)}")
    print(f"ENC2_CURRENT_OK: {current_ok}")
    print(f"ENC2_ZERO_RUN_RECOVERABLE: {len(zero_ok)}")
    print(f"ENC2_STILL_UNRESOLVED: {len(unresolved)}")
    print(f"ENC1: {len(enc1)}")
    print(f"OTHER_FORMAT: {len(other)}")

    offsets = Counter(offset for _name, offset in zero_ok)
    if offsets:
        print("ENC2_ZERO_RUN_OFFSETS:")
        for offset, count in offsets.most_common(20):
            print(f"  {offset}: {count}")

    if unresolved:
        print("ENC2_UNRESOLVED_PATHS:")
        for name in unresolved:
            print(f"  {name}")

    if enc1:
        groups: dict[str, list[str]] = defaultdict(list)
        for relative, magic_text in enc1:
            groups[magic_text].append(relative)
        print(f"ENC1_HEADER_GROUPS: {len(groups)}")
        for magic_text, members in sorted(
            groups.items(), key=lambda item: (-len(item[1]), item[0])
        ):
            examples = "; ".join(members[:4])
            suffix = " ..." if len(members) > 4 else ""
            print(f"  {len(members):4d}  {magic_text}  {examples}{suffix}")

    if other:
        print("OTHER_FORMAT_PATHS:")
        for relative, magic_text in other:
            print(f"  {relative}: {magic_text}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
