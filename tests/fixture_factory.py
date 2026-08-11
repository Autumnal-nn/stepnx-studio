from __future__ import annotations

import struct


def u32(value: int) -> bytes:
    return struct.pack("<I", value)


def f32(value: float) -> bytes:
    return struct.pack("<f", value)


def f32_bits(bits: int) -> bytes:
    return struct.pack("<I", bits)


def metadata(*pairs: tuple[int, int]) -> bytes:
    return u32(len(pairs)) + b"".join(u32(meta_id) + u32(value) for meta_id, value in pairs)


def make_normal_nx20(*, sized_trailer: bool = True, opaque_tail: bool = False) -> bytes:
    data = bytearray(b"NX20")
    data += u32(0) + u32(5) + u32(0)
    data += metadata((900, 7), (900, 9), (0x0001044F, 12))
    data += u32(1)
    data += bytes((0x5A, 0x81)) + struct.pack("<H", 0xBEEF)
    data += metadata((21, 3), (21, 4))
    data += u32(1)
    data += f32_bits(0x80000000)
    data += f32(120.0)
    data += f32_bits(0x7FA12345)
    data += f32(-0.25)
    data += f32(-1.5)
    data += bytes((4, 4, 3, 0xA5))
    data += metadata((111, 0xDEADBEEF), (0x4001, 0x00020001))
    data += u32(2)
    data += bytes((0x03, 0x04, 0x05, 0x06))
    data += bytes((0x01, 0xF0, 0x10, 0x20))
    data += bytes((0x05, 0x06, 0x07, 0x08))
    data += bytes((0x07, 0x08, 0x09, 0x0A))
    data += bytes((0x00, 0x00, 0x00, 0x00))
    data += bytes((0x80, 0x12, 0x34, 0x56))
    if opaque_tail:
        data += b"not-a-sized-trailer"
    elif sized_trailer:
        payload = b"condition\x00localized text\x00"
        data += payload + u32(len(payload) + 4)
    return bytes(data)


def make_implicit_lightmap() -> bytes:
    data = bytearray(b"NX20")
    data += u32(0) + u32(3) + u32(0)
    data += metadata()
    data += u32(1)
    data += b"\x00\x00\x00\x00"
    data += metadata()
    data += u32(1)
    data += f32(0.0) + f32(120.0) + f32(0.5) + f32(0.0) + f32(1.0)
    data += bytes((2, 4, 0, 0))
    data += metadata()
    data += u32(1)
    data += b"\x01\x02\x03\x04"
    return bytes(data)


def make_nx10() -> bytes:
    return b"NX10" + u32(0) + u32(5) + u32(0)


def make_nx10_lightmap() -> bytes:
    split_offset = 20
    block_offset = 28
    data = bytearray(b"NX10")
    data += u32(10) + u32(3) + u32(1)
    data += u32(split_offset)
    data += u32(1) + u32(block_offset)
    data += f32(0.0) + f32(120.0) + f32(0.5) + f32(0.0) + f32(1.0)
    data += u32(0)
    data += struct.pack("<HBBI", 2, 4, 1, 1)
    data += b"\x01\x02\x03\x04"
    return bytes(data)


def make_stepedit_blank_nx10_lightmap(*, bpm: float = 120.0) -> bytes:
    """Reproduce the blank LM.NX emitted by StepEdit 5.63."""

    split_offset = 20
    block_offset = 28
    row_count = 400
    data = bytearray(b"NX10")
    data += u32(10) + u32(3) + u32(1)
    data += u32(split_offset)
    data += u32(1) + u32(block_offset)
    data += f32(0.0) + f32(bpm) + f32(0.5) + f32(0.0) + f32(1.0)
    data += u32(0)
    data += struct.pack("<HBBI", 2, 4, 0, row_count)
    data += b"\x00\x00\x00\x00" * row_count
    data += b"\x00\x00\x00\x00"
    return bytes(data)
