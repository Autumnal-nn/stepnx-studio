from __future__ import annotations

import math
import unittest

from stepnx.core.scalars import RawF32, RawU16, RawU32, SourceSpan


class RawScalarTests(unittest.TestCase):
    def test_float_preserves_nan_payload(self) -> None:
        raw = RawF32.from_bits(0x7FA12345)
        self.assertTrue(math.isnan(raw.value))
        self.assertEqual(raw.bits, 0x7FA12345)
        self.assertEqual(raw.raw, bytes.fromhex("4523A17F"))

    def test_float_preserves_negative_zero(self) -> None:
        raw = RawF32.from_bits(0x80000000)
        self.assertEqual(raw.value, 0.0)
        self.assertEqual(raw.bits, 0x80000000)

    def test_integer_edit_discards_source_span(self) -> None:
        original = RawU32(bytes.fromhex("01000000"), SourceSpan(10, 14))
        edited = original.with_value(2)
        self.assertEqual(edited.value, 2)
        self.assertIsNone(edited.span)

    def test_scalar_rejects_wrong_size(self) -> None:
        with self.assertRaises(ValueError):
            RawU16(b"\x00")


if __name__ == "__main__":
    unittest.main()

