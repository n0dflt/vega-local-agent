import copy
import unittest
from datetime import datetime

from workflows.checkpoint_models import (
    CheckpointIntegrityError,
    CheckpointValidationError,
    WorkflowCheckpoint,
)
from workflows.models import WorkflowRun, WorkflowStatus, WorkflowStep


class CheckpointModelTests(unittest.TestCase):
    def setUp(self):
        self.run = WorkflowRun.create("feature", "Add checkpoints", [WorkflowStep("plan", "Plan")])

    def checkpoint(self):
        return WorkflowCheckpoint.create(
            self.run,
            "workflow_started",
            1,
            checkpoint_id="checkpoint-" + "a" * 32,
            created_at="2026-07-12T10:00:00+00:00",
        )

    def test_valid_model_round_trip(self):
        checkpoint = self.checkpoint()
        self.assertEqual(WorkflowCheckpoint.from_dict(checkpoint.to_dict()).to_dict(), checkpoint.to_dict())

    def test_payload_hash_is_deterministic(self):
        first = self.checkpoint()
        payload = {key: first.workflow_payload[key] for key in reversed(first.workflow_payload)}
        data = first.to_dict()
        data["workflow_payload"] = payload
        second = WorkflowCheckpoint.from_dict(data)
        self.assertEqual(first.payload_sha256, second.payload_sha256)

    def test_modified_payload_fails_integrity_verification(self):
        data = self.checkpoint().to_dict()
        data["workflow_payload"]["task"] = "tampered"
        checkpoint = WorkflowCheckpoint.from_dict(data)
        with self.assertRaises(CheckpointIntegrityError):
            checkpoint.verify_integrity()

    def test_invalid_checkpoint_id_rejected(self):
        data = self.checkpoint().to_dict()
        data["checkpoint_id"] = "checkpoint-../escape"
        with self.assertRaises(CheckpointValidationError):
            WorkflowCheckpoint.from_dict(data)

    def test_invalid_workflow_id_rejected(self):
        data = self.checkpoint().to_dict()
        data["workflow_id"] = "bad"
        data["workflow_payload"]["workflow_id"] = "bad"
        with self.assertRaises(CheckpointValidationError):
            WorkflowCheckpoint.from_dict(data)

    def test_mismatched_payload_workflow_id_rejected(self):
        data = self.checkpoint().to_dict()
        data["workflow_payload"]["workflow_id"] = "workflow-" + "b" * 32
        with self.assertRaises(CheckpointValidationError):
            WorkflowCheckpoint.from_dict(data)

    def test_mismatched_workflow_status_rejected(self):
        data = self.checkpoint().to_dict()
        data["workflow_status"] = WorkflowStatus.ANALYZING.value
        with self.assertRaises(CheckpointValidationError):
            WorkflowCheckpoint.from_dict(data)

    def test_invalid_reason_rejected(self):
        data = self.checkpoint().to_dict()
        data["reason"] = "surprise"
        with self.assertRaises(CheckpointValidationError):
            WorkflowCheckpoint.from_dict(data)

    def test_duplicate_patch_ids_rejected(self):
        data = self.checkpoint().to_dict()
        data["patch_ids"] = ["patch-a", "patch-a"]
        with self.assertRaises(CheckpointValidationError):
            WorkflowCheckpoint.from_dict(data)

    def test_naive_timestamp_rejected(self):
        data = self.checkpoint().to_dict()
        data["created_at"] = datetime.now().isoformat()
        with self.assertRaises(CheckpointValidationError):
            WorkflowCheckpoint.from_dict(data)

    def test_boolean_integer_fields_rejected(self):
        for field in ("schema_version", "sequence"):
            with self.subTest(field=field):
                data = self.checkpoint().to_dict()
                data[field] = True
                with self.assertRaises(CheckpointValidationError):
                    WorkflowCheckpoint.from_dict(data)

    def test_malformed_dictionaries_fail_closed(self):
        valid = self.checkpoint().to_dict()
        malformed = [None, {}, {**valid, "unknown": 1}, {key: value for key, value in valid.items() if key != "reason"}]
        for data in malformed:
            with self.subTest(data=data):
                with self.assertRaises(CheckpointValidationError):
                    WorkflowCheckpoint.from_dict(copy.deepcopy(data))


if __name__ == "__main__":
    unittest.main()
