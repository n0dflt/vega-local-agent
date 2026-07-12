import tempfile
import unittest
from pathlib import Path

from core.confirmation_manager import ConfirmationManager
from core.intent_router import ConfirmationDecision
from review.models import ReviewFinding, ReviewReport
from workflows import WorkflowEngine, default_registry
from workflows.checkpoint_models import CheckpointReason, WorkflowCheckpoint
from workflows.engine import WorkflowStorageError
from workflows.models import WorkflowError, WorkflowStatus


class RecordingCheckpointStore:
    def __init__(self):
        self.active = []
        self.history = []
        self.archive_calls = []
        self.fail_next_create = False
        self.fail_archive = False

    def create(self, run, reason):
        if self.fail_next_create:
            self.fail_next_create = False
            raise RuntimeError("checkpoint unavailable")
        checkpoint = WorkflowCheckpoint.create(
            run,
            reason,
            len(self.active) + len(self.history) + 1,
        )
        self.active.append(checkpoint)
        return checkpoint

    def latest(self, workflow_id, include_history=False):
        source = self.active + (self.history if include_history else [])
        matches = [item for item in source if item.workflow_id == workflow_id]
        return matches[-1] if matches else None

    def archive_workflow(self, workflow_id):
        self.archive_calls.append(workflow_id)
        if self.fail_archive:
            raise RuntimeError("checkpoint archive unavailable")
        matches = [item for item in self.active if item.workflow_id == workflow_id]
        self.active = [item for item in self.active if item.workflow_id != workflow_id]
        self.history.extend(matches)
        return len(matches)


class PatchStub:
    def __init__(self, checkpoints=None):
        self.checkpoints = checkpoints
        self.applied = 0
        self.state = "pending"

    def prepare(self, run):
        patch_id = run.artifacts["requested_patch_id"]
        return {"patch_id": patch_id, "status": "pending", "target_path": "sample.py"}

    def apply(self, patch_id, confirmed=False):
        if self.checkpoints is not None:
            latest = self.checkpoints.latest(self.checkpoints.active[-1].workflow_id)
            if latest.reason is not CheckpointReason.BEFORE_PATCH_APPLY:
                raise AssertionError("patch applied before checkpoint")
        if self.state == "applied":
            raise AssertionError("patch applied twice")
        self.applied += 1
        self.state = "applied"
        return {"ok": True, "data": {"patch_id": patch_id, "status": "applied", "target_path": "sample.py"}}

    def inspect(self, patch_id):
        return {"patch_id": patch_id, "status": self.state, "target_path": "sample.py"}


class Verifier:
    def __init__(self, results=(True,)):
        self.results = list(results)
        self.runs = 0

    def run_once(self, run):
        value = self.results[self.runs]
        self.runs += 1
        return {"ok": value, "runs": self.runs, "error": None if value else "failed"}


class Reviewer:
    def __init__(self, severities=(None,)):
        self.severities = list(severities)
        self.runs = 0

    def run_once(self, run):
        severity = self.severities[self.runs]
        self.runs += 1
        findings = []
        if severity:
            findings.append(ReviewFinding("finding-test", severity, "correctness", "sample.py", 1, "p", "r", "e", True))
        report = ReviewReport.create(
            run.workflow_id,
            len(run.test_fix_iterations),
            [(run.patch or {})["patch_id"]],
            list(run.changed_files),
            findings,
            "done",
        )
        report.blocking_findings = list(findings)
        report.highest_severity = severity or "info"
        report.passed = not findings
        return report.to_dict()


class WorkflowCheckpointIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkpoints = RecordingCheckpointStore()
        self.confirmations = ConfirmationManager()
        self.patch = PatchStub(self.checkpoints)
        self.verifier = Verifier()
        self.reviewer = Reviewer()
        self.engine = self.make_engine()

    def make_engine(self, *, patch=None, verifier=None, reviewer=None):
        return WorkflowEngine(
            self.root,
            default_registry(),
            confirmation_manager=self.confirmations,
            patch_tools=patch or self.patch,
            test_tools=verifier or self.verifier,
            review_tools=reviewer or self.reviewer,
            checkpoint_store=self.checkpoints,
        )

    def reasons(self, history=False):
        source = self.checkpoints.history if history else self.checkpoints.active
        return [(item.reason, item.workflow_status) for item in source]

    def start_attached(self):
        return self.engine.start("feature", "Implement export", patch_id="patch-1")

    def test_workflow_start_checkpoint_is_created_at_created(self):
        self.engine.start("feature", "Implement export")
        self.assertEqual(self.reasons()[0], (CheckpointReason.WORKFLOW_STARTED, WorkflowStatus.CREATED))

    def test_waiting_patch_has_state_transition_checkpoint(self):
        run = self.engine.start("feature", "Implement export")
        self.assertEqual(run.status, WorkflowStatus.WAITING_PATCH)
        self.assertEqual(self.reasons()[-1], (CheckpointReason.STATE_TRANSITION, WorkflowStatus.WAITING_PATCH))

    def test_attach_patch_has_waiting_confirmation_checkpoint(self):
        run = self.start_attached()
        self.assertEqual(run.status, WorkflowStatus.WAITING_CONFIRMATION)
        self.assertEqual(self.reasons()[-1], (CheckpointReason.STATE_TRANSITION, WorkflowStatus.WAITING_CONFIRMATION))

    def test_before_apply_checkpoint_precedes_patch_side_effect(self):
        self.start_attached()
        self.engine.confirm()
        self.assertEqual(self.patch.applied, 1)
        self.assertIn((CheckpointReason.BEFORE_PATCH_APPLY, WorkflowStatus.EXECUTING), self.reasons(history=True))

    def test_after_apply_contains_application_evidence_and_changed_files(self):
        self.start_attached()
        self.engine.confirm()
        checkpoint = next(item for item in self.checkpoints.history if item.reason is CheckpointReason.AFTER_PATCH_APPLY)
        self.assertEqual(checkpoint.workflow_status, WorkflowStatus.VERIFYING)
        self.assertEqual(checkpoint.workflow_payload["artifacts"]["application_result"]["data"]["status"], "applied")
        self.assertEqual(checkpoint.workflow_payload["changed_files"], ["sample.py"])

    def test_verification_checkpoint_follows_result_and_iteration(self):
        self.start_attached()
        self.engine.confirm()
        checkpoint = next(item for item in self.checkpoints.history if item.reason is CheckpointReason.VERIFICATION_RECORDED)
        self.assertEqual(len(checkpoint.workflow_payload["verification_results"]), 1)
        self.assertEqual(len(checkpoint.workflow_payload["test_fix_iterations"]), 1)

    def test_review_checkpoint_follows_stored_review(self):
        self.start_attached()
        self.engine.confirm()
        checkpoint = next(item for item in self.checkpoints.history if item.reason is CheckpointReason.REVIEW_RECORDED)
        self.assertEqual(len(checkpoint.workflow_payload["review_results"]), 1)
        self.assertEqual(checkpoint.workflow_status, WorkflowStatus.REVIEWING)

    def test_completed_workflow_checkpoints_are_archived(self):
        run = self.start_attached()
        completed = self.engine.confirm()
        self.assertEqual(completed.status, WorkflowStatus.COMPLETED)
        self.assertFalse(self.checkpoints.active)
        self.assertEqual(self.reasons(history=True)[-1], (CheckpointReason.STATE_TRANSITION, WorkflowStatus.COMPLETED))
        self.assertEqual(self.checkpoints.archive_calls, [run.workflow_id])

    def test_cancelled_workflow_checkpoints_are_archived(self):
        run = self.start_attached()
        cancelled = self.engine.cancel()
        self.assertEqual(cancelled.status, WorkflowStatus.CANCELLED)
        self.assertFalse(self.checkpoints.active)
        self.assertEqual(self.reasons(history=True)[-1], (CheckpointReason.STATE_TRANSITION, WorkflowStatus.CANCELLED))
        self.assertEqual(self.checkpoints.archive_calls, [run.workflow_id])

    def test_failed_workflow_gets_terminal_checkpoint(self):
        broken = Verifier((False, False, False))
        engine = self.make_engine(verifier=broken)
        engine.start("bugfix", "Fix parser", patch_id="patch-1")
        engine.confirm()
        self.patch.state = "pending"
        engine.attach_patch("patch-2"); engine.confirm()
        self.patch.state = "pending"
        engine.attach_patch("patch-3")
        with self.assertRaises(WorkflowError):
            engine.confirm()
        self.assertEqual(self.reasons(history=True)[-1], (CheckpointReason.STATE_TRANSITION, WorkflowStatus.FAILED))

    def test_equivalent_checkpoint_is_deduplicated(self):
        run = self.engine.start("feature", "Implement export")
        count = len(self.checkpoints.active)
        first = self.engine._checkpoint(run, CheckpointReason.STATE_TRANSITION)
        second = self.engine._checkpoint(run, CheckpointReason.STATE_TRANSITION)
        self.assertIs(first, second)
        self.assertEqual(len(self.checkpoints.active), count)

    def test_different_reason_is_not_deduplicated(self):
        run = self.engine.start("feature", "Implement export")
        count = len(self.checkpoints.active)
        self.engine._checkpoint(run, CheckpointReason.MANUAL)
        self.assertEqual(len(self.checkpoints.active), count + 1)

    def test_resume_executing_does_not_apply_patch_twice(self):
        run = self.start_attached()
        self.confirmations.resolve(ConfirmationDecision.CONFIRM)
        run.step("confirmation").start(); run.step("confirmation").complete({"confirmed": True})
        run.transition(WorkflowStatus.EXECUTING)
        run.step("apply").start()
        self.patch.state = "applied"
        self.engine._save(run)
        self.engine.resume()
        self.assertEqual(self.patch.applied, 0)

    def test_resume_verifying_does_not_repeat_recorded_verification(self):
        run = self.start_attached()
        self.confirmations.resolve(ConfirmationDecision.CONFIRM)
        run.step("confirmation").start(); run.step("confirmation").complete({})
        run.transition(WorkflowStatus.EXECUTING)
        application = {"ok": True, "data": {"status": "applied", "target_path": "sample.py"}}
        run.step("apply").start(); run.step("apply").complete(application)
        run.artifacts["application_result"] = application
        run.changed_files = ["sample.py"]
        run.transition(WorkflowStatus.VERIFYING)
        verification = {"ok": True, "runs": 1, "error": None}
        run.step("verify").start(); run.step("verify").complete(verification)
        run.verification_results.append(verification)
        self.engine._record_iteration(run, verification)
        self.engine.resume()
        self.assertEqual(self.verifier.runs, 0)

    def test_resume_reviewing_does_not_repeat_stored_review(self):
        run = self.start_attached()
        self.confirmations.resolve(ConfirmationDecision.CONFIRM)
        run.step("confirmation").start(); run.step("confirmation").complete({})
        run.transition(WorkflowStatus.EXECUTING)
        application = {"ok": True, "data": {"status": "applied", "target_path": "sample.py"}}
        run.step("apply").start(); run.step("apply").complete(application)
        run.artifacts["application_result"] = application; run.changed_files = ["sample.py"]
        run.transition(WorkflowStatus.VERIFYING)
        verification = {"ok": True, "error": None}
        run.step("verify").start(); run.step("verify").complete(verification)
        run.verification_results.append(verification); self.engine._record_iteration(run, verification)
        run.transition(WorkflowStatus.REVIEWING)
        saved = self.reviewer.run_once(run); run.review_results.append(saved); self.engine._save(run)
        previous = self.reviewer.runs
        self.engine.resume()
        self.assertEqual(self.reviewer.runs, previous)

    def test_checkpoint_creation_failure_stops_before_apply(self):
        self.start_attached()
        self.checkpoints.fail_next_create = True
        with self.assertRaises(RuntimeError):
            self.engine.confirm()
        self.assertEqual(self.patch.applied, 0)

    def test_checkpoint_archive_failure_is_reported(self):
        self.start_attached()
        self.checkpoints.fail_archive = True
        with self.assertRaises(WorkflowStorageError):
            self.engine.confirm()
        self.assertTrue(self.checkpoints.active)

    def test_confirmation_is_still_required(self):
        self.start_attached()
        self.assertEqual(self.patch.applied, 0)
        self.assertTrue(self.confirmations.has_pending)

    def test_verification_fix_limit_is_unchanged(self):
        run = default_registry().get("bugfix").create_run("Fix parser")
        self.assertEqual(run.max_fix_attempts, 3)

    def test_blocking_review_returns_to_waiting_patch(self):
        reviewer = Reviewer(("high",))
        engine = self.make_engine(reviewer=reviewer)
        engine.start("bugfix", "Fix parser", patch_id="patch-1")
        run = engine.confirm()
        self.assertEqual(run.status, WorkflowStatus.WAITING_PATCH)
        self.assertEqual(run.patch_request_reason, "review_findings")


if __name__ == "__main__":
    unittest.main()
