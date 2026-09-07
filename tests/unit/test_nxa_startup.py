from __future__ import annotations

import unittest

from stepnx.authoring.nxa_startup import (
    NxaStartupAnalysis,
    NxaStartupRecovery,
    analyze_nxa_mp3_startup,
)

_MPEG1_L3_192K_48K_STEREO = bytes.fromhex("fffbb404")


def _layer3_frame(main_data_begin: int = 0) -> bytes:
    payload = bytearray(572)
    payload[0] = (main_data_begin >> 1) & 0xFF
    payload[1] = (main_data_begin & 1) << 7
    return _MPEG1_L3_192K_48K_STEREO + bytes(payload)


def _source_chain(*main_data_begin: int) -> bytes:
    values = main_data_begin or (0, 0, 0, 0)
    return b"".join(_layer3_frame(value) for value in values)


class NxaStartupTests(unittest.TestCase):
    def test_clean_mpeg_chain_has_no_correction(self) -> None:
        result = analyze_nxa_mp3_startup(_source_chain())
        self.assertEqual(result.net_source_lead_samples, 0)
        self.assertEqual(result.offset_ms, 0.0)
        self.assertEqual(result.recoveries, ())

    def test_leading_junk_reproduces_initial_lost_sync(self) -> None:
        result = analyze_nxa_mp3_startup(b"JUNK" + _source_chain())
        self.assertEqual(result.net_source_lead_samples, -1152)
        self.assertEqual(result.offset_ms, -24.0)
        self.assertEqual(
            result.recoveries,
            (NxaStartupRecovery("lost synchronization", 0, 1152),),
        )

    def test_header_recovery_uses_runtime_error_priority(self) -> None:
        payload = b"X" + bytes.fromhex("fffe4f00") + b"Y" * 8 + _source_chain()
        result = analyze_nxa_mp3_startup(payload)
        self.assertEqual(result.net_source_lead_samples, -1536)
        self.assertEqual(result.offset_ms, -32.0)
        self.assertEqual(
            [item.error for item in result.recoveries],
            ["lost synchronization", "reserved sample frequency value"],
        )

        all_ones = analyze_nxa_mp3_startup(
            bytes.fromhex("ffffffff") + b"X" * 8 + _source_chain()
        )
        self.assertEqual(all_ones.recoveries[0].error, "forbidden bitrate value")

    def test_bad_main_data_begin_advances_source_and_recovery_equally(self) -> None:
        result = analyze_nxa_mp3_startup(_source_chain(100, 0, 0, 0))
        self.assertEqual(result.first_decoded_offset, 576)
        self.assertEqual(result.source_samples_before_first_decoded, 1152)
        self.assertEqual(result.synthesized_samples_before_first_decoded, 1152)
        self.assertEqual(result.net_source_lead_samples, 0)

    def test_false_free_format_frame_can_make_nxa_lead_source(self) -> None:
        payload = bytearray(b"X" * 4096)
        for offset in (100, 676, 1252, 1828, 2404, 2980, 3556):
            payload[offset : offset + 576] = _layer3_frame(
                100 if offset == 2404 else 0
            )

        payload[8:12] = bytes.fromhex("fffe08b1")
        payload[2000:2004] = bytes.fromhex("ffff5a09")

        result = analyze_nxa_mp3_startup(bytes(payload))
        self.assertEqual(result.source_start_offset, 100)
        self.assertEqual(result.first_decoded_offset, 2980)
        self.assertEqual(result.source_samples_before_first_decoded, 5760)
        self.assertEqual(result.synthesized_samples_before_first_decoded, 3456)
        self.assertEqual(result.net_source_lead_samples, 2304)
        self.assertEqual(result.offset_ms, 48.0)

    def test_offset_ms_preserves_net_source_lead_sign(self) -> None:
        positive = NxaStartupAnalysis(0, 0, 0, 0, 6912, 48000, ())
        negative = NxaStartupAnalysis(0, 0, 0, 0, -1920, 48000, ())
        self.assertEqual(positive.offset_ms, 144.0)
        self.assertEqual(negative.offset_ms, -40.0)


if __name__ == "__main__":
    unittest.main()
