from __future__ import annotations

import unittest

from stepnx.importers.legacy import parse_ksf


class KSFImportRegressionTests(unittest.TestCase):
    def test_semicolon_terminated_headers_parse(self) -> None:
        chart = parse_ksf(
            b"#BPM:180.0;\n"
            b"#TICKCOUNT:4;\n"
            b"#STEP:\n"
            b"1000000000\n"
            b"#END;\n",
            source="legacy.KSF",
        )

        block = chart.blocks[0]
        self.assertEqual(block.bpm, 180.0)
        self.assertEqual(block.beat_split, 4)
        self.assertEqual(block.rows[0].cells[0], 1)

    def test_semicolon_terminated_direct_move_control_is_normalized(self) -> None:
        chart = parse_ksf(
            b"#STEP:\n"
            b"B:180.0;\n"
            b"1000000000\n"
            b"#END;\n"
        )

        self.assertEqual(chart.source_format, "ksf-direct-move")
        self.assertEqual(chart.controls, (("B", "180.0"),))


if __name__ == "__main__":
    unittest.main()
