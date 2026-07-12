import unittest

from workflows.models import WorkflowRun, WorkflowStateError, WorkflowStatus, WorkflowStep, validate_transition


class WorkflowModelTests(unittest.TestCase):
    def test_all_required_statuses_exist(self):
        self.assertEqual(
            {status.value for status in WorkflowStatus},
            {"created", "analyzing", "planning", "waiting_patch", "waiting_confirmation", "executing", "verifying", "reviewing", "completed", "failed", "cancelled"},
        )

    def test_model_round_trip(self):
        run = WorkflowRun.create("feature", "Add search", [WorkflowStep("analyze", "Analyze")])
        self.assertEqual(WorkflowRun.from_dict(run.to_dict()).to_dict(), run.to_dict())

    def test_allowed_transition(self):
        self.assertEqual(validate_transition("created", "analyzing"), WorkflowStatus.ANALYZING)

    def test_forbidden_transition(self):
        with self.assertRaises(WorkflowStateError):
            validate_transition("created", "completed")

    def test_fix_attempt_limit_is_validated_on_load(self):
        run = WorkflowRun.create("feature", "Add search", [])
        data = run.to_dict()
        data["max_fix_attempts"] = 0
        with self.assertRaises(ValueError):
            WorkflowRun.from_dict(data)

    def test_v23_json_without_review_fields_loads_safely(self):
        run = WorkflowRun.create("feature", "Add search", [])
        data = run.to_dict()
        data.pop("review_results")
        data.pop("patch_request_reason")
        restored = WorkflowRun.from_dict(data)
        self.assertEqual(restored.review_results, [])
        self.assertEqual(restored.patch_request_reason, "initial")


if __name__ == "__main__":
    unittest.main()
