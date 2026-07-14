"""Deterministic v2.13 coding workflow engine with separately bound actions."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from permissions.evaluator import PermissionEvaluator
from permissions.policy import load_permission_policy
from core.execution_trace import (
    ExecutionTrace,
    TraceStatus,
    WorkflowTraceDecision,
    append_trace,
)
from tools.git_tools import git_diff, git_diff_cached, git_log, git_status
from workflows.controlled_models import (
    ConfirmationBinding,
    ControlledWorkflowState,
    ControlledWorkflowValidationError,
    InvestigationEvidence,
    MAX_ITERATIONS,
    PatchEvidence,
    ReviewEvidence,
    ReviewFindingEvidence,
    TestOutcome,
)
from workflows.controlled_store import (
    ControlledStoreConflict,
    ControlledStoreError,
    ControlledWorkflowStore,
)
from workflows.integrations import PatchToolsAdapter, TestToolsAdapter
from workflows.checkpoint_models import CheckpointReason, payload_sha256
from workflows.checkpoint_store import CheckpointStore, CheckpointStorageError
from workflows.models import WorkflowError, WorkflowStatus, validate_workflow_id
from workflows.registry import WorkflowRegistry


MAX_INSPECTION_FILES = 200
MAX_INSPECTION_BYTES = 64 * 1024
MAX_FALLBACK_REVISION_FILES = 256
MAX_FALLBACK_REVISION_BYTES = 4 * 1024 * 1024

_TYPE_ALIASES = {"bugfix": "bug-fix", "bug-fix": "bug-fix"}
_BLOCKED_PARTS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "data", "logs"
}
_SENSITIVE_MARKERS = (
    ".env", "credential", "secret", "token", "password", "private", ".pem", ".key", ".p12", ".pfx"
)


class ControlledWorkflowError(WorkflowError):
    """A fixed safe workflow error suitable for CLI output."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WorkflowStorageError(ControlledWorkflowError):
    pass


class ActiveWorkflowError(ControlledWorkflowError):
    pass


def _canonical_patch_identity(metadata: dict[str, object]) -> str:
    visible = {
        "patch_id": metadata.get("patch_id"),
        "status": metadata.get("status"),
        "target_path": metadata.get("target_path"),
        "original_sha256": metadata.get("original_sha256"),
        "proposed_sha256": metadata.get("proposed_sha256"),
    }
    encoded = json.dumps(visible, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _synthetic_sha(patch_id: str, label: str) -> str:
    return hashlib.sha256(f"{patch_id}:{label}".encode("utf-8")).hexdigest()


class WorkflowEngine:
    """One controlled path over existing Patch, Test, policy and state layers."""

    def __init__(
        self,
        project_root: Path | str,
        registry: WorkflowRegistry,
        *,
        confirmation_manager: object | None = None,
        planner: object | None = None,
        project_context: object | None = None,
        patch_tools: object | None = None,
        test_tools: object | None = None,
        review_provider: object | None = None,
        review_tools: object | None = None,
        task_adapter: object | None = None,
        checkpoint_store: object | None = None,
        state_store: ControlledWorkflowStore | None = None,
        lock_timeout_ms: int = 1_000,
    ) -> None:
        del confirmation_manager, planner, project_context, review_provider, review_tools, task_adapter
        if not isinstance(registry, WorkflowRegistry):
            raise TypeError("registry must be a WorkflowRegistry instance")
        self.project_root = Path(project_root).resolve()
        self.registry = registry
        self.patch_tools = patch_tools or PatchToolsAdapter()
        self.test_tools = test_tools or TestToolsAdapter(self.project_root)
        self.store = state_store or ControlledWorkflowStore(
            self.project_root, lock_timeout_ms=lock_timeout_ms
        )
        self.checkpoint_store = checkpoint_store or CheckpointStore(self.project_root)
        self.active_dir = self.store.active_dir
        self.history_dir = self.store.history_dir

    def list_workflows(self) -> tuple[str, ...]:
        return tuple(sorted({"bug-fix", "bugfix", "feature", "refactor", "review", "test"}))

    def start(
        self,
        workflow_type: str,
        task: str,
        *,
        patch_id: str | None = None,
        test_group: str = "workflow",
    ) -> ControlledWorkflowState:
        normalized_type = self._workflow_type(workflow_type)
        if normalized_type == "review" and task not in {"staged", "unstaged"}:
            raise ControlledWorkflowError("review_scope_invalid")
        resolved_test: tuple[str, str] | None = None
        if normalized_type == "test":
            resolved_test = self._resolve_test_group(task)
        try:
            with self.store.mutation():
                if self.store.load_active() is not None:
                    raise ActiveWorkflowError("active_workflow_exists")
                revision = self._workspace_revision()
                state = ControlledWorkflowState.create(normalized_type, task, revision)
                self.store.save_active(state)
                self._checkpoint(state, CheckpointReason.WORKFLOW_STARTED)
                if normalized_type == "review":
                    state = self._complete_review(state, task)
                    self._archive_state(state)
                elif normalized_type == "test":
                    assert resolved_test is not None
                    group, command = resolved_test
                    target_revision = state.revision + 1
                    binding = ConfirmationBinding.create(
                        workflow_id=state.workflow_id,
                        stage=WorkflowStatus.AWAITING_TEST_CONFIRMATION,
                        action="test_execution",
                        patch_identity="",
                        workspace_revision=revision,
                        test_group=group,
                        command_id=command,
                        state_revision=target_revision,
                    )
                    state = state.evolve(
                        status=WorkflowStatus.AWAITING_TEST_CONFIRMATION,
                        next_actions=("approve_tests", "cancel", "show"),
                        confirmation=binding,
                        test_group=group,
                        test_command_id=command,
                    )
                    self.store.save_active(state)
                    self._checkpoint(state, CheckpointReason.STATE_TRANSITION)
                else:
                    state = state.evolve(
                        status=WorkflowStatus.INVESTIGATING,
                        next_actions=("resume", "cancel", "show"),
                    )
                    self.store.save_active(state)
                    self._checkpoint(state, CheckpointReason.STATE_TRANSITION)
                    evidence = self._investigate(task)
                    state = state.evolve(
                        status=WorkflowStatus.WAITING_PATCH,
                        next_actions=("attach_patch", "cancel", "show"),
                        investigation=evidence,
                        workspace_revision=self._workspace_revision(),
                    )
                    self.store.save_active(state)
                    self._checkpoint(state, CheckpointReason.STATE_TRANSITION)
        except ControlledWorkflowValidationError as exc:
            raise ControlledWorkflowError("state_invalid") from exc
        except ControlledStoreError as exc:
            raise WorkflowStorageError(exc.code) from None
        if patch_id is not None:
            return self.attach_patch(
                patch_id,
                workflow_id=state.workflow_id,
                test_group=test_group,
            )
        return state

    def attach_patch(
        self,
        patch_id: str,
        *,
        workflow_id: str | None = None,
        test_group: str = "workflow",
    ) -> ControlledWorkflowState:
        try:
            with self.store.mutation():
                state = self._active(workflow_id)
                if state.status is not WorkflowStatus.WAITING_PATCH:
                    raise ActiveWorkflowError("invalid_stage")
                if state.iteration_count >= MAX_ITERATIONS:
                    raise ControlledWorkflowError("iteration_limit_reached")
                if any(item.patch_id == patch_id for item in state.patches):
                    raise ControlledWorkflowError("confirmation_replayed")
                metadata = self._prepare_patch(patch_id)
                if metadata["status"] != "pending":
                    raise ControlledWorkflowError("managed_patch_invalid")
                group, command = self._resolve_test_group(test_group)
                patch = PatchEvidence(
                    patch_id=patch_id,
                    identity_sha256=_canonical_patch_identity(metadata),
                    target_path=metadata["target_path"],
                    original_sha256=metadata["original_sha256"],
                    proposed_sha256=metadata["proposed_sha256"],
                    status="pending",
                )
                workspace = self._workspace_revision()
                target_revision = state.revision + 1
                binding = ConfirmationBinding.create(
                    workflow_id=state.workflow_id,
                    stage=WorkflowStatus.AWAITING_PATCH_CONFIRMATION,
                    action="patch_application",
                    patch_identity=patch.identity_sha256,
                    workspace_revision=workspace,
                    test_group=group,
                    command_id=command,
                    state_revision=target_revision,
                )
                state = state.evolve(
                    status=WorkflowStatus.AWAITING_PATCH_CONFIRMATION,
                    next_actions=("approve_patch", "cancel", "show"),
                    patches=(*state.patches, patch),
                    confirmation=binding,
                    test_group=group,
                    test_command_id=command,
                    workspace_revision=workspace,
                    workspace_drift=False,
                    error_codes=(),
                )
                self.store.save_active(state)
                self._checkpoint(state, CheckpointReason.STATE_TRANSITION)
                return state
        except ControlledStoreError as exc:
            raise WorkflowStorageError(exc.code) from None
        except ControlledWorkflowValidationError as exc:
            raise ControlledWorkflowError("managed_patch_invalid") from exc

    def approve_patch(self, workflow_id: str) -> ControlledWorkflowState:
        validate_workflow_id(workflow_id)
        try:
            with self.store.mutation():
                state = self._active(workflow_id)
                binding = self._binding(
                    state,
                    WorkflowStatus.AWAITING_PATCH_CONFIRMATION,
                    "patch_application",
                )
                patch = state.patches[-1]
                if binding.patch_identity != patch.identity_sha256:
                    raise ControlledWorkflowError("confirmation_binding_invalid")
                current_workspace = self._workspace_revision()
                if current_workspace != binding.workspace_revision:
                    drifted = state.evolve(
                        status=WorkflowStatus.WAITING_PATCH,
                        next_actions=("attach_patch", "cancel", "show"),
                        confirmation=None,
                        workspace_drift=True,
                        error_codes=("workspace_drift",),
                    )
                    self.store.save_active(drifted)
                    self._checkpoint(drifted, CheckpointReason.STATE_TRANSITION)
                    raise ControlledWorkflowError("workspace_drift")
                metadata = self._prepare_patch(patch.patch_id)
                if not hmac_compare(_canonical_patch_identity(metadata), patch.identity_sha256):
                    invalidated = state.evolve(
                        status=WorkflowStatus.WAITING_PATCH,
                        next_actions=("attach_patch", "cancel", "show"),
                        confirmation=None,
                        error_codes=("patch_identity_changed",),
                    )
                    self.store.save_active(invalidated)
                    self._checkpoint(invalidated, CheckpointReason.STATE_TRANSITION)
                    raise ControlledWorkflowError("patch_identity_changed")
                self._require_confirmation_policy("apply_patch")
                self._checkpoint(state, CheckpointReason.BEFORE_PATCH_APPLY)
                try:
                    result = self.patch_tools.apply(patch.patch_id, confirmed=True)
                except Exception:
                    raise ControlledWorkflowError("patch_apply_failed") from None
                data = result.get("data") if isinstance(result, dict) else None
                if (
                    not isinstance(result, dict)
                    or result.get("ok") is not True
                    or not isinstance(data, dict)
                    or data.get("status") != "applied"
                ):
                    raise ControlledWorkflowError("patch_apply_failed")
                applied = PatchEvidence(
                    patch.patch_id,
                    patch.identity_sha256,
                    patch.target_path,
                    patch.original_sha256,
                    patch.proposed_sha256,
                    "applied",
                )
                workspace = self._workspace_revision()
                target_revision = state.revision + 1
                test_binding = ConfirmationBinding.create(
                    workflow_id=state.workflow_id,
                    stage=WorkflowStatus.AWAITING_TEST_CONFIRMATION,
                    action="test_execution",
                    patch_identity=applied.identity_sha256,
                    workspace_revision=workspace,
                    test_group=state.test_group,
                    command_id=state.test_command_id,
                    state_revision=target_revision,
                )
                state = state.evolve(
                    status=WorkflowStatus.AWAITING_TEST_CONFIRMATION,
                    next_actions=("approve_tests", "rollback", "cancel", "show"),
                    patches=(*state.patches[:-1], applied),
                    confirmation=test_binding,
                    iteration_count=state.iteration_count + 1,
                    rollback_available=True,
                    workspace_revision=workspace,
                    workspace_drift=False,
                    error_codes=(),
                )
                self.store.save_active(state)
                self._checkpoint(state, CheckpointReason.AFTER_PATCH_APPLY)
                return state
        except ControlledStoreError as exc:
            raise WorkflowStorageError(exc.code) from None

    def approve_tests(self, workflow_id: str) -> ControlledWorkflowState:
        validate_workflow_id(workflow_id)
        try:
            with self.store.mutation():
                state = self._active(workflow_id)
                binding = self._binding(
                    state,
                    WorkflowStatus.AWAITING_TEST_CONFIRMATION,
                    "test_execution",
                )
                if (
                    binding.test_group != state.test_group
                    or binding.command_id != state.test_command_id
                ):
                    raise ControlledWorkflowError("confirmation_binding_invalid")
                current_workspace = self._workspace_revision()
                if current_workspace != binding.workspace_revision:
                    state = state.evolve(
                        confirmation=None,
                        workspace_drift=True,
                        error_codes=("workspace_drift",),
                        next_actions=("rollback", "cancel", "show")
                        if state.rollback_available
                        else ("cancel", "show"),
                    )
                    self.store.save_active(state)
                    raise ControlledWorkflowError("workspace_drift")
                self._require_confirmation_policy("test_run")
                running = state.evolve(
                    status=WorkflowStatus.TESTS_RUNNING,
                    next_actions=("show",),
                    confirmation=None,
                )
                self.store.save_active(running)
                self._checkpoint(running, CheckpointReason.STATE_TRANSITION)
                outcome = self._run_test_group(state.test_group, state.test_command_id)
                after_workspace = self._workspace_revision()
                drift = after_workspace != current_workspace
                results = (*state.test_results, outcome)
                if drift:
                    terminal = running.evolve(
                        status=WorkflowStatus.FAILED,
                        next_actions=("rollback", "show")
                        if state.rollback_available
                        else ("show",),
                        test_results=results,
                        workspace_drift=True,
                        error_codes=("workspace_drift",),
                        workspace_revision=after_workspace,
                    )
                    self._checkpoint(terminal, CheckpointReason.VERIFICATION_RECORDED)
                    self._archive_state(terminal)
                    return terminal
                if outcome.passed:
                    terminal = running.evolve(
                        status=WorkflowStatus.COMPLETED,
                        next_actions=("rollback", "show")
                        if state.rollback_available
                        else ("show",),
                        test_results=results,
                        workspace_revision=after_workspace,
                        error_codes=(),
                    )
                    self._checkpoint(terminal, CheckpointReason.VERIFICATION_RECORDED)
                    self._archive_state(terminal)
                    return terminal
                if state.workflow_type != "test" and state.iteration_count < MAX_ITERATIONS:
                    waiting = running.evolve(
                        status=WorkflowStatus.WAITING_PATCH,
                        next_actions=("attach_patch", "rollback", "cancel", "show"),
                        test_results=results,
                        workspace_revision=after_workspace,
                        error_codes=("test_execution_failed",),
                    )
                    self.store.save_active(waiting)
                    self._checkpoint(waiting, CheckpointReason.VERIFICATION_RECORDED)
                    return waiting
                code = (
                    "iteration_limit_reached"
                    if state.iteration_count >= MAX_ITERATIONS
                    else "test_execution_failed"
                )
                terminal = running.evolve(
                    status=WorkflowStatus.FAILED,
                    next_actions=("rollback", "show")
                    if state.rollback_available
                    else ("show",),
                    test_results=results,
                    workspace_revision=after_workspace,
                    error_codes=(code,),
                )
                self._checkpoint(terminal, CheckpointReason.VERIFICATION_RECORDED)
                self._archive_state(terminal)
                return terminal
        except ControlledStoreError as exc:
            raise WorkflowStorageError(exc.code) from None

    def status(self, workflow_id: str | None = None) -> ControlledWorkflowState | None:
        try:
            if workflow_id is None:
                return self.store.load_active()
            validate_workflow_id(workflow_id)
            active = self.store.load_active(workflow_id)
            if active is not None:
                return active
            history = self.store.load_history(workflow_id)
            return history[0] if len(history) == 1 else None
        except ControlledStoreError as exc:
            raise WorkflowStorageError(exc.code) from None

    def show(self, workflow_id: str) -> ControlledWorkflowState:
        validate_workflow_id(workflow_id)
        try:
            return self.store.load_any(workflow_id)
        except ControlledStoreError as exc:
            raise WorkflowStorageError(exc.code) from None

    def history(self) -> list[ControlledWorkflowState]:
        try:
            return self.store.load_history()
        except ControlledStoreError as exc:
            raise WorkflowStorageError(exc.code) from None

    def resume(self, workflow_id: str | None = None) -> ControlledWorkflowState:
        try:
            with self.store.mutation():
                state = self._active(workflow_id)
                if state.is_terminal:
                    self._archive_state(state)
                    return state
                if state.migrated_from_schema:
                    self.store.save_active(state)
                    self._checkpoint(state, CheckpointReason.STATE_TRANSITION)
                if state.status in {WorkflowStatus.PLANNED, WorkflowStatus.INVESTIGATING}:
                    failed = state.evolve(
                        status=WorkflowStatus.FAILED,
                        next_actions=("show",),
                        confirmation=None,
                        error_codes=("state_incompatible",),
                    )
                    self._archive_state(failed)
                    return failed
                if state.status is WorkflowStatus.TESTS_RUNNING:
                    failed = state.evolve(
                        status=WorkflowStatus.FAILED,
                        next_actions=("rollback", "show")
                        if state.rollback_available
                        else ("show",),
                        confirmation=None,
                        error_codes=("test_execution_failed",),
                    )
                    self._archive_state(failed)
                    return failed
                if state.status is WorkflowStatus.AWAITING_PATCH_CONFIRMATION:
                    patch = state.patches[-1]
                    metadata = self._prepare_patch(patch.patch_id)
                    if metadata.get("status") == "applied":
                        applied = PatchEvidence(
                            patch.patch_id,
                            patch.identity_sha256,
                            patch.target_path,
                            patch.original_sha256,
                            patch.proposed_sha256,
                            "applied",
                        )
                        workspace = self._workspace_revision()
                        target_revision = state.revision + 1
                        binding = ConfirmationBinding.create(
                            workflow_id=state.workflow_id,
                            stage=WorkflowStatus.AWAITING_TEST_CONFIRMATION,
                            action="test_execution",
                            patch_identity=applied.identity_sha256,
                            workspace_revision=workspace,
                            test_group=state.test_group,
                            command_id=state.test_command_id,
                            state_revision=target_revision,
                        )
                        state = state.evolve(
                            status=WorkflowStatus.AWAITING_TEST_CONFIRMATION,
                            next_actions=("approve_tests", "rollback", "cancel", "show"),
                            patches=(*state.patches[:-1], applied),
                            confirmation=binding,
                            iteration_count=state.iteration_count + 1,
                            rollback_available=True,
                            workspace_revision=workspace,
                        )
                        self.store.save_active(state)
                        self._checkpoint(state, CheckpointReason.AFTER_PATCH_APPLY)
                return state
        except ControlledStoreError as exc:
            raise WorkflowStorageError(exc.code) from None

    def cancel(self, workflow_id: str | None = None) -> ControlledWorkflowState:
        try:
            with self.store.mutation():
                state = self._active(workflow_id)
                if state.status is WorkflowStatus.TESTS_RUNNING or state.is_terminal:
                    raise ActiveWorkflowError("invalid_stage")
                terminal = state.evolve(
                    status=WorkflowStatus.CANCELLED,
                    next_actions=("rollback", "show")
                    if state.rollback_available
                    else ("show",),
                    confirmation=None,
                )
                self._archive_state(terminal)
                return terminal
        except ControlledStoreError as exc:
            raise WorkflowStorageError(exc.code) from None

    def rollback(self, workflow_id: str) -> ControlledWorkflowState:
        """The exact command is the explicit, single-use rollback confirmation."""
        validate_workflow_id(workflow_id)
        try:
            with self.store.mutation():
                active = self.store.load_active(workflow_id)
                any_active = self.store.load_active()
                if any_active is not None and any_active.workflow_id != workflow_id:
                    raise ControlledWorkflowError("active_workflow_exists")
                state = active if active is not None else self.store.load_any(workflow_id)
                if not state.rollback_available or not state.patches:
                    raise ControlledWorkflowError("rollback_refused")
                patch = state.patches[-1]
                if patch.status != "applied":
                    raise ControlledWorkflowError("rollback_refused")
                self._require_confirmation_policy("rollback_patch")
                workspace = self._workspace_revision()
                if workspace != state.workspace_revision:
                    raise ControlledWorkflowError("rollback_refused")
                binding = ConfirmationBinding.create(
                    workflow_id=state.workflow_id,
                    stage=state.status,
                    action="patch_rollback",
                    patch_identity=patch.identity_sha256,
                    workspace_revision=workspace,
                    state_revision=state.revision + 1,
                )
                requested = state.evolve(confirmation=binding)
                if active is not None:
                    self.store.save_active(requested)
                else:
                    self.store.save_history(requested)
                if requested.confirmation is None or requested.confirmation.action != "patch_rollback":
                    raise ControlledWorkflowError("confirmation_binding_invalid")
                try:
                    self.patch_tools.rollback(patch.patch_id, confirmed=True)
                except Exception:
                    raise ControlledWorkflowError("rollback_refused") from None
                rolled_patch = PatchEvidence(
                    patch.patch_id,
                    patch.identity_sha256,
                    patch.target_path,
                    patch.original_sha256,
                    patch.proposed_sha256,
                    "rolled_back",
                )
                terminal = requested.evolve(
                    status=WorkflowStatus.ROLLED_BACK,
                    next_actions=("show",),
                    patches=(*requested.patches[:-1], rolled_patch),
                    confirmation=None,
                    rollback_available=False,
                    workspace_revision=self._workspace_revision(),
                    error_codes=(),
                )
                if active is not None:
                    self._archive_state(terminal)
                else:
                    self.store.save_history(terminal)
                return terminal
        except ControlledStoreError as exc:
            raise WorkflowStorageError(exc.code) from None

    def confirm(self) -> ControlledWorkflowState:
        state = self._active(None)
        if state.status is WorkflowStatus.AWAITING_PATCH_CONFIRMATION:
            return self.approve_patch(state.workflow_id)
        if state.status is WorkflowStatus.AWAITING_TEST_CONFIRMATION:
            return self.approve_tests(state.workflow_id)
        raise ActiveWorkflowError("invalid_stage")

    def _active(self, workflow_id: str | None) -> ControlledWorkflowState:
        state = self.store.load_active(workflow_id)
        if state is None:
            raise ActiveWorkflowError("workflow_not_found")
        return state

    @staticmethod
    def _workflow_type(value: str) -> str:
        if not isinstance(value, str):
            raise ControlledWorkflowError("unsupported_workflow_type")
        normalized = _TYPE_ALIASES.get(value, value)
        if normalized not in {"bug-fix", "feature", "refactor", "test", "review"}:
            raise ControlledWorkflowError("unsupported_workflow_type")
        return normalized

    def _binding(
        self,
        state: ControlledWorkflowState,
        expected_stage: WorkflowStatus,
        expected_action: str,
    ) -> ConfirmationBinding:
        binding = state.confirmation
        if state.status is not expected_stage or binding is None:
            raise ControlledWorkflowError("confirmation_binding_invalid")
        if (
            binding.workflow_id != state.workflow_id
            or binding.stage != state.status.value
            or binding.action != expected_action
            or binding.state_revision != state.revision
        ):
            raise ControlledWorkflowError("confirmation_binding_invalid")
        return binding

    def _prepare_patch(self, patch_id: str) -> dict[str, str]:
        try:
            if hasattr(self.patch_tools, "prepare_safe"):
                data = self.patch_tools.prepare_safe(patch_id)
            else:
                proxy = SimpleNamespace(artifacts={"requested_patch_id": patch_id})
                data = self.patch_tools.prepare(proxy)
            if not isinstance(data, dict):
                raise ValueError
            result = {
                "patch_id": data.get("patch_id"),
                "status": data.get("status"),
                "target_path": data.get("target_path"),
                "original_sha256": data.get("original_sha256")
                or _synthetic_sha(patch_id, "original"),
                "proposed_sha256": data.get("proposed_sha256")
                or _synthetic_sha(patch_id, "proposed"),
            }
            if result["patch_id"] != patch_id:
                raise ValueError
            return result
        except ControlledWorkflowError:
            raise
        except Exception:
            raise ControlledWorkflowError("managed_patch_invalid") from None

    def _resolve_test_group(self, group_id: str) -> tuple[str, str]:
        try:
            if hasattr(self.test_tools, "resolve"):
                result = self.test_tools.resolve(group_id)
                return result["group_id"], result["command_id"]
            if group_id != "workflow":
                raise ValueError
            return "workflow", "tests-workflow"
        except Exception:
            raise ControlledWorkflowError("test_configuration_missing") from None

    def _run_test_group(self, group_id: str, command_id: str) -> TestOutcome:
        try:
            if hasattr(self.test_tools, "run_group"):
                result = self.test_tools.run_group(group_id)
            else:
                legacy = self.test_tools.run_once(SimpleNamespace(workflow_type="bug-fix"))
                result = {
                    "passed": legacy.get("ok") is True,
                    "returncode": 0 if legacy.get("ok") is True else 1,
                    "timed_out": False,
                    "duration_ms": 0,
                    "outcome_code": "passed" if legacy.get("ok") is True else "failed",
                }
            return TestOutcome(
                group_id=group_id,
                command_id=command_id,
                passed=result.get("passed") is True,
                returncode=result.get("returncode"),
                timed_out=result.get("timed_out") is True,
                duration_ms=result.get("duration_ms", 0),
                outcome_code=result.get("outcome_code", "not_started"),
            )
        except ControlledWorkflowValidationError:
            raise ControlledWorkflowError("test_execution_failed") from None
        except Exception:
            return TestOutcome(group_id, command_id, False, None, False, 0, "not_started")

    def _require_confirmation_policy(self, tool_name: str) -> None:
        try:
            policy = load_permission_policy(self.project_root)
            decision = PermissionEvaluator(policy).evaluate(tool_name)
        except Exception:
            raise ControlledWorkflowError("permission_policy_error") from None
        if not decision.confirmation_required:
            raise ControlledWorkflowError("permission_policy_error")

    def _workspace_revision(self) -> str:
        status = git_status(self.project_root)
        log = git_log(self.project_root, 1)
        if (self.project_root / ".git").exists() and status.ok and log.ok:
            payload = (status.stdout[:100_000] + "\0" + log.stdout[:10_000]).encode(
                "utf-8", errors="replace"
            )
            return hashlib.sha256(payload).hexdigest()
        digest = hashlib.sha256(b"workspace-fallback-v1")
        total = 0
        count = 0
        for path in sorted(self.project_root.rglob("*")):
            try:
                relative = path.relative_to(self.project_root)
            except ValueError:
                continue
            if any(part.lower() in _BLOCKED_PARTS for part in relative.parts):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            encoded_name = relative.as_posix().encode("utf-8", errors="replace")
            digest.update(encoded_name)
            try:
                remaining = MAX_FALLBACK_REVISION_BYTES - total
                if remaining <= 0:
                    break
                content = path.read_bytes()[:remaining]
            except OSError:
                digest.update(b"unavailable")
            else:
                digest.update(hashlib.sha256(content).digest())
                total += len(content)
            count += 1
            if count >= MAX_FALLBACK_REVISION_FILES:
                break
        return digest.hexdigest()

    def _investigate(self, task: str) -> InvestigationEvidence:
        tokens = {
            token.lower()
            for token in re.findall(r"[A-Za-z0-9_]{4,}", task)
            if len(token) <= 64
        }
        related: list[str] = []
        inspected = 0
        matches = 0
        for path in sorted(self.project_root.rglob("*")):
            if inspected >= MAX_INSPECTION_FILES:
                break
            try:
                relative = path.relative_to(self.project_root)
            except ValueError:
                continue
            if any(part.lower() in _BLOCKED_PARTS for part in relative.parts):
                continue
            lowered = relative.as_posix().lower()
            if any(marker in lowered for marker in _SENSITIVE_MARKERS):
                continue
            if path.is_symlink() or not path.is_file():
                continue
            try:
                raw = path.read_bytes()[:MAX_INSPECTION_BYTES]
                text = raw.decode("utf-8", errors="ignore").lower()
            except OSError:
                continue
            inspected += 1
            file_matches = sum(text.count(token) for token in tokens)
            if any(token in lowered for token in tokens) or file_matches:
                if relative.as_posix() not in related and len(related) < 24:
                    related.append(relative.as_posix())
                matches = min(10_000, matches + file_matches)
        return InvestigationEvidence(
            tuple(related),
            inspected,
            matches,
            "related_evidence_found" if related else "insufficient_evidence",
            "not_configured",
        )

    def _complete_review(
        self,
        state: ControlledWorkflowState,
        scope: str,
    ) -> ControlledWorkflowState:
        if scope not in {"unstaged", "staged"}:
            raise ControlledWorkflowError("review_failed")
        result = git_diff(self.project_root) if scope == "unstaged" else git_diff_cached(self.project_root)
        if not result.ok:
            raise ControlledWorkflowError("review_failed")
        diff = result.stdout[:100_000]
        files: list[str] = []
        findings: list[ReviewFindingEvidence] = []
        current_file = ""
        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                current_file = line[6:]
                if current_file not in files and len(files) < 64:
                    files.append(current_file)
                continue
            if not current_file or not line.startswith("+") or line.startswith("+++"):
                continue
            checks = (
                ("<<<<<<<", "conflict_marker", "critical"),
                ("eval(", "dynamic_execution", "high"),
                ("exec(", "dynamic_execution", "high"),
                ("shell=True", "shell_execution", "high"),
            )
            for marker, code, severity in checks:
                if marker in line and len(findings) < 100:
                    findings.append(ReviewFindingEvidence(code, severity, current_file))
            if re.search(r"(?i)(password|secret|token)\s*=", line) and len(findings) < 100:
                findings.append(ReviewFindingEvidence("credential_marker", "critical", current_file))
        evidence = ReviewEvidence(
            scope=scope,
            diff_sha256=hashlib.sha256(diff.encode("utf-8", errors="replace")).hexdigest(),
            diff_bytes=len(diff.encode("utf-8", errors="replace")),
            truncated=len(result.stdout) > len(diff),
            files=tuple(files),
            findings=tuple(findings),
        )
        return state.evolve(
            status=WorkflowStatus.COMPLETED,
            next_actions=("show",),
            review=evidence,
            workspace_revision=self._workspace_revision(),
        )

    def _checkpoint(self, state: ControlledWorkflowState, reason: CheckpointReason) -> None:
        try:
            latest = self.checkpoint_store.latest(
                state.workflow_id, include_history=False
            )
            current_hash = payload_sha256(state.to_dict())
            if (
                latest is not None
                and latest.reason is reason
                and latest.workflow_status is state.status
                and latest.payload_sha256 == current_hash
            ):
                return
            self.checkpoint_store.create(state, reason)
            self._trace_decision(state, reason)
        except CheckpointStorageError:
            raise WorkflowStorageError("state_write_failed") from None

    def _trace_decision(self, state: ControlledWorkflowState, reason: CheckpointReason) -> None:
        """Best-effort allowlisted workflow trace; tracing never affects execution."""
        try:
            terminal_outcomes = {
                WorkflowStatus.COMPLETED: "completed",
                WorkflowStatus.FAILED: "failed",
                WorkflowStatus.CANCELLED: "cancelled",
                WorkflowStatus.ROLLED_BACK: "rolled_back",
            }
            outcome = terminal_outcomes.get(
                state.status,
                "awaiting_confirmation" if state.confirmation is not None else "in_progress",
            )
            trace_status = (
                TraceStatus.FAILED
                if state.status is WorkflowStatus.FAILED
                else TraceStatus.BLOCKED
                if state.confirmation is not None
                else TraceStatus.COMPLETED
            )
            decision = WorkflowTraceDecision(
                workflow_id=state.workflow_id,
                workflow_type=state.workflow_type,
                stage=state.status.value,
                action=state.confirmation.action if state.confirmation else "state_transition",
                outcome=outcome,
                iteration_count=state.iteration_count,
                confirmation_required=state.confirmation is not None,
                workspace_drift=state.workspace_drift,
                rollback_available=state.rollback_available,
                error_codes=state.error_codes,
            )
            append_trace(
                self.project_root,
                ExecutionTrace(
                    trace_id=f"{state.workflow_id}:{state.revision}:{reason.value}",
                    request_type="workflow",
                    intent=state.workflow_type,
                    domain="coding",
                    confirmation_required=state.confirmation is not None,
                    status=trace_status,
                    workflow_decision=decision,
                ),
            )
        except Exception:
            return

    def _archive_state(self, state: ControlledWorkflowState) -> None:
        self._checkpoint(state, CheckpointReason.STATE_TRANSITION)
        try:
            self.checkpoint_store.archive_workflow(state.workflow_id)
        except CheckpointStorageError:
            raise WorkflowStorageError("state_write_failed") from None
        self.store.archive(state)


def hmac_compare(left: str, right: str) -> bool:
    try:
        return hmac.compare_digest(left.encode("ascii"), right.encode("ascii"))
    except (UnicodeError, AttributeError):
        return False


__all__ = [
    "ActiveWorkflowError",
    "ControlledWorkflowError",
    "WorkflowEngine",
    "WorkflowStorageError",
]
