from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from stepnx.cli.main import main
from tests.fixture_factory import make_normal_nx20, make_nx10


class CliTests(unittest.TestCase):
    def test_inspect_json_reports_exact_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "chart.NX"
            path.write_bytes(make_normal_nx20())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["inspect", str(path), "--json"])
            self.assertEqual(result, 0)
            self.assertIn('"byte_exact_roundtrip": true', output.getvalue())

    def test_inspect_accepts_compact_row_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "chart.NX"
            path.write_bytes(make_normal_nx20())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["inspect", str(path), "--row-storage", "compact", "--json"])
            self.assertEqual(result, 0)
            self.assertIn('"byte_exact_roundtrip": true', output.getvalue())

    def test_verify_skips_recognized_legacy_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "chart.NX").write_bytes(make_normal_nx20())
            (root / "legacy.NX").write_bytes(make_nx10())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["verify", str(root)])
            self.assertEqual(result, 0)
            self.assertIn("verified=1 unsupported=1 errors=0 total=2", output.getvalue())

    def test_roundtrip_writes_copy_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "chart.NX"
            output_path = root / "copy.NX"
            source.write_bytes(make_normal_nx20())
            with contextlib.redirect_stdout(io.StringIO()):
                result = main(["roundtrip", str(source), "-o", str(output_path)])
            self.assertEqual(result, 0)
            self.assertEqual(output_path.read_bytes(), source.read_bytes())


if __name__ == "__main__":
    unittest.main()
