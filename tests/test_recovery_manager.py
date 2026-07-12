import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from workflows.checkpoint_models import WorkflowCheckpoint
from workflows.checkpoint_store import CheckpointStore
from workflows.models import WorkflowRun, WorkflowStatus
from workflows.recovery_manager import (
    RecoveryConflictError, RecoveryConfirmationError, RecoveryNotAvailableError,
    RecoveryStorageError, WorkflowRecoveryManager,
)
from workflows.recovery_models import RecoveryDiagnosis, RecoveryResult, RecoveryState, RecoveryValidationError


POLICY = {"schema_version": 1, "hash_algorithm": "sha256", "max_checkpoints_per_workflow": 100,
          "max_payload_bytes": 1048576, "fail_closed_on_invalid_checkpoint": True,
          "allowed_reasons": ["workflow_started", "state_transition", "before_patch_apply",
                              "after_patch_apply", "verification_recorded", "review_recorded", "manual"]}


class RecoveryManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir(); (self.root / "config/checkpoint_policy.json").write_text(json.dumps(POLICY))
        self.store = CheckpointStore(self.root); self.manager = WorkflowRecoveryManager(self.root, checkpoint_store=self.store)
        self.run = WorkflowRun.create("feature", "Recover safely", [])

    @property
    def active(self): return self.root / "data/workflows/active"

    def checkpoint(self, reason="workflow_started", status=WorkflowStatus.CREATED):
        self.run.status = status
        return self.store.create(self.run, reason)

    def save(self, run=None, name=None):
        run = run or self.run; self.active.mkdir(parents=True, exist_ok=True)
        path = self.active / (name or f"{run.workflow_id}.json")
        path.write_text(json.dumps(run.to_dict()), encoding="utf-8"); return path

    def test_missing_is_not_recoverable(self):
        result = self.manager.diagnose(); self.assertEqual(result.state, RecoveryState.MISSING_ACTIVE_STATE); self.assertFalse(result.recoverable)

    def test_valid_is_healthy(self):
        path = self.save(); result = self.manager.diagnose(); self.assertEqual(result.state, RecoveryState.HEALTHY); self.assertEqual(result.active_state_filename, path.name)

    def test_corrupt_is_detected_without_modification(self):
        path = self.save(); path.write_bytes(b"{bad"); before = path.read_bytes()
        self.assertEqual(self.manager.diagnose().state, RecoveryState.CORRUPT_ACTIVE_STATE); self.assertEqual(path.read_bytes(), before)

    def test_filename_mismatch_is_corrupt(self):
        path = self.save(name="workflow-00000000000000000000000000000000.json")
        self.assertEqual(self.manager.diagnose().state, RecoveryState.CORRUPT_ACTIVE_STATE); self.assertTrue(path.exists())

    def test_multiple_active_files_fail_closed(self):
        self.save(); other = WorkflowRun.create("feature", "Other", []); self.save(other)
        self.assertEqual(self.manager.diagnose().state, RecoveryState.MULTIPLE_ACTIVE_STATES)

    def test_one_safe_checkpoint_is_recoverable(self):
        cp = self.checkpoint(); result = self.manager.diagnose()
        self.assertEqual(result.state, RecoveryState.RECOVERABLE); self.assertEqual(result.checkpoint_id, cp.checkpoint_id)

    def test_multiple_checkpoint_workflows_are_ambiguous(self):
        self.checkpoint(); other = WorkflowRun.create("feature", "Other", []); self.store.create(other, "workflow_started")
        self.assertEqual(self.manager.diagnose().state, RecoveryState.MULTIPLE_CHECKPOINT_WORKFLOWS)

    def test_latest_checkpoint_is_selected_deterministically(self):
        old = self.checkpoint(); self.run.status = WorkflowStatus.WAITING_PATCH; latest = self.store.create(self.run, "state_transition")
        self.assertEqual(self.manager.select_checkpoint(self.run.workflow_id), latest)

    def test_older_checkpoint_cannot_be_restored(self):
        old = self.checkpoint(); self.run.status = WorkflowStatus.WAITING_PATCH; self.store.create(self.run, "state_transition")
        with self.assertRaises(RecoveryConflictError): self.manager.recover(old.checkpoint_id, "CONFIRM")

    def test_history_only_is_rejected(self):
        cp = self.checkpoint(); self.store.archive_workflow(self.run.workflow_id)
        with self.assertRaises(RecoveryNotAvailableError): self.manager.recover(cp.checkpoint_id, "CONFIRM")

    def test_terminal_checkpoint_is_rejected(self):
        cp = self.checkpoint("state_transition", WorkflowStatus.COMPLETED)
        with self.assertRaises(RecoveryNotAvailableError): self.manager.recover(cp.checkpoint_id, "CONFIRM")

    def test_unsupported_reason_status_pair_is_rejected(self):
        cp = self.checkpoint("manual", WorkflowStatus.CREATED)
        with self.assertRaises(RecoveryNotAvailableError): self.manager.recover(cp.checkpoint_id, "CONFIRM")

    def test_exact_confirmation_required(self):
        cp = self.checkpoint()
        for token in ("confirm", "Confirm", "yes", "1", True, 1, None):
            with self.subTest(token=token):
                with self.assertRaises(RecoveryConfirmationError): self.manager.recover(cp.checkpoint_id, token)

    def test_corrupt_bytes_preserved_and_restore_exact(self):
        cp = self.checkpoint(); path = self.save(); original = b"\xffcorrupt\x00"; path.write_bytes(original)
        cp_before = (self.store.active_dir / f"{cp.checkpoint_id}.json").read_bytes()
        result = self.manager.recover(cp.checkpoint_id, "CONFIRM")
        self.assertEqual((self.manager.quarantine_dir / result.quarantine_filename).read_bytes(), original)
        self.assertEqual(WorkflowRun.from_dict(json.loads(path.read_text())).to_dict(), cp.workflow_payload)
        self.assertEqual((self.store.active_dir / f"{cp.checkpoint_id}.json").read_bytes(), cp_before)
        self.assertFalse(list(self.active.glob("*.tmp")))

    def test_valid_unrelated_and_differing_state_block(self):
        cp = self.checkpoint(); other = WorkflowRun.create("feature", "Other", []); self.save(other)
        with self.assertRaises(RecoveryConflictError): self.manager.recover(cp.checkpoint_id, "CONFIRM")
        (self.active / f"{other.workflow_id}.json").unlink(); changed = WorkflowRun.from_dict(cp.workflow_payload); changed.task = "Changed"; self.save(changed)
        with self.assertRaises(RecoveryConflictError): self.manager.recover(cp.checkpoint_id, "CONFIRM")

    def test_identical_state_is_idempotent(self):
        cp = self.checkpoint(); self.save(); result = self.manager.recover(cp.checkpoint_id, "CONFIRM")
        self.assertTrue(result.already_recovered); self.assertFalse(result.recovered); self.assertTrue(result.requires_resume)

    def test_missing_state_is_restored_and_waiting_confirmation_unchanged(self):
        cp = self.checkpoint("state_transition", WorkflowStatus.WAITING_CONFIRMATION)
        result = self.manager.recover(cp.checkpoint_id, "CONFIRM")
        restored = WorkflowRun.from_dict(json.loads((self.active / result.active_state_filename).read_text()))
        self.assertEqual(restored.status, WorkflowStatus.WAITING_CONFIRMATION)
        self.assertEqual(restored.required_confirmations, self.run.required_confirmations)

    def test_executing_warning(self):
        cp = self.checkpoint("before_patch_apply", WorkflowStatus.EXECUTING)
        result = self.manager.recover(cp.checkpoint_id, "CONFIRM")
        self.assertIn("WorkflowEngine.resume()", result.warnings[0])

    def test_path_traversal_workflow_id_rejected(self):
        with self.assertRaises(RecoveryNotAvailableError): self.manager.select_checkpoint("../escape")

    def test_recovery_models_round_trip_strictly(self):
        diagnosis = RecoveryDiagnosis(RecoveryState.MISSING_ACTIVE_STATE)
        self.assertEqual(RecoveryDiagnosis.from_dict(diagnosis.to_dict()), diagnosis)
        cp = self.checkpoint(); result = self.manager.recover(cp.checkpoint_id, "CONFIRM")
        self.assertEqual(RecoveryResult.from_dict(result.to_dict()), result)

    def test_unknown_recovery_model_fields_fail_closed(self):
        diagnosis = RecoveryDiagnosis(RecoveryState.MISSING_ACTIVE_STATE)
        cp = self.checkpoint(); result = self.manager.recover(cp.checkpoint_id, "CONFIRM")
        for data, model in ((dict(diagnosis.to_dict(), extra=True), RecoveryDiagnosis),
                            (dict(result.to_dict(), extra=True), RecoveryResult)):
            with self.assertRaises(RecoveryValidationError): model.from_dict(data)

    def test_boolean_integer_rejected(self):
        data = RecoveryDiagnosis(RecoveryState.MISSING_ACTIVE_STATE).to_dict(); data["checkpoint_sequence"] = True
        with self.assertRaises(RecoveryValidationError): RecoveryDiagnosis.from_dict(data)

    def test_malformed_checkpoint_fails_closed(self):
        (self.store.active_dir / "checkpoint-00000000000000000000000000000000.json").write_text("{}")
        with self.assertRaises(RecoveryStorageError): self.manager.diagnose()

    def test_boolean_confirmation_is_rejected(self):
        cp = self.checkpoint()
        with self.assertRaises(RecoveryConfirmationError):
            self.manager.recover(cp.checkpoint_id, True)

    def test_existing_quarantine_destination_is_not_overwritten(self):
        cp = self.checkpoint(); source = self.save(); source.write_bytes(b"corrupt")
        suffix = "0" * 32
        destination = self.manager.quarantine_dir / f"{source.stem}.corrupt.{suffix}.json"
        destination.write_bytes(b"sentinel")
        with patch("workflows.recovery_manager.uuid4", return_value=Mock(hex=suffix)):
            with self.assertRaises(RecoveryStorageError):
                self.manager.recover(cp.checkpoint_id, "CONFIRM")
        self.assertEqual(destination.read_bytes(), b"sentinel")
        self.assertEqual(source.read_bytes(), b"corrupt")

    def test_valid_unrelated_active_workflow_blocks_recovery(self):
        cp = self.checkpoint(); other = WorkflowRun.create("feature", "Other", []); self.save(other)
        with self.assertRaises(RecoveryConflictError):
            self.manager.recover(cp.checkpoint_id, "CONFIRM")

    def test_valid_different_matching_state_blocks_recovery(self):
        cp = self.checkpoint(); changed = WorkflowRun.from_dict(cp.workflow_payload); changed.task = "Changed"; self.save(changed)
        with self.assertRaises(RecoveryConflictError):
            self.manager.recover(cp.checkpoint_id, "CONFIRM")

    def test_restored_filename_comes_from_validated_workflow_id(self):
        cp = self.checkpoint(); result = self.manager.recover(cp.checkpoint_id, "CONFIRM")
        self.assertEqual(result.active_state_filename, f"{self.run.workflow_id}.json")
        self.assertEqual((self.active / result.active_state_filename).resolve().parent, self.active.resolve())

    def test_restored_json_loads_and_complete_payload_matches(self):
        self.run.context["detail"] = {"nested": [1, "two"]}; cp = self.checkpoint()
        result = self.manager.recover(cp.checkpoint_id, "CONFIRM")
        raw = json.loads((self.active / result.active_state_filename).read_text(encoding="utf-8"))
        restored = WorkflowRun.from_dict(raw)
        self.assertEqual(restored.to_dict(), cp.workflow_payload)
        self.assertEqual(raw, cp.workflow_payload)

    def test_checkpoint_file_is_not_modified(self):
        cp = self.checkpoint(); checkpoint_path = self.store.active_dir / f"{cp.checkpoint_id}.json"
        before = checkpoint_path.read_bytes(); self.manager.recover(cp.checkpoint_id, "CONFIRM")
        self.assertEqual(checkpoint_path.read_bytes(), before)

    def test_recovery_does_not_invoke_engine_or_external_operations(self):
        cp = self.checkpoint()
        with patch("workflows.engine.WorkflowEngine.resume") as resume, \
             patch("os.system") as terminal, patch("subprocess.run") as command:
            result = self.manager.recover(cp.checkpoint_id, "CONFIRM")
        resume.assert_not_called(); terminal.assert_not_called(); command.assert_not_called()
        self.assertTrue(result.requires_resume)

    def test_waiting_confirmation_does_not_grant_confirmation(self):
        self.run.required_confirmations = ["patch_apply"]
        cp = self.checkpoint("state_transition", WorkflowStatus.WAITING_CONFIRMATION)
        result = self.manager.recover(cp.checkpoint_id, "CONFIRM")
        restored = WorkflowRun.from_dict(json.loads((self.active / result.active_state_filename).read_text()))
        self.assertEqual(restored.required_confirmations, ["patch_apply"])
        self.assertNotIn("confirmed", restored.artifacts)

    def test_successful_restore_removes_temporary_files(self):
        cp = self.checkpoint(); self.manager.recover(cp.checkpoint_id, "CONFIRM")
        self.assertEqual(list(self.active.glob("*.tmp")), [])

    def test_quarantine_failure_prevents_restored_write(self):
        cp = self.checkpoint(); source = self.save(); source.write_bytes(b"corrupt")
        with patch.object(self.manager, "_quarantine", side_effect=RecoveryStorageError("failed")), \
             patch.object(self.manager, "_write") as write:
            with self.assertRaises(RecoveryStorageError): self.manager.recover(cp.checkpoint_id, "CONFIRM")
        write.assert_not_called(); self.assertEqual(source.read_bytes(), b"corrupt")

    def test_write_failure_preserves_quarantined_original(self):
        cp = self.checkpoint(); source = self.save(); original = b"corrupt-original"; source.write_bytes(original)
        with patch.object(self.manager, "_write", side_effect=RecoveryStorageError("failed")):
            with self.assertRaises(RecoveryStorageError): self.manager.recover(cp.checkpoint_id, "CONFIRM")
        quarantined = list(self.manager.quarantine_dir.glob("*.json"))
        self.assertEqual(len(quarantined), 1); self.assertEqual(quarantined[0].read_bytes(), original)
        self.assertFalse(source.exists())

    def test_unmanaged_quarantine_path_is_rejected(self):
        outside = self.root / "outside.json"; outside.write_text("corrupt")
        with self.assertRaises(RecoveryStorageError): self.manager._quarantine(outside)
        self.assertTrue(outside.exists())

    def test_history_checkpoint_is_ignored_during_diagnosis(self):
        self.checkpoint(); self.store.archive_workflow(self.run.workflow_id)
        result = self.manager.diagnose()
        self.assertEqual(result.state, RecoveryState.MISSING_ACTIVE_STATE)

    def test_latest_unsafe_checkpoint_does_not_fallback(self):
        self.checkpoint(); latest = self.checkpoint("manual", WorkflowStatus.CREATED)
        with self.assertRaises(RecoveryNotAvailableError): self.manager.select_checkpoint(self.run.workflow_id)
        with self.assertRaises(RecoveryNotAvailableError): self.manager.recover(latest.checkpoint_id, "CONFIRM")

    def test_duplicate_checkpoint_sequences_fail_closed(self):
        self.checkpoint(); second = self.checkpoint("state_transition", WorkflowStatus.WAITING_PATCH)
        path = self.store.active_dir / f"{second.checkpoint_id}.json"
        data = json.loads(path.read_text()); data["sequence"] = 1; path.write_text(json.dumps(data))
        with self.assertRaises(RecoveryConflictError): self.manager.select_checkpoint(self.run.workflow_id)

    def test_diagnosis_never_modifies_managed_files(self):
        self.checkpoint(); active = self.save(); active.write_bytes(b"corrupt-diagnosis")
        before_active = active.read_bytes()
        checkpoint_files = {path.name: path.read_bytes() for path in self.store.active_dir.glob("*.json")}
        quarantine_before = list(self.manager.quarantine_dir.iterdir())
        self.assertEqual(self.manager.diagnose().state, RecoveryState.RECOVERABLE)
        self.assertEqual(active.read_bytes(), before_active)
        self.assertEqual({path.name: path.read_bytes() for path in self.store.active_dir.glob("*.json")}, checkpoint_files)
        self.assertEqual(list(self.manager.quarantine_dir.iterdir()), quarantine_before)

    def test_checkpoint_storage_corruption_is_not_swallowed_during_diagnosis(self):
        self.checkpoint(); active = self.save(); active.write_bytes(b"corrupt")
        (self.store.active_dir / "checkpoint-00000000000000000000000000000000.json").write_text("{}")
        with self.assertRaises(RecoveryStorageError): self.manager.diagnose()


if __name__ == "__main__": unittest.main()
