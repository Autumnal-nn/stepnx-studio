from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from stepnx.cli.main import main
from tests.fixture_factory import make_implicit_lightmap, make_normal_nx20, make_nx10


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

    def test_verify_imports_recognized_nx10(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "chart.NX").write_bytes(make_normal_nx20())
            (root / "legacy.NX").write_bytes(make_nx10())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["verify", str(root)])
            self.assertEqual(result, 0)
            self.assertIn(
                "verified=1 imported=1 import_attention=0 unsupported=0 errors=0 total=2",
                output.getvalue(),
            )

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

    def test_validate_reports_a_clean_document(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "chart.NX"
            path.write_bytes(make_normal_nx20())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["validate", str(path), "--json"])
            self.assertEqual(result, 0)
            self.assertIn('"valid": true', output.getvalue())

    def test_diff_reports_structural_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            left = root / "left.NX"
            right = root / "right.NX"
            source = bytearray(make_normal_nx20(sized_trailer=False))
            left.write_bytes(source)
            source[32:36] = (42).to_bytes(4, "little")
            right.write_bytes(source)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["diff", str(left), str(right), "--json"])
            self.assertEqual(result, 1)
            self.assertIn('"path": "header_metadata[1].value"', output.getvalue())

    def test_import_nx10_writes_only_to_an_explicit_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "legacy.NX"
            output_path = root / "native.NX"
            source.write_bytes(make_nx10())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(
                    ["import-nx10", str(source), "--output", str(output_path), "--json"]
                )

            self.assertEqual(result, 0)
            self.assertEqual(source.read_bytes(), make_nx10())
            self.assertEqual(output_path.read_bytes()[:4], b"NX20")
            self.assertIn('"semantically_lossless": true', output.getvalue())

    def test_import_nx10_never_overwrites_its_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "legacy.NX"
            payload = make_nx10()
            source.write_bytes(payload)
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                result = main(
                    ["import-nx10", str(source), "--output", str(source), "--force"]
                )

            self.assertEqual(result, 1)
            self.assertEqual(source.read_bytes(), payload)
            self.assertIn("refusing to overwrite", error.getvalue())

    def test_folder_inspect_reports_documents_failures_and_publication_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "LM.NX").write_bytes(make_implicit_lightmap())
            (root / "NM.NX").write_bytes(make_normal_nx20())
            (root / "BAD.NX").write_bytes(b"NX20")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["folder-inspect", str(root), "--json"])
            self.assertEqual(result, 1)
            report = output.getvalue()
            self.assertIn('"name": "LM.NX"', report)
            self.assertIn('"name": "NM.NX"', report)
            self.assertIn('"publication_ready": false', report)
            self.assertIn('"folder.unreadable-document"', report)

    def test_folder_save_plan_is_a_write_free_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lightmap = root / "LM.NX"
            chart = root / "NM.NX"
            lightmap.write_bytes(make_implicit_lightmap())
            chart.write_bytes(make_normal_nx20())
            before = {path: path.read_bytes() for path in (lightmap, chart)}
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["folder-save-plan", str(root), "--json"])
            self.assertEqual(result, 0)
            self.assertIn('"ready": true', output.getvalue())
            self.assertIn('"operation_count": 0', output.getvalue())
            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_folder_generate_lightmap_previews_then_explicitly_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "NM.NX").write_bytes(make_normal_nx20())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(
                    ["folder-generate-lightmap", str(root), "--bpm", "150", "--json"]
                )
            self.assertEqual(result, 0)
            self.assertIn('"written": false', output.getvalue())
            self.assertIn('"size": 1668', output.getvalue())
            self.assertFalse((root / "LM.NX").exists())

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(
                    [
                        "folder-generate-lightmap",
                        str(root),
                        "--bpm",
                        "150",
                        "--write",
                        "--json",
                    ]
                )
            self.assertEqual(result, 0)
            self.assertIn('"written": true', output.getvalue())
            self.assertEqual((root / "LM.NX").read_bytes()[:4], b"NX20")

            existing = (root / "LM.NX").read_bytes()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(
                    [
                        "folder-generate-lightmap",
                        str(root),
                        "--bpm",
                        "180",
                        "--write",
                        "--json",
                    ]
                )
            self.assertEqual(result, 0)
            self.assertIn('"reused": true', output.getvalue())
            self.assertIn('"written": false', output.getvalue())
            self.assertEqual((root / "LM.NX").read_bytes(), existing)

    def test_mirror_compare_uses_shared_nx20_codec(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "NM.NX"
            mirror = root / "NM.NFO"
            source.write_bytes(make_normal_nx20())
            mirror.write_bytes(make_normal_nx20())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["mirror-compare", str(source), str(mirror), "--json"])
            self.assertEqual(result, 0)
            self.assertIn('"binary_identical": true', output.getvalue())


if __name__ == "__main__":
    unittest.main()
