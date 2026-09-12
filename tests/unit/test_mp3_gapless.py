from __future__ import annotations

import unittest

from stepnx.authoring.mp3_gapless import analyze_ffmpeg_lame_gapless


_MPEG1_L3_192K_48K_STEREO = bytes.fromhex("fffbb404")


def _info_frame(*, encoder_delay: int = 576, encoder_padding: int = 1000) -> bytes:
    frame = bytearray(576)
    frame[:4] = _MPEG1_L3_192K_48K_STEREO

    # MPEG-1 stereo Xing/Info marker is 32 side-info bytes after the header.
    xing = 4 + 32
    frame[xing : xing + 4] = b"Info"
    frame[xing + 4 : xing + 8] = (0).to_bytes(4, "big")

    encoder = xing + 8
    frame[encoder : encoder + 9] = b"LAME3.96 "

    delay_offset = encoder + 9 + 12
    packed = (encoder_delay << 12) | encoder_padding
    frame[delay_offset : delay_offset + 3] = packed.to_bytes(3, "big")
    return bytes(frame)


class Mp3GaplessTests(unittest.TestCase):
    def test_lame_delay_matches_ffmpeg_start_skip_semantics(self) -> None:
        result = analyze_ffmpeg_lame_gapless(_info_frame())
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.encoder_delay_samples, 576)
        self.assertEqual(result.encoder_padding_samples, 1000)
        self.assertEqual(result.ffmpeg_start_skip_samples, 1105)
        self.assertAlmostEqual(result.ffmpeg_start_skip_ms, 23.020833333333332)

    def test_no_xing_info_tag_has_no_gapless_correction(self) -> None:
        payload = _MPEG1_L3_192K_48K_STEREO + bytes(572)
        self.assertIsNone(analyze_ffmpeg_lame_gapless(payload))

    def test_unrecognized_encoder_does_not_invent_ffmpeg_trim(self) -> None:
        payload = bytearray(_info_frame())
        encoder = 4 + 32 + 8
        payload[encoder : encoder + 9] = b"OTHER1234"
        self.assertIsNone(analyze_ffmpeg_lame_gapless(bytes(payload)))


if __name__ == "__main__":
    unittest.main()
