from __future__ import annotations

import math
import unittest

from stepnx.gui.nxa_startup_experiment import (
    NXA_STARTUP_CORRECTION_PRESETS_MS,
    effective_audio_offset_ms,
)


class NxaStartupExperimentTests(unittest.TestCase):
    def test_candidate_classes_are_explicit_and_small(self) -> None:
        self.assertEqual(
            NXA_STARTUP_CORRECTION_PRESETS_MS,
            (0.0, 24.0, 32.0, 40.0, 48.0, -144.0),
        )

    def test_disabled_is_exact_existing_session_offset(self) -> None:
        self.assertEqual(
            effective_audio_offset_ms(12.5, 48.0, enabled=False),
            12.5,
        )

    def test_enabled_composes_with_manual_offset(self) -> None:
        self.assertEqual(
            effective_audio_offset_ms(-7.5, 40.0, enabled=True),
            32.5,
        )
        self.assertEqual(
            effective_audio_offset_ms(8.0, -144.0, enabled=True),
            -136.0,
        )

    def test_non_finite_offsets_are_rejected(self) -> None:
        for manual, correction in (
            (math.nan, 0.0),
            (0.0, math.inf),
            (0.0, -math.inf),
        ):
            with self.subTest(manual=manual, correction=correction):
                with self.assertRaises(ValueError):
                    effective_audio_offset_ms(manual, correction, enabled=True)


if __name__ == "__main__":
    unittest.main()
