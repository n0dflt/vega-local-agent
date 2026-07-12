"""Persistent, confirmation-gated execution engine for coding workflows."""
from __future__ import annotations
import json,os,subprocess
from pathlib import Path
from typing import Any,Callable
from core.confirmation_manager import ConfirmationManager
from core.intent_router import ConfirmationDecision
from planner import TaskPlanner
from workflows.base_workflow import WorkflowServices
from workflows.checkpoint_models import CheckpointReason, WorkflowCheckpoint, payload_sha256
from workflows.checkpoint_store import CheckpointStorageError, CheckpointStore
from workflows.integrations import PatchToolsAdapter,ReviewToolsAdapter,TestToolsAdapter
from workflows.models import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    StepStatus,
    WorkflowError,
    WorkflowRun,
    WorkflowStatus,
    validate_workflow_id,
)
from workflows.project_context import ProjectContextAdapter,TaskSystemAdapter
from workflows.registry import WorkflowRegistry

class WorkflowStorageError(WorkflowError): pass
class ActiveWorkflowError(WorkflowError): pass

class WorkflowEngine:
    def __init__(
        self,
        project_root: Path | str,
        registry: WorkflowRegistry,
        *,
        confirmation_manager=None,
        planner=None,
        project_context=None,
        patch_tools=None,
        test_tools=None,
        review_provider=None,
        review_tools=None,
        task_adapter=None,
        checkpoint_store: CheckpointStore | None = None,
    ) -> None:
        if not isinstance(registry, WorkflowRegistry):
            raise TypeError("registry must be a WorkflowRegistry instance.")
        self.project_root = Path(project_root).resolve()
        self.registry = registry
        self.checkpoint_store = checkpoint_store if checkpoint_store is not None else CheckpointStore(self.project_root)
        self.confirmation_manager=confirmation_manager or ConfirmationManager()
        self.services = WorkflowServices(
            self.project_root,
            planner or TaskPlanner(),
            project_context or ProjectContextAdapter(self.project_root),
            patch_tools or PatchToolsAdapter(),
            test_tools or TestToolsAdapter(self.project_root),
            review_tools or ReviewToolsAdapter(self.project_root,review_provider),
            task_adapter or TaskSystemAdapter(self.project_root),
        )
        self.active_dir = self.project_root / "data" / "workflows" / "active"
        self.history_dir = self.project_root / "data" / "workflows" / "history"
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
    def list_workflows(self):
        return self.registry.names()

    def start(
        self,
        workflow_type: str,
        task: str,
        *,
        patch_id: str | None = None,
    ) -> WorkflowRun:
        if self._active_files():
            raise ActiveWorkflowError("Only one active workflow is allowed.")
        workflow = self.registry.get(workflow_type)
        run = workflow.create_run(task)
        self._save(run)
        try:
            self._checkpoint(run, CheckpointReason.WORKFLOW_STARTED)
            run = self._advance_readonly(run)
            if patch_id:
                run = self.attach_patch(patch_id)
            return run
        except Exception as exc:
            self._fail(run, exc)
            raise
    def attach_patch(self, patch_id: str) -> WorkflowRun:
        run=self._require_active()
        if run.status is not WorkflowStatus.WAITING_PATCH:
            raise ActiveWorkflowError("The active workflow is not waiting for a patch.")
        workflow=self.registry.get(run.workflow_type)
        try:
            run.artifacts["requested_patch_id"]=patch_id
            run.patch=self._execute_step(run,"patch",lambda:workflow.prepare_patch(run,self.services))
            run.transition(WorkflowStatus.WAITING_CONFIRMATION)
            run.required_confirmations=["patch_application"]
            self._restore_confirmation(run)
            self._save(run)
            self._checkpoint(run, CheckpointReason.STATE_TRANSITION)
            return run
        except CheckpointStorageError:
            raise
        except Exception:
            run.artifacts.pop("requested_patch_id",None)
            run.patch=None
            step=run.step("patch")
            if step.status is StepStatus.FAILED:
                step.status=StepStatus.PENDING
                step.error=""
                step.started_at=None
                step.completed_at=None
            self._save(run)
            raise
    def link_task(self, task_id: str) -> WorkflowRun:
        run=self._require_active()
        if run.status not in {WorkflowStatus.WAITING_PATCH,WorkflowStatus.WAITING_CONFIRMATION}:
            raise ActiveWorkflowError("Task linking is allowed only before patch execution.")
        if self.services.task_adapter is None:
            raise WorkflowError("Task system is unavailable.")
        linked=self.services.task_adapter.link_plan(task_id,run.plan)
        run.linked_task_id=task_id
        run.artifacts["linked_task"]={"task_id":task_id,"plan_updated":True,"task":linked}
        self._save(run)
        return run
    def status(self)->WorkflowRun|None:
        files=self._active_files()
        if not files:
            return None
        if len(files) > 1:
            raise WorkflowStorageError(
                "Multiple active workflow files were found."
            )
        return self._load(files[0])
    def resume(self)->WorkflowRun:
        run=self._require_active()
        if run.status in TERMINAL_STATUSES:
            raise ActiveWorkflowError(
                f"Cannot resume a {run.status.value} workflow."
            )
        try:
            if run.status in {
                WorkflowStatus.CREATED,
                WorkflowStatus.ANALYZING,
                WorkflowStatus.PLANNING,
            }:
                if run.status is WorkflowStatus.CREATED:
                    self._checkpoint(run, CheckpointReason.WORKFLOW_STARTED)
                return self._advance_readonly(run)
            if run.status is WorkflowStatus.WAITING_PATCH:
                self._checkpoint(run, CheckpointReason.STATE_TRANSITION)
                return run
            if run.status is WorkflowStatus.WAITING_CONFIRMATION:
                self._restore_confirmation(run)
                self._checkpoint(run, CheckpointReason.STATE_TRANSITION)
                return run
            if run.status is WorkflowStatus.EXECUTING:
                return self._recover_executing(run)
            if run.status is WorkflowStatus.VERIFYING:
                return self._recover_verifying(run)
            if run.status is WorkflowStatus.REVIEWING:
                return self._recover_reviewing(run)
            raise ActiveWorkflowError(f"Unsupported recovery state: {run.status.value}.")
        except Exception as exc:
            self._fail(run, exc, manual=True)
            raise
    def confirm(self)->WorkflowRun:
        run=self._require_active()
        if run.status is not WorkflowStatus.WAITING_CONFIRMATION:
            raise ActiveWorkflowError(
                "The active workflow is not waiting for confirmation."
            )
        self._restore_confirmation(run)
        pending = self.confirmation_manager.pending
        if pending is None or pending.action_id != run.workflow_id:
            raise ActiveWorkflowError(
                "Another action is waiting for confirmation."
            )
        self.confirmation_manager.resolve(ConfirmationDecision.CONFIRM)
        workflow=self.registry.get(run.workflow_type)
        try:
            self._complete_step(run,"confirmation",{"confirmed":True})
            run.transition(WorkflowStatus.EXECUTING)
            self._save(run)
            self._checkpoint(run, CheckpointReason.BEFORE_PATCH_APPLY)
            application=self._execute_step(run,"apply",lambda:workflow.apply_patch(run,self.services))
            if application.get("ok") is not True:
                raise WorkflowError(
                    application.get("error") or "Patch application failed."
                )
            data = application.get("data") or {}
            run.artifacts["application_result"] = application
            if data.get("target_path") and data["target_path"] not in run.changed_files:
                run.changed_files.append(data["target_path"])
            if data.get("status") != "applied" or not run.changed_files:
                raise WorkflowError(
                    "Workflow cannot complete without an applied change artifact."
                )
            run.transition(WorkflowStatus.VERIFYING)
            self._save(run)
            self._checkpoint(run, CheckpointReason.AFTER_PATCH_APPLY)
            return self._recover_verifying(run)
        except Exception as exc:
            self._fail(run, exc, manual=True)
            raise
    def cancel(self)->WorkflowRun:
        run=self._require_active()
        if run.is_terminal:
            raise ActiveWorkflowError(
                f"Cannot cancel a {run.status.value} workflow."
            )
        self._cancel_own_confirmation(run)
        run.transition(WorkflowStatus.CANCELLED)
        run.report = self._report(run)
        self._save(run)
        self._checkpoint_terminal_and_archive(run)
        return run
    def history(self) -> list[WorkflowRun]:
        return [
            self._load(path)
            for path in sorted(self.history_dir.glob("*.json"), reverse=True)
        ]
    def _advance_readonly(self,run):
        workflow=self.registry.get(run.workflow_type)
        if run.status is WorkflowStatus.CREATED:
            run.transition(WorkflowStatus.ANALYZING)
            self._save(run)
        if run.status is WorkflowStatus.ANALYZING:
            workflow.validate_scope(run)
            context_id="context" if any(s.step_id=="context" for s in run.steps) else run.steps[0].step_id
            run.context=self._execute_step(run,context_id,lambda:workflow.collect_context(run,self.services))
            artifacts = workflow.analyze_artifacts(run)
            run.artifacts.update(artifacts)
            reserved={"plan","patch","confirmation","apply","verify","report",context_id}
            for step in run.steps:
                if step.step_id not in reserved and step.status is not StepStatus.COMPLETED:
                    reproduction_unavailable = (
                        step.step_id == "reproduction"
                        and (artifacts.get("reproduction_result") or {}).get(
                            "status"
                        )
                        == "not_available"
                    )
                    if reproduction_unavailable:
                        step.skip(artifacts["reproduction_result"])
                        self._save(run)
                    else:
                        self._execute_step(run,step.step_id,lambda sid=step.step_id:artifacts.get(sid,artifacts))
            run.transition(WorkflowStatus.PLANNING)
            self._save(run)
        if run.status is WorkflowStatus.PLANNING:
            plan_id="plan"
            run.plan=self._execute_step(run,plan_id,lambda:workflow.plan(run,self.services))
            run.transition(WorkflowStatus.WAITING_PATCH)
            self._save(run)
            self._checkpoint(run, CheckpointReason.STATE_TRANSITION)
        return run
    def _recover_executing(self,run):
        patch_id = (run.patch or {}).get("patch_id")
        state = self.services.patch_tools.inspect(patch_id)
        if state.get("status") != "applied":
            raise WorkflowError(
                "Patch application state is uncertain; manual intervention is required."
            )
        apply_step=run.step("apply")
        if apply_step.status is not StepStatus.COMPLETED:
            if apply_step.status is StepStatus.PENDING:
                apply_step.start()
            apply_step.complete({"ok":True,"data":state,"recovered":True})
        run.artifacts["application_result"] = apply_step.result
        if state.get("target_path") and state["target_path"] not in run.changed_files:
            run.changed_files.append(state["target_path"])
        run.transition(WorkflowStatus.VERIFYING)
        self._save(run)
        self._checkpoint(run, CheckpointReason.AFTER_PATCH_APPLY)
        return self._recover_verifying(run)
    def _recover_verifying(self,run):
        workflow=self.registry.get(run.workflow_type)
        verify_step=run.step("verify")
        if verify_step.status is not StepStatus.COMPLETED:
            verification = self._execute_step(
                run,
                "verify",
                lambda: workflow.verify(run, self.services),
            )
            run.verification_results.append(verification)
            self._save(run)
        else:
            verification=verify_step.result
            if len(run.verification_results) <= len(run.test_fix_iterations):
                run.verification_results.append(verification)
                self._save(run)
        if len(run.test_fix_iterations) < len(run.verification_results):
            self._record_iteration(run,verification)
        self._checkpoint(run, CheckpointReason.VERIFICATION_RECORDED)
        if verification.get("ok") is not True:
            return self._continue_after_failed_verification(run,verification)
        application_evidence = (
            run.artifacts.get("application_result")
            or run.step("apply").result
        )
        if not run.changed_files or not application_evidence:
            raise WorkflowError("Applied patch evidence is missing.")
        run.transition(WorkflowStatus.REVIEWING)
        self._save(run)
        return self._recover_reviewing(run)
    def _recover_reviewing(self,run):
        iteration=len(run.test_fix_iterations)
        existing=next((item for item in run.review_results if item.get("patch_iteration")==iteration),None)
        if existing is None:
            review=self.services.review_tools.run_once(run)
            from review.models import ReviewReport
            review=ReviewReport.from_dict(review).to_dict()
            run.review_results.append(review)
            self._save(run)
        else:
            review=existing
        self._checkpoint(run, CheckpointReason.REVIEW_RECORDED)
        blocking=review.get("blocking_findings") or []
        if review.get("reviewer_error"):
            raise WorkflowError(f"Reviewer infrastructure failed: {review['reviewer_error']}")
        if review.get("passed") is True and not blocking:
            self._execute_step(run,"report",lambda:{"status":"completed","changed_files":run.changed_files})
            run.transition(WorkflowStatus.COMPLETED)
            run.report=self._report(run)
            self._save(run)
            self._checkpoint_terminal_and_archive(run)
            return run
        if not blocking:
            raise WorkflowError("Review did not pass and supplied no blocking evidence.")
        if iteration >= run.max_fix_attempts:
            raise WorkflowError("Blocking review findings remain after the patch iteration limit.")
        run.artifacts.setdefault("application_results",[]).append(
            run.test_fix_iterations[-1]["application"]
        )
        run.artifacts.pop("application_result",None); run.artifacts.pop("requested_patch_id",None)
        run.patch=None; run.required_confirmations=[]; run.patch_request_reason="review_findings"
        for step_id in ("patch","confirmation","apply","verify"): self._reset_step(run.step(step_id))
        run.transition(WorkflowStatus.WAITING_PATCH); self._save(run)
        self._checkpoint(run, CheckpointReason.STATE_TRANSITION)
        return run
    def _continue_after_failed_verification(self,run,verification):
        if len(run.test_fix_iterations) >= run.max_fix_attempts:
            raise WorkflowError(
                "Workflow verification failed and the controlled fix "
                f"limit ({run.max_fix_attempts}) was reached: "
                f"{verification.get('error') or 'tests failed'}"
            )
        run.artifacts.setdefault("application_results",[]).append(
            run.test_fix_iterations[-1]["application"]
        )
        run.artifacts.pop("application_result",None)
        run.artifacts.pop("requested_patch_id",None)
        run.patch=None
        run.patch_request_reason="test_failure"
        run.required_confirmations=[]
        for step_id in ("patch","confirmation","apply","verify"):
            self._reset_step(run.step(step_id))
        run.transition(WorkflowStatus.WAITING_PATCH)
        self._save(run)
        self._checkpoint(run, CheckpointReason.STATE_TRANSITION)
        return run
    def _record_iteration(self,run,verification):
        patch=dict(run.patch or {})
        application=(
            run.artifacts.get("application_result")
            or run.step("apply").result
            or {}
        )
        run.test_fix_iterations.append({
            "attempt":len(run.test_fix_iterations)+1,
            "patch_id":patch.get("patch_id"),
            "target_path":patch.get("target_path"),
            "application":application,
            "verification":verification,
        })
        self._save(run)
    @staticmethod
    def _reset_step(step):
        step.status=StepStatus.PENDING
        step.result=None
        step.error=""
        step.started_at=None
        step.completed_at=None
    def _execute_step(
        self,
        run,
        step_id,
        action: Callable[[], Any],
    ):
        step=run.step(step_id)
        if step.status is StepStatus.COMPLETED:
            return step.result
        if step.status is StepStatus.PENDING:
            step.start()
            self._save(run)
        try:
            result = action()
            step.complete(result)
            self._save(run)
            return result
        except Exception as exc:
            step.fail(exc)
            self._save(run)
            raise
    def _complete_step(self,run,step_id,result):
        step=run.step(step_id)
        if step.status is StepStatus.PENDING:
            step.start()
        if step.status is not StepStatus.COMPLETED:
            step.complete(result)
        self._save(run)
    def _restore_confirmation(self,run):
        if self.confirmation_manager.has_pending:
            pending=self.confirmation_manager.pending
            if pending and pending.action_id == run.workflow_id:
                return
            raise ActiveWorkflowError("Another action is waiting for confirmation.")
        self.confirmation_manager.request(
            run.workflow_id,
            f"workflow:{run.workflow_type}",
            "Inspect the pending patch, then run /workflow confirm or cancel.",
            payload={
                "workflow_id": run.workflow_id,
                "patch_id": (run.patch or {}).get("patch_id"),
            },
        )
    def _cancel_own_confirmation(self,run):
        pending=self.confirmation_manager.pending
        if pending is not None and pending.action_id == run.workflow_id:
            self.confirmation_manager.resolve(ConfirmationDecision.CANCEL)
    def _require_active(self):
        run=self.status()
        if run is None:
            raise ActiveWorkflowError("No active workflow.")
        return run
    def _active_files(self):
        return sorted(self.active_dir.glob("*.json"))
    def _path(self, run):
        validate_workflow_id(run.workflow_id)
        return self.active_dir / f"{run.workflow_id}.json"
    def _save(self,run):
        path = self._path(run)
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(
                json.dumps(run.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except OSError as exc:
            raise WorkflowStorageError(
                f"Cannot save workflow state: {exc}"
            ) from exc
    def _load(self,path):
        try:
            run=WorkflowRun.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if path.stem != run.workflow_id:
                raise ValueError("Workflow ID does not match filename.")
            return run
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise WorkflowStorageError(
                f"Cannot load workflow state {path.name}: {exc}"
            ) from exc
    def _archive(self,run):
        source = self._path(run)
        target = self.history_dir / source.name
        try:
            os.replace(source, target)
        except OSError as exc:
            raise WorkflowStorageError(
                f"Cannot archive workflow state: {exc}"
            ) from exc
    def _checkpoint(self, run, reason):
        if not isinstance(run, WorkflowRun):
            raise TypeError("Checkpoint creation requires a WorkflowRun.")
        normalized_reason = CheckpointReason(reason)
        latest = self.checkpoint_store.latest(run.workflow_id, include_history=False)
        current_hash = payload_sha256(run.to_dict())
        if (
            latest is not None
            and latest.reason is normalized_reason
            and latest.workflow_status is run.status
            and latest.payload_sha256 == current_hash
        ):
            return latest
        return self.checkpoint_store.create(run, normalized_reason)
    def _checkpoint_terminal_and_archive(self, run):
        self._checkpoint(run, CheckpointReason.STATE_TRANSITION)
        # Archive immutable evidence first. If this fails, the terminal workflow
        # file remains active and available for manual diagnosis.
        self.checkpoint_store.archive_workflow(run.workflow_id)
        self._archive(run)
    def _fail(self,run,exc,manual=False):
        if (
            not run.is_terminal
            and WorkflowStatus.FAILED in ALLOWED_TRANSITIONS[run.status]
        ):
            run.transition(WorkflowStatus.FAILED)
        run.error = f"{type(exc).__name__}: {exc}"
        run.manual_intervention_required = manual
        run.report = self._report(run)
        self._cancel_own_confirmation(run)
        self._save(run)
        try:
            self._checkpoint_terminal_and_archive(run)
        except Exception as terminal_exc:
            raise WorkflowStorageError(
                "Workflow failure was persisted, but terminal checkpoint or "
                f"archive handling failed: {terminal_exc}"
            ) from exc
    def _report(self,run):
        patch_id=(run.patch or {}).get("patch_id")
        application=run.artifacts.get("application_result") or run.step("apply").result or {}
        applied=(application.get("data") or {}).get("status")=="applied"
        try:
            git = subprocess.run(
                ["git", "status", "--short"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            ).stdout.strip()
        except Exception as exc:
            git = f"unavailable: {exc}"
        return "\n".join(
            [
                f"Workflow: {run.workflow_type}",
                f"ID: {run.workflow_id}",
                f"Task: {run.task}",
                f"Status: {run.status.value}",
                f"Changed files: {', '.join(run.changed_files) or 'none'}",
                f"Patch ID: {patch_id or 'none'}",
                f"Patch applied: {applied}",
                f"Checks: {len(run.verification_results)}",
                f"Fix attempts: {len(run.test_fix_iterations)}/{run.max_fix_attempts}",
                f"Verification results: {run.verification_results}",
                f"Reviews: {len(run.review_results)}",
                f"Last review: {(run.review_results[-1].get('passed') if run.review_results else 'none')}",
                f"Highest review severity: {(run.review_results[-1].get('highest_severity') if run.review_results else 'none')}",
                f"Review findings: {(len(run.review_results[-1].get('findings') or []) if run.review_results else 0)}",
                f"Blocking findings: {(len(run.review_results[-1].get('blocking_findings') or []) if run.review_results else 0)}",
                f"Reviewed patch IDs: {([x.get('patch_id') for x in run.test_fix_iterations] if run.review_results else [])}",
                f"Error: {run.error or 'none'}",
                "Manual intervention required: "
                f"{run.manual_intervention_required}",
                f"Git status:\n{git or 'clean'}",
            ]
        )
