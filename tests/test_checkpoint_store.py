import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflows.checkpoint_store import (
    CheckpointLimitError,
    CheckpointStorageError,
    CheckpointStore,
)
from workflows.checkpoint_models import canonical_payload_bytes, payload_sha256
from workflows.models import WorkflowRun, WorkflowStep


POLICY = {
    "schema_version": 1,
    "hash_algorithm": "sha256",
    "max_checkpoints_per_workflow": 30,
    "max_payload_bytes": 2097152,
    "fail_closed_on_invalid_checkpoint": True,
    "allowed_reasons": [
        "workflow_started", "state_transition", "before_patch_apply", "after_patch_apply",
        "verification_recorded", "review_recorded", "manual",
    ],
}


class CheckpointStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        self.write_policy(POLICY)
        self.store = CheckpointStore(self.root)
        self.run = WorkflowRun.create("feature", "Add checkpoints", [WorkflowStep("plan", "Plan")])

    def tearDown(self):
        self.temporary.cleanup()

    def write_policy(self, policy):
        (self.root / "config" / "checkpoint_policy.json").write_text(json.dumps(policy), encoding="utf-8")

    def checkpoint_path(self, checkpoint):
        return self.store.active_dir / f"{checkpoint.checkpoint_id}.json"

    def rewrite_checkpoint(self, checkpoint, mutate):
        path = self.checkpoint_path(checkpoint)
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_runtime_directories_are_created(self):
        self.assertTrue(self.store.active_dir.is_dir())
        self.assertTrue(self.store.history_dir.is_dir())
        self.assertTrue(self.store.quarantine_dir.is_dir())

    def test_checkpoint_is_created_and_loaded(self):
        created = self.store.create(self.run, "workflow_started")
        self.assertEqual(self.store.get(created.checkpoint_id), created)

    def test_sequences_increase_across_active_and_history(self):
        first = self.store.create(self.run, "workflow_started")
        self.store.archive_workflow(self.run.workflow_id)
        second = self.store.create(self.run, "manual")
        self.assertEqual((first.sequence, second.sequence), (1, 2))

    def test_duplicate_checkpoint_file_is_not_overwritten(self):
        fixed_id = "checkpoint-" + "a" * 32
        destination = self.store.active_dir / f"{fixed_id}.json"
        destination.write_text("sentinel", encoding="utf-8")
        with patch("workflows.checkpoint_models.uuid4", return_value=type("UUID", (), {"hex": "a" * 32})()):
            with self.assertRaises(CheckpointStorageError):
                self.store.create(self.run, "manual")
        self.assertEqual(destination.read_text(encoding="utf-8"), "sentinel")

    def test_payload_size_limit_is_enforced(self):
        policy = dict(POLICY, max_payload_bytes=1024)
        self.write_policy(policy)
        store = CheckpointStore(self.root)
        self.run.context["large"] = "x" * 2000
        with self.assertRaises(CheckpointLimitError):
            store.create(self.run, "manual")

    def test_checkpoint_count_limit_is_enforced(self):
        self.write_policy(dict(POLICY, max_checkpoints_per_workflow=1))
        store = CheckpointStore(self.root)
        store.create(self.run, "manual")
        with self.assertRaises(CheckpointLimitError):
            store.create(self.run, "manual")

    def test_invalid_policy_is_rejected(self):
        for invalid in ({**POLICY, "hash_algorithm": "md5"}, {**POLICY, "max_payload_bytes": True}):
            with self.subTest(invalid=invalid):
                self.write_policy(invalid)
                with self.assertRaises(CheckpointStorageError):
                    CheckpointStore(self.root)

    def test_corrupt_json_is_rejected(self):
        (self.store.active_dir / ("checkpoint-" + "a" * 32 + ".json")).write_text("{", encoding="utf-8")
        with self.assertRaises(CheckpointStorageError):
            self.store.list_for_workflow(self.run.workflow_id)

    def test_hash_tampering_is_rejected(self):
        checkpoint = self.store.create(self.run, "manual")
        path = self.store.active_dir / f"{checkpoint.checkpoint_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["workflow_payload"]["task"] = "tampered"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(CheckpointStorageError):
            self.store.get(checkpoint.checkpoint_id)

    def test_filename_id_mismatch_is_rejected(self):
        checkpoint = self.store.create(self.run, "manual")
        source = self.store.active_dir / f"{checkpoint.checkpoint_id}.json"
        target = self.store.active_dir / ("checkpoint-" + "b" * 32 + ".json")
        source.rename(target)
        with self.assertRaises(CheckpointStorageError):
            self.store.list_for_workflow(self.run.workflow_id)

    def test_active_checkpoints_archive_without_rewriting(self):
        checkpoint = self.store.create(self.run, "manual")
        source = self.store.active_dir / f"{checkpoint.checkpoint_id}.json"
        original = source.read_bytes()
        self.assertEqual(self.store.archive_workflow(self.run.workflow_id), 1)
        destination = self.store.history_dir / source.name
        self.assertEqual(destination.read_bytes(), original)
        self.assertFalse(source.exists())

    def test_existing_archive_destination_is_not_overwritten(self):
        checkpoint = self.store.create(self.run, "manual")
        destination = self.store.history_dir / f"{checkpoint.checkpoint_id}.json"
        destination.write_text("sentinel", encoding="utf-8")
        with self.assertRaises(CheckpointStorageError):
            self.store.archive_workflow(self.run.workflow_id)
        self.assertEqual(destination.read_text(encoding="utf-8"), "sentinel")

    def test_latest_is_deterministic(self):
        first = self.store.create(self.run, "workflow_started")
        second = self.store.create(self.run, "manual")
        self.assertEqual(self.store.latest(self.run.workflow_id), second)
        self.assertNotEqual(first.checkpoint_id, second.checkpoint_id)

    def test_path_traversal_is_rejected(self):
        outside = self.root / "outside.json"
        outside.write_text("data", encoding="utf-8")
        with self.assertRaises(CheckpointStorageError):
            self.store.quarantine_file(self.store.active_dir / ".." / ".." / "outside.json", "bad")

    def test_unmanaged_file_cannot_be_quarantined(self):
        outside = self.root / "outside.json"
        outside.write_text("data", encoding="utf-8")
        with self.assertRaises(CheckpointStorageError):
            self.store.quarantine_file(outside, "corrupt")

    def test_successful_write_leaves_no_temporary_file(self):
        self.store.create(self.run, "manual")
        self.assertEqual(list(self.store.active_dir.glob("*.tmp")), [])

    def test_workspace_root_absolute_path_is_accepted(self):
        self.run.context["working_directory"] = str(self.root.resolve())
        checkpoint = self.store.create(self.run, "manual")
        self.assertEqual(self.store.get(checkpoint.checkpoint_id), checkpoint)

    def test_absolute_path_inside_workspace_is_accepted(self):
        self.run.context["target"] = str((self.root / "src" / "module.py").resolve())
        checkpoint = self.store.create(self.run, "manual")
        self.assertEqual(self.store.get(checkpoint.checkpoint_id), checkpoint)

    def test_windows_external_absolute_path_is_rejected(self):
        self.run.context["target"] = r"Z:\external\secret.txt"
        with self.assertRaises(CheckpointStorageError):
            self.store.create(self.run, "manual")

    def test_posix_external_absolute_path_is_rejected(self):
        self.run.context["target"] = "/etc/passwd"
        with self.assertRaises(CheckpointStorageError):
            self.store.create(self.run, "manual")

    def test_sensitive_nested_dictionary_key_is_rejected(self):
        self.run.context["service"] = {"api_key": "value"}
        with self.assertRaises(CheckpointStorageError):
            self.store.create(self.run, "manual")

    def test_sensitive_key_inside_list_item_is_rejected(self):
        self.run.context["services"] = [{"refreshToken": "value"}]
        with self.assertRaises(CheckpointStorageError):
            self.store.create(self.run, "manual")

    def test_similar_ordinary_words_are_not_rejected(self):
        self.run.context["secretary"] = "Alice"
        self.run.context["environmentalist"] = "Bob"
        checkpoint = self.store.create(self.run, "manual")
        self.assertEqual(self.store.get(checkpoint.checkpoint_id), checkpoint)

    def test_unsupported_schema_is_rejected_during_load(self):
        checkpoint = self.store.create(self.run, "manual")
        self.rewrite_checkpoint(checkpoint, lambda data: data.update(schema_version=2))
        with self.assertRaises(CheckpointStorageError):
            self.store.get(checkpoint.checkpoint_id)

    def test_policy_disabled_reason_is_rejected_during_load(self):
        checkpoint = self.store.create(self.run, "manual")
        policy = dict(POLICY)
        policy["allowed_reasons"] = [reason for reason in POLICY["allowed_reasons"] if reason != "manual"]
        self.write_policy(policy)
        restricted_store = CheckpointStore(self.root)
        with self.assertRaises(CheckpointStorageError):
            restricted_store.get(checkpoint.checkpoint_id)

    def test_oversized_validly_hashed_payload_is_rejected_during_load(self):
        checkpoint = self.store.create(self.run, "manual")

        def enlarge(data):
            data["workflow_payload"]["context"]["large"] = "x" * 2000
            data["payload_sha256"] = payload_sha256(data["workflow_payload"])

        self.rewrite_checkpoint(checkpoint, enlarge)
        self.write_policy(dict(POLICY, max_payload_bytes=1024))
        restricted_store = CheckpointStore(self.root)
        with self.assertRaises(CheckpointStorageError):
            restricted_store.get(checkpoint.checkpoint_id)

    def test_unhashable_allowed_reasons_raise_storage_error(self):
        for reasons in ([{"invalid": True}], [["workflow_started"]]):
            with self.subTest(reasons=reasons):
                self.write_policy(dict(POLICY, allowed_reasons=reasons))
                with self.assertRaises(CheckpointStorageError) as caught:
                    CheckpointStore(self.root)
                self.assertNotIsInstance(caught.exception.__cause__, TypeError)

    def test_canonical_payload_size_excludes_checkpoint_formatting(self):
        checkpoint = self.store.create(self.run, "manual")
        self.assertLess(
            len(canonical_payload_bytes(checkpoint.workflow_payload)),
            len(self.checkpoint_path(checkpoint).read_bytes()),
        )


if __name__ == "__main__":
    unittest.main()
