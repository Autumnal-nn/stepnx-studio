from __future__ import annotations

import math
import unittest

from stepnx.authoring.mp3_gapless import Mp3GaplessAnalysis
from stepnx.authoring.nxa_startup import NxaStartupAnalysis
from stepnx.gui.nxa_audio_alignment import effective_nxa_audio_offset_ms


class NxaAudioAlignmentTests(unittest.TestCase):
    def test_nxa_profile_composes_automatic_and_manual_offsets(self) -> None:
        analysis = NxaStartupAnalysis(0, 0, 0, 0, -1920, 48000, ())
        self.assertEqual(
            effective_nxa_audio_offset_ms(7.5, analysis, nxa_profile=True),
            -32.5,
        )

    def test_ffmpeg_lame_trim_is_restored_as_virtual_negative_offset(self) -> None:
        analysis = NxaStartupAnalysis(0, 0, 0, 0, 0, 48000, ())
        gapless = Mp3GaplessAnalysis(
            encoder="LAME3.96",
            encoder_delay_samples=576,
            encoder_padding_samples=1000,
            ffmpeg_start_skip_samples=1105,
            sample_rate=48000,
        )
        self.assertAlmostEqual(
            effective_nxa_audio_offset_ms(
                -33.0,
                analysis,
                gapless,
                nxa_profile=True,
            ),
            -56.02083333333333,
        )

    def test_other_profiles_keep_manual_offset(self) -> None:
        analysis = NxaStartupAnalysis(0, 0, 0, 0, 6912, 48000, ())
        gapless = Mp3GaplessAnalysis("LAME", 576, 0, 1105, 48000)
        self.assertEqual(
            effective_nxa_audio_offset_ms(
                5.0,
                analysis,
                gapless,
                nxa_profile=False,
            ),
            5.0,
        )

    def test_missing_analysis_keeps_manual_offset(self) -> None:
        self.assertEqual(
            effective_nxa_audio_offset_ms(-3.25, None, nxa_profile=True),
            -3.25,
        )

    def test_non_finite_manual_offset_is_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    effective_nxa_audio_offset_ms(value, None, nxa_profile=True)


if __name__ == "__main__":
    unittest.main()
