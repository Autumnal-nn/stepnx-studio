from __future__ import annotations


def layer3_crc_valid(payload: bytes, offset: int, header) -> bool:
    """MPEG audio CRC-16 over protected header bits and Layer III side info."""
    if header.protection:
        return True
    size = (17 if header.mono else 32) if header.version == 3 else (9 if header.mono else 17)
    if offset + 6 + size > len(payload):
        return False
    crc = 0xFFFF
    for value in payload[offset + 2:offset + 4] + payload[offset + 6:offset + 6 + size]:
        for bit in range(7, -1, -1):
            feedback = ((crc >> 15) ^ (value >> bit)) & 1
            crc = (crc << 1) & 0xFFFF
            if feedback:
                crc ^= 0x8005
    return crc == int.from_bytes(payload[offset + 4:offset + 6], "big")
