import unittest

from workflows.models import WorkflowRun, WorkflowStateError, WorkflowStatus, WorkflowStep, validate_transition


class WorkflowModelTests(unittest.TestCase):
    def test_all_required_statuses_exist(self):
        self.assertEqual(
            {status.value for status in WorkflowStatus},
            {"created", "analyzing", "planning", "waiting_patch", "waiting_confirmation", "executing", "verifying", "completed", "failed", "cancelled"},
        )

    def test_model_round_trip(self):
        run = WorkflowRun.create("feature", "Add search", [WorkflowStep("analyze", "Analyze")])
        self.assertEqual(WorkflowRun.from_dict(run.to_dict()).to_dict(), run.to_dict())

    def test_allowed_transition(self):
        self.assertEqual(validate_transition("created", "analyzing"), WorkflowStatus.ANALYZING)

    def test_forbidden_transition(self):
        with self.assertRaises(WorkflowStateError):
            validate_transition("created", "completed")


if __name__ == "__main__":
    unittest.main()
