from __future__ import annotations

import errno
import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from stepnx.core.scalars import RawU32
from stepnx.workspace import (
    RecoveryError,
    RecoveryStore,
    SaveOperation,
    SavePlan,
    WorkspaceError,
    execute_save_plan,
    open_folder,
    plan_individual_save,
    plan_save_all,
)
from tests.fixture_factory import make_implicit_lightmap, make_normal_nx20


def _edit_first_metadata(entry):
    if not entry.document.header_metadata:
        document = replace(entry.document, lightmap_flag=RawU32.from_value(1))
        return entry.with_document(document)
    first = entry.document.header_metadata[0]
    edited_first = replace(first, value=RawU32.from_value(first.value.value + 1), span=None)
    document = replace(
        entry.document,
        header_metadata=(edited_first, *entry.document.header_metadata[1:]),
    )
    return entry.with_document(document)


def _transaction_artifacts(root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in root.iterdir()
        if path.name.endswith(".stepnx-stage") or path.name.endswith(".stepnx-original")
    )


def _workspace_with_two_modified_charts(root: Path):
    (root / "LM.NX").write_bytes(make_implicit_lightmap())
    (root / "A.NX").write_bytes(make_normal_nx20())
    (root / "B.NX").write_bytes(make_normal_nx20())
    workspace = open_folder(root)
    for name in ("A.NX", "B.NX"):
        workspace = workspace.replace_document(
            _edit_first_metadata(workspace.document_for(root / name))
        )
    return workspace


class SaveTortureTests(unittest.TestCase):
    def test_temp_creation_permission_failure_keeps_original_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "NM.NX").write_bytes(make_normal_nx20())
            entry = _edit_first_metadata(open_folder(root).documents[0])
            original = entry.path.read_bytes()
            plan = plan_individual_save(entry)

            with mock.patch(
                "stepnx.workspace.durability.tempfile.NamedTemporaryFile",
                side_effect=PermissionError(errno.EACCES, "injected permission failure"),
            ):
                with self.assertRaisesRegex(WorkspaceError, "save failed"):
                    execute_save_plan(plan)

            self.assertEqual(entry.path.read_bytes(), original)
            self.assertEqual(_transaction_artifacts(root), ())

    def test_stage_fsync_disk_full_keeps_original_and_removes_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "NM.NX").write_bytes(make_normal_nx20())
            entry = _edit_first_metadata(open_folder(root).documents[0])
            original = entry.path.read_bytes()
            plan = plan_individual_save(entry)

            with mock.patch(
                "stepnx.workspace.durability.os.fsync",
                side_effect=OSError(errno.ENOSPC, "injected disk full"),
            ):
                with self.assertRaisesRegex(WorkspaceError, "disk full"):
                    execute_save_plan(plan)

            self.assertEqual(entry.path.read_bytes(), original)
            self.assertEqual(_transaction_artifacts(root), ())

    def test_backup_copy_failure_keeps_original_and_removes_temporaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "NM.NX").write_bytes(make_normal_nx20())
            entry = _edit_first_metadata(open_folder(root).documents[0])
            original = entry.path.read_bytes()
            plan = plan_individual_save(entry)

            with mock.patch(
                "stepnx.workspace.durability.shutil.copy2",
                side_effect=PermissionError(errno.EACCES, "injected backup failure"),
            ):
                with self.assertRaisesRegex(WorkspaceError, "backup failure"):
                    execute_save_plan(plan)

            self.assertEqual(entry.path.read_bytes(), original)
            self.assertEqual(_transaction_artifacts(root), ())

    def test_keyboard_interrupt_after_first_commit_rolls_back_before_propagating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace_with_two_modified_charts(root)
            plan = plan_save_all(workspace)
            self.assertEqual(len(plan.operations), 2)
            originals = {operation.target: operation.target.read_bytes() for operation in plan.operations}
            real_replace = os.replace
            calls = 0

            def interrupt_second(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise KeyboardInterrupt("injected interruption")
                real_replace(source, target)

            with self.assertRaises(KeyboardInterrupt):
                execute_save_plan(plan, replace_file=interrupt_second)

            for path, payload in originals.items():
                self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(_transaction_artifacts(root), ())

    def test_rollback_failure_preserves_original_backup_for_manual_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = _workspace_with_two_modified_charts(root)
            plan = plan_save_all(workspace)
            first, second = plan.operations
            first_original = first.target.read_bytes()
            second_original = second.target.read_bytes()
            real_replace = os.replace
            calls = 0

            def fail_second_commit(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected second commit failure")
                real_replace(source, target)

            with mock.patch(
                "stepnx.workspace.durability.os.replace",
                side_effect=PermissionError(errno.EACCES, "injected rollback failure"),
            ):
                with self.assertRaisesRegex(WorkspaceError, "original preserved at") as raised:
                    execute_save_plan(plan, replace_file=fail_second_commit)

            self.assertNotEqual(first.target.read_bytes(), first_original)
            self.assertEqual(second.target.read_bytes(), second_original)
            backups = tuple(root.glob(f".{first.target.name}.*.stepnx-original"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), first_original)
            self.assertIn(backups[0].name, str(raised.exception))
            self.assertFalse(
                any(path.name.endswith(".stepnx-stage") for path in root.iterdir())
            )

    def test_new_target_is_removed_when_a_later_commit_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            new_target = (root / "NEW.NX").resolve()
            existing_target = (root / "EXISTING.NX").resolve()
            existing_payload = b"old-existing"
            existing_target.write_bytes(existing_payload)
            expected_hash = hashlib.sha256(existing_payload).hexdigest()
            plan = SavePlan(
                (
                    SaveOperation(None, new_target, b"new-target", None, False),
                    SaveOperation(None, existing_target, b"new-existing", expected_hash, True),
                ),
                (),
                False,
            )
            real_replace = os.replace
            calls = 0

            def fail_second(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected later failure")
                real_replace(source, target)

            with self.assertRaisesRegex(WorkspaceError, "rolled back"):
                execute_save_plan(plan, replace_file=fail_second)

            self.assertFalse(new_target.exists())
            self.assertEqual(existing_target.read_bytes(), existing_payload)
            self.assertEqual(_transaction_artifacts(root), ())

    def test_successful_save_leaves_no_transaction_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "NM.NX").write_bytes(make_normal_nx20())
            entry = _edit_first_metadata(open_folder(root).documents[0])
            plan = plan_individual_save(entry)

            execute_save_plan(plan)

            self.assertEqual(entry.path.read_bytes(), entry.current_bytes)
            self.assertEqual(_transaction_artifacts(root), ())


class RecoveryTortureTests(unittest.TestCase):
    def _modified_workspace(self, base: Path):
        charts = base / "charts"
        charts.mkdir()
        (charts / "LM.NX").write_bytes(make_implicit_lightmap())
        (charts / "NM.NX").write_bytes(make_normal_nx20())
        workspace = open_folder(charts)
        return workspace.replace_document(
            _edit_first_metadata(workspace.document_for(charts / "NM.NX"))
        )

    def test_recovery_staging_creation_permission_failure_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = self._modified_workspace(base)
            store = RecoveryStore(base / "recovery")

            with mock.patch(
                "stepnx.workspace.durability.tempfile.mkdtemp",
                side_effect=PermissionError(errno.EACCES, "injected staging permission failure"),
            ):
                with self.assertRaisesRegex(RecoveryError, "cannot create recovery staging area"):
                    store.write(workspace)

            self.assertEqual(store.list(), ())

    def test_recovery_payload_fsync_disk_full_removes_hidden_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = self._modified_workspace(base)
            store = RecoveryStore(base / "recovery")

            with mock.patch(
                "stepnx.workspace.durability.os.fsync",
                side_effect=OSError(errno.ENOSPC, "injected recovery disk full"),
            ):
                with self.assertRaisesRegex(RecoveryError, "disk full"):
                    store.write(workspace)

            self.assertEqual(store.list(), ())
            self.assertEqual(tuple(store.root.iterdir()), ())

    def test_recovery_keyboard_interrupt_during_manifest_cleans_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = self._modified_workspace(base)
            store = RecoveryStore(base / "recovery")
            real_fsync = os.fsync
            calls = 0

            def interrupt_manifest(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise KeyboardInterrupt("injected recovery interruption")
                real_fsync(fd)

            with mock.patch("stepnx.workspace.durability.os.fsync", side_effect=interrupt_manifest):
                with self.assertRaises(KeyboardInterrupt):
                    store.write(workspace)

            self.assertEqual(store.list(), ())
            self.assertEqual(tuple(store.root.iterdir()), ())

    def test_recovery_publish_rename_failure_cleans_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = self._modified_workspace(base)
            store = RecoveryStore(base / "recovery")

            with mock.patch(
                "stepnx.workspace.durability.os.replace",
                side_effect=PermissionError(errno.EACCES, "injected recovery publish failure"),
            ):
                with self.assertRaisesRegex(RecoveryError, "publish failure"):
                    store.write(workspace)

            self.assertEqual(store.list(), ())
            self.assertEqual(tuple(store.root.iterdir()), ())

    def test_recovery_list_ignores_orphan_hidden_staging_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "recovery"
            root.mkdir()
            orphan = root / ".0123456789abcdef0123456789abcdef.crashed"
            orphan.mkdir()
            (orphan / "manifest.json").write_text("{}", encoding="utf-8")
            final = root / "0123456789abcdef0123456789abcdef"
            final.mkdir()
            (final / "manifest.json").write_text("{}", encoding="utf-8")

            store = RecoveryStore(root)

            self.assertEqual(
                tuple(path.name for path in store.list()),
                (final.name,),
            )

    def test_matching_hash_invalid_nx20_payload_is_reported_as_recovery_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = self._modified_workspace(base)
            store = RecoveryStore(base / "recovery")
            snapshot = store.write(workspace)
            self.assertIsNotNone(snapshot)
            manifest_path = snapshot / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            payload_path = snapshot / manifest["documents"][0]["payload"]
            invalid_payload = b"NX20"
            payload_path.write_bytes(invalid_payload)
            manifest["documents"][0]["payload_sha256"] = hashlib.sha256(
                invalid_payload
            ).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(RecoveryError, "invalid recovery snapshot payload"):
                store.load(snapshot)


if __name__ == "__main__":
    unittest.main()
