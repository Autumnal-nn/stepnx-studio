from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stepnx.core.errors import UnsupportedFormatError
from stepnx.importers.dispatch import load_importable


class ImportDispatchErrorTests(unittest.TestCase):
    def test_unknown_suffix_raises_structured_unsupported_format_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "chart.xyz"
            with self.assertRaises(UnsupportedFormatError) as caught:
                load_importable(source)

        error = caught.exception
        self.assertEqual(error.offset, 0)
        self.assertEqual(error.label, "import source")
        self.assertIn(".xyz", error.detail)
        self.assertEqual(error.source, str(source))


if __name__ == "__main__":
    unittest.main()
