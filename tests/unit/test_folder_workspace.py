from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from stepnx.codecs.nx20 import parse_bytes, serialize
from stepnx.core.scalars import RawU32
from stepnx.workspace import (
    RecoveryError,
    RecoveryStore,
    SourceFormat,
    WorkspaceError,
    compare_mirror,
    create_blank_lightmap,
    execute_save_plan,
    open_folder,
    plan_blank_lightmap,
    plan_individual_save,
    plan_mirror_export,
    plan_save_all,
)
from tests.fixture_factory import (
    make_implicit_lightmap,
    make_normal_nx20,
    make_nx10,
    make_nx10_lightmap,
    make_stepedit_blank_nx10_lightmap,
)
from stepnx.importers.nx10 import import_bytes as import_nx10_bytes


def _edit_first_metadata(entry):
    if not entry.document.header_metadata:
        return entry.with_document(
            replace(entry.document, lightmap_flag=RawU32.from_value(1))
        )
    first = entry.document.header_metadata[0]
    edited_first = replace(first, value=RawU32.from_value(first.value.value + 1), span=None)
    document = replace(
        entry.document,
        header_metadata=(edited_first, *entry.document.header_metadata[1:]),
    )
    return entry.with_document(document)


class FolderWorkspaceTests(unittest.TestCase):
    def _complete_folder(self, root: Path) -> None:
        (root / "LM.NX").write_bytes(make_implicit_lightmap())
        (root / "NM.NX").write_bytes(make_normal_nx20())

    def test_open_is_non_recursive_and_isolates_bad_nx(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._complete_folder(root)
            (root / "BROKEN.NX").write_bytes(b"NX20")
            (root / "MISSION.NFO").write_bytes(make_normal_nx20())
            nested = root / "nested"
            nested.mkdir()
            (nested / "IGNORED.NX").write_bytes(make_normal_nx20())
            (root / "song.mp3").write_bytes(b"audio-placeholder")

            workspace = open_folder(root)

            self.assertEqual([entry.path.name for entry in workspace.documents], ["LM.NX", "NM.NX"])
            self.assertEqual([failure.path.name for failure in workspace.failures], ["BROKEN.NX"])
            self.assertEqual([item.path.name for item in workspace.audio_candidates], ["song.mp3"])
            self.assertFalse(workspace.publication_report().is_ready)

    def test_complete_folder_requires_exact_valid_lightmap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "lm.nx").write_bytes(make_implicit_lightmap())
            (root / "NM.NX").write_bytes(make_normal_nx20())
            workspace = open_folder(root)
            self.assertIn(
                "lightmap.missing",
                [issue.code for issue in workspace.publication_report().errors],
            )

            (root / "lm.nx").rename(root / "LM.NX")
            workspace = open_folder(root)
            self.assertTrue(workspace.publication_report().is_ready)

            (root / "LM.NX").write_bytes(make_normal_nx20())
            workspace = open_folder(root)
            self.assertIn(
                "lightmap.wrong-layout",
                [issue.code for issue in workspace.publication_report().errors],
            )

    def test_blank_lightmap_matches_stepedit_projection_at_observed_bpms(self) -> None:
        for bpm in (150.0, 180.0):
            with self.subTest(bpm=bpm):
                reference = import_nx10_bytes(
                    make_stepedit_blank_nx10_lightmap(bpm=bpm),
                    source="LM.NX",
                )
                generated = create_blank_lightmap(bpm)
                self.assertEqual(serialize(generated), serialize(reference.document))
                self.assertEqual(generated.statistics()["rows"], 400)
                self.assertEqual(generated.statistics()["lightmap_rows"], 400)

    def test_blank_lightmap_plan_is_previewable_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "NM.NX").write_bytes(make_normal_nx20())
            workspace = open_folder(root)

            plan = plan_blank_lightmap(workspace, 150.0)
            self.assertTrue(plan.is_ready)
            self.assertEqual(len(plan.operations), 1)
            self.assertIsNone(plan.operations[0].source)
            self.assertEqual(plan.operations[0].target, root / "LM.NX")
            self.assertFalse((root / "LM.NX").exists())

            execute_save_plan(plan)
            self.assertEqual((root / "LM.NX").read_bytes()[:4], b"NX20")
            self.assertTrue(open_folder(root).publication_report().is_ready)
            existing = (root / "LM.NX").read_bytes()
            reused = plan_blank_lightmap(open_folder(root), 180.0)
            self.assertTrue(reused.is_ready)
            self.assertEqual(reused.operations, ())
            execute_save_plan(reused)
            self.assertEqual((root / "LM.NX").read_bytes(), existing)

    def test_blank_lightmap_rejects_case_collision_and_invalid_bpm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "lm.nx").write_bytes(make_implicit_lightmap())
            workspace = open_folder(root)
            collision = plan_blank_lightmap(workspace, 120.0)
            self.assertFalse(collision.is_ready)
            self.assertIn("lightmap.case-collision", [issue.code for issue in collision.errors])

            (root / "lm.nx").unlink()
            workspace = open_folder(root)
            for bpm in (0.0, -1.0, float("nan"), float("inf")):
                with self.subTest(bpm=bpm):
                    self.assertFalse(plan_blank_lightmap(workspace, bpm).is_ready)

    def test_blank_lightmap_does_not_replace_an_invalid_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "LM.NX"
            target.write_bytes(b"broken-lightmap")
            workspace = open_folder(root)
            plan = plan_blank_lightmap(workspace, 120.0)
            self.assertFalse(plan.is_ready)
            self.assertIn("lightmap.existing-invalid", [issue.code for issue in plan.errors])
            self.assertEqual(target.read_bytes(), b"broken-lightmap")

    def test_audio_selection_is_session_only_and_may_be_external(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "charts"
            root.mkdir()
            self._complete_folder(root)
            external = Path(temporary) / "mix.wav"
            external.write_bytes(b"not-decoded-yet")
            workspace = open_folder(root).select_audio(external)
            self.assertEqual(workspace.selected_audio, external.resolve())
            self.assertEqual(set(root.iterdir()), {root / "LM.NX", root / "NM.NX"})

    def test_open_imports_nx10_without_replacing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "LEGACY.NX"
            source.write_bytes(make_nx10())
            workspace = open_folder(root)
            entry = workspace.documents[0]
            self.assertIs(entry.source_format, SourceFormat.NX10_IMPORT)
            self.assertEqual(source.read_bytes(), make_nx10())
            self.assertEqual(entry.current_bytes[:4], b"NX20")

    def test_unmaterialized_official_style_nx10_lightmap_blocks_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "LM.NX"
            source.write_bytes(make_nx10_lightmap())
            (root / "NM.NX").write_bytes(make_normal_nx20())
            workspace = open_folder(root)
            self.assertFalse(workspace.publication_report().is_ready)
            self.assertFalse(plan_save_all(workspace).is_ready)
            self.assertEqual(plan_save_all(workspace).operations, ())
            self.assertEqual(source.read_bytes(), make_nx10_lightmap())

    def test_explicit_in_place_lightmap_materialization_writes_nx20(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "LM.NX"
            source.write_bytes(make_nx10_lightmap())
            (root / "NM.NX").write_bytes(make_normal_nx20())
            workspace = open_folder(root)
            imported = workspace.document_for(source).with_output_path(source)
            workspace = workspace.replace_document(imported)

            plan = plan_save_all(workspace)
            self.assertTrue(plan.is_ready)
            self.assertEqual([operation.target for operation in plan.operations], [source])
            execute_save_plan(plan)
            self.assertEqual(source.read_bytes()[:4], b"NX20")

    def test_save_all_writes_only_modified_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._complete_folder(root)
            workspace = open_folder(root)
            chart = _edit_first_metadata(workspace.document_for(root / "NM.NX"))
            workspace = workspace.replace_document(chart)

            plan = plan_save_all(workspace)
            self.assertTrue(plan.is_ready)
            self.assertEqual([item.target.name for item in plan.operations], ["NM.NX"])
            saved = execute_save_plan(plan)
            self.assertEqual(saved, (root / "NM.NX",))
            self.assertEqual((root / "NM.NX").read_bytes(), chart.current_bytes)

    def test_save_plan_refuses_external_target_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._complete_folder(root)
            workspace = open_folder(root)
            chart = _edit_first_metadata(workspace.document_for(root / "NM.NX"))
            plan = plan_individual_save(chart)
            (root / "NM.NX").write_bytes(b"external-change")
            with self.assertRaisesRegex(WorkspaceError, "changed since save planning"):
                execute_save_plan(plan)
            self.assertEqual((root / "NM.NX").read_bytes(), b"external-change")

    def test_multi_file_failure_rolls_back_prior_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._complete_folder(root)
            workspace = open_folder(root)
            edited = tuple(_edit_first_metadata(entry) for entry in workspace.documents)
            workspace = replace(workspace, documents=edited)
            originals = {entry.path: entry.path.read_bytes() for entry in workspace.documents}
            plan = plan_save_all(workspace)
            calls = 0

            def fail_second(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected commit failure")
                os.replace(source, target)

            with self.assertRaisesRegex(WorkspaceError, "rolled back"):
                execute_save_plan(plan, replace_file=fail_second)
            for path, payload in originals.items():
                self.assertEqual(path.read_bytes(), payload)

    def test_change_during_multi_file_commit_stops_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._complete_folder(root)
            workspace = open_folder(root)
            workspace = replace(
                workspace,
                documents=tuple(_edit_first_metadata(entry) for entry in workspace.documents),
            )
            plan = plan_save_all(workspace)
            first, second = (operation.target for operation in plan.operations)
            first_original = first.read_bytes()

            def mutate_next_target(source, target):
                os.replace(source, target)
                if Path(target) == first:
                    second.write_bytes(b"concurrent-external-change")

            with self.assertRaisesRegex(WorkspaceError, "changed during save execution"):
                execute_save_plan(plan, replace_file=mutate_next_target)
            self.assertEqual(first.read_bytes(), first_original)
            self.assertEqual(second.read_bytes(), b"concurrent-external-change")

    def test_nx10_needs_explicit_native_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "LEGACY.NX"
            source.write_bytes(make_nx10())
            entry = open_folder(root).documents[0]
            edited = replace(entry, document=replace(entry.document, profile="test-profile"))
            # Profile is editor state and does not serialize, so make a binary edit too.
            edited = replace(
                edited,
                document=replace(edited.document, start_column=RawU32.from_value(1)),
            )
            edited = edited.with_document(edited.document)
            self.assertFalse(plan_individual_save(edited).is_ready)
            in_place = plan_individual_save(edited, source)
            self.assertTrue(in_place.is_ready)
            target = root / "LEGACY_IMPORTED.NX"
            plan = plan_individual_save(edited, target)
            self.assertTrue(plan.is_ready)
            execute_save_plan(plan)
            self.assertEqual(source.read_bytes(), make_nx10())
            self.assertEqual(target.read_bytes()[:4], b"NX20")

    def test_case_collisions_block_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._complete_folder(root)
            lower = root / "nm.nx"
            try:
                lower.write_bytes(make_normal_nx20())
            except FileExistsError:
                self.skipTest("case-insensitive filesystem")
            if len([path for path in root.iterdir() if path.name.casefold() == "nm.nx"]) < 2:
                self.skipTest("case-insensitive filesystem")
            workspace = open_folder(root)
            self.assertIn(
                "folder.case-collision",
                [issue.code for issue in workspace.publication_report().errors],
            )

    def test_save_all_confines_import_outputs_to_distinct_nx_names_in_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "charts"
            root.mkdir()
            self._complete_folder(root)
            legacy_path = root / "LEGACY.NX"
            legacy_path.write_bytes(make_nx10())
            workspace = open_folder(root)
            legacy = workspace.document_for(legacy_path)
            legacy = legacy.with_document(
                replace(legacy.document, start_column=RawU32.from_value(1))
            )

            outside = legacy.with_output_path(root.parent / "converted.NX")
            plan = plan_save_all(workspace.replace_document(outside))
            self.assertIn("save.target-outside-folder", [issue.code for issue in plan.errors])

            wrong_suffix = legacy.with_output_path(root / "converted.NFO")
            plan = plan_save_all(workspace.replace_document(wrong_suffix))
            self.assertIn("save.invalid-folder-suffix", [issue.code for issue in plan.errors])

            case_collision = legacy.with_output_path(root / "legacy.nx")
            plan = plan_save_all(workspace.replace_document(case_collision))
            self.assertIn("save.case-collision", [issue.code for issue in plan.errors])

            valid = legacy.with_output_path(root / "LEGACY_IMPORTED.NX")
            plan = plan_save_all(workspace.replace_document(valid))
            self.assertTrue(plan.is_ready)
            self.assertEqual(
                [operation.target.name for operation in plan.operations],
                ["LEGACY_IMPORTED.NX"],
            )


class RecoveryAndMirrorTests(unittest.TestCase):
    def test_recovery_snapshot_stays_outside_chart_folder_and_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            charts = base / "charts"
            recovery = base / "app-state" / "recovery"
            charts.mkdir()
            (charts / "LM.NX").write_bytes(make_implicit_lightmap())
            (charts / "NM.NX").write_bytes(make_normal_nx20())
            audio = base / "song.wav"
            audio.write_bytes(b"session-audio")
            workspace = open_folder(charts).select_audio(audio)
            edited = _edit_first_metadata(workspace.document_for(charts / "NM.NX"))
            workspace = workspace.replace_document(edited)

            store = RecoveryStore(recovery)
            snapshot_path = store.write(workspace)

            self.assertIsNotNone(snapshot_path)
            self.assertEqual(set(charts.iterdir()), {charts / "LM.NX", charts / "NM.NX"})
            snapshot = store.load(snapshot_path)
            self.assertEqual(len(snapshot.documents), 1)
            self.assertEqual(serialize(snapshot.documents[0].document), edited.current_bytes)
            self.assertEqual(snapshot.selected_audio, audio)
            reopened = open_folder(charts)
            restored = store.restore(reopened, snapshot_path)
            self.assertEqual(
                restored.document_for(charts / "NM.NX").current_bytes,
                edited.current_bytes,
            )
            self.assertEqual(restored.selected_audio, audio)

            (charts / "NM.NX").write_bytes(make_normal_nx20() + b"external-tail")
            changed = open_folder(charts)
            with self.assertRaisesRegex(RecoveryError, "changed on disk"):
                store.restore(changed, snapshot_path)

    def test_recovery_root_cannot_live_inside_chart_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            charts = Path(temporary)
            (charts / "LM.NX").write_bytes(make_implicit_lightmap())
            workspace = open_folder(charts)
            workspace = workspace.replace_document(_edit_first_metadata(workspace.documents[0]))
            store = RecoveryStore(charts / ".stepnx-recovery")
            with self.assertRaisesRegex(RecoveryError, "outside the chart workspace"):
                store.write(workspace)

    def test_recovered_lightmap_keeps_its_deployment_role(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            charts = base / "charts"
            charts.mkdir()
            (charts / "LM.NX").write_bytes(make_implicit_lightmap())
            workspace = open_folder(charts)
            workspace = workspace.replace_document(_edit_first_metadata(workspace.documents[0]))
            store = RecoveryStore(base / "recovery")
            snapshot_path = store.write(workspace)
            snapshot = store.load(snapshot_path)
            self.assertEqual(snapshot.documents[0].document.role.value, "lightmap")

    def test_recovery_detects_tampered_payload_and_unsafe_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            charts = base / "charts"
            charts.mkdir()
            (charts / "LM.NX").write_bytes(make_implicit_lightmap())
            workspace = open_folder(charts)
            edited = _edit_first_metadata(
                replace(
                    workspace.documents[0],
                    document=parse_bytes(make_normal_nx20(), source=str(charts / "LM.NX")),
                ).with_document(parse_bytes(make_normal_nx20(), source=str(charts / "LM.NX")))
            )
            workspace = replace(workspace, documents=(edited,))
            store = RecoveryStore(base / "recovery")
            snapshot_path = store.write(workspace)
            self.assertIsNotNone(snapshot_path)
            manifest_path = snapshot_path / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload = snapshot_path / manifest["documents"][0]["payload"]
            payload.write_bytes(payload.read_bytes() + b"tamper")
            with self.assertRaisesRegex(RecoveryError, "hash mismatch"):
                store.load(snapshot_path)

            payload.write_bytes(edited.current_bytes)
            manifest["documents"][0]["payload"] = "../escape.nx20"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RecoveryError, "unsafe payload path"):
                store.load(snapshot_path)

    def test_clean_workspace_produces_no_recovery_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "LM.NX").write_bytes(make_implicit_lightmap())
            workspace = open_folder(root)
            store = RecoveryStore(root.parent / "recovery")
            self.assertIsNone(store.write(workspace))
            self.assertEqual(store.list(), ())

    def test_mirror_compare_and_explicit_export(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "NM.NX"
            mirror = root / "MISSION.NFO"
            source.write_bytes(make_normal_nx20())
            mirror.write_bytes(make_normal_nx20())
            document = parse_bytes(source.read_bytes(), source=str(source))
            comparison = compare_mirror(document, mirror)
            self.assertTrue(comparison.binary_identical)
            self.assertEqual(comparison.structural_changes, ())

            edited = replace(document, start_column=RawU32.from_value(1))
            comparison = compare_mirror(edited, mirror)
            self.assertFalse(comparison.binary_identical)
            self.assertTrue(comparison.structural_changes)
            plan = plan_mirror_export(edited, mirror)
            self.assertTrue(plan.is_ready)
            execute_save_plan(plan)
            self.assertEqual(mirror.read_bytes(), serialize(edited))


if __name__ == "__main__":
    unittest.main()
