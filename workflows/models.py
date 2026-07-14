"""Persistent models and state rules for VEGA coding workflows."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

WORKFLOW_ID_PATTERN = re.compile(r"^workflow-[0-9a-f]{32}$")


class WorkflowError(RuntimeError):
    """Base workflow error."""


class WorkflowStateError(WorkflowError):
    """Invalid workflow state transition."""


class WorkflowStatus(str, Enum):
    PLANNED = "planned"
    INVESTIGATING = "investigating"
    AWAITING_PATCH_CONFIRMATION = "awaiting_patch_confirmation"
    PATCH_APPLIED = "patch_applied"
    AWAITING_TEST_CONFIRMATION = "awaiting_test_confirmation"
    TESTS_RUNNING = "tests_running"
    ROLLED_BACK = "rolled_back"
    CREATED = "created"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    WAITING_PATCH = "waiting_patch"
    WAITING_CONFIRMATION = "waiting_confirmation"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


TERMINAL_STATUSES=frozenset({WorkflowStatus.COMPLETED,WorkflowStatus.FAILED,WorkflowStatus.CANCELLED,WorkflowStatus.ROLLED_BACK})
ALLOWED_TRANSITIONS={
 WorkflowStatus.PLANNED:frozenset({WorkflowStatus.INVESTIGATING,WorkflowStatus.AWAITING_TEST_CONFIRMATION,WorkflowStatus.COMPLETED,WorkflowStatus.CANCELLED,WorkflowStatus.FAILED}),
 WorkflowStatus.INVESTIGATING:frozenset({WorkflowStatus.WAITING_PATCH,WorkflowStatus.COMPLETED,WorkflowStatus.CANCELLED,WorkflowStatus.FAILED}),
 WorkflowStatus.AWAITING_PATCH_CONFIRMATION:frozenset({WorkflowStatus.PATCH_APPLIED,WorkflowStatus.CANCELLED,WorkflowStatus.FAILED}),
 WorkflowStatus.PATCH_APPLIED:frozenset({WorkflowStatus.AWAITING_TEST_CONFIRMATION,WorkflowStatus.ROLLED_BACK,WorkflowStatus.FAILED}),
 WorkflowStatus.AWAITING_TEST_CONFIRMATION:frozenset({WorkflowStatus.TESTS_RUNNING,WorkflowStatus.CANCELLED,WorkflowStatus.ROLLED_BACK,WorkflowStatus.FAILED}),
 WorkflowStatus.TESTS_RUNNING:frozenset({WorkflowStatus.WAITING_PATCH,WorkflowStatus.COMPLETED,WorkflowStatus.FAILED}),
 WorkflowStatus.ROLLED_BACK:frozenset(),
 WorkflowStatus.CREATED:frozenset({WorkflowStatus.ANALYZING,WorkflowStatus.CANCELLED,WorkflowStatus.FAILED}),
 WorkflowStatus.ANALYZING:frozenset({WorkflowStatus.PLANNING,WorkflowStatus.CANCELLED,WorkflowStatus.FAILED}),
 WorkflowStatus.PLANNING:frozenset({WorkflowStatus.WAITING_PATCH,WorkflowStatus.CANCELLED,WorkflowStatus.FAILED}),
 WorkflowStatus.WAITING_PATCH:frozenset({WorkflowStatus.WAITING_CONFIRMATION,WorkflowStatus.CANCELLED,WorkflowStatus.FAILED}),
 WorkflowStatus.WAITING_CONFIRMATION:frozenset({WorkflowStatus.EXECUTING,WorkflowStatus.CANCELLED,WorkflowStatus.FAILED}),
 WorkflowStatus.EXECUTING:frozenset({WorkflowStatus.VERIFYING,WorkflowStatus.CANCELLED,WorkflowStatus.FAILED}),
 WorkflowStatus.VERIFYING:frozenset({WorkflowStatus.WAITING_PATCH,WorkflowStatus.REVIEWING,WorkflowStatus.FAILED,WorkflowStatus.CANCELLED}),
 WorkflowStatus.REVIEWING:frozenset({WorkflowStatus.WAITING_PATCH,WorkflowStatus.COMPLETED,WorkflowStatus.FAILED,WorkflowStatus.CANCELLED}),
 WorkflowStatus.COMPLETED:frozenset(),WorkflowStatus.FAILED:frozenset(),WorkflowStatus.CANCELLED:frozenset(),}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_workflow_id(value: str) -> str:
    if not isinstance(value, str) or not WORKFLOW_ID_PATTERN.fullmatch(value):
        raise ValueError("Invalid workflow_id.")
    return value


def validate_transition(
    current: WorkflowStatus | str,
    target: WorkflowStatus | str,
) -> WorkflowStatus:
    try:
        source = WorkflowStatus(current)
        destination = WorkflowStatus(target)
    except (TypeError, ValueError) as exc:
        raise WorkflowStateError(
            f"Unknown workflow status: {current!r} -> {target!r}."
        ) from exc
    if destination not in ALLOWED_TRANSITIONS[source]:
        raise WorkflowStateError(f"Workflow cannot transition from {source.value!r} to {destination.value!r}.")
    return destination


@dataclass(slots=True)
class WorkflowStep:
    step_id: str
    name: str
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str = ""
    started_at: str | None = None
    completed_at: str | None = None

    def start(self) -> None:
        if self.status is not StepStatus.PENDING:
            raise WorkflowStateError(
                f"Step {self.step_id} cannot start from {self.status.value}."
            )
        self.status = StepStatus.RUNNING
        self.started_at = utc_now()

    def complete(self, result: Any) -> None:
        if self.status is not StepStatus.RUNNING:
            raise WorkflowStateError(f"Step {self.step_id} is not running.")
        self.result = result
        self.status = StepStatus.COMPLETED
        self.completed_at = utc_now()

    def fail(self, error: Exception | str) -> None:
        self.error = str(error)
        self.status = StepStatus.FAILED
        self.completed_at = utc_now()

    def skip(self, result: Any) -> None:
        if self.status is StepStatus.PENDING:
            self.start()
        if self.status is not StepStatus.RUNNING:
            raise WorkflowStateError(
                f"Step {self.step_id} cannot be skipped from {self.status.value}."
            )
        self.result = result
        self.status = StepStatus.SKIPPED
        self.completed_at = utc_now()
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowStep":
        values = dict(data)
        values["status"] = StepStatus(values.get("status", "pending"))
        return cls(**values)


@dataclass(slots=True)
class WorkflowRun:
    workflow_id: str
    workflow_type: str
    task: str
    steps: list[WorkflowStep]
    status: WorkflowStatus = WorkflowStatus.CREATED
    plan: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    required_confirmations: list[str] = field(default_factory=list)
    verification_results: list[dict[str, Any]] = field(default_factory=list)
    test_fix_iterations: list[dict[str, Any]] = field(default_factory=list)
    review_results: list[dict[str, Any]] = field(default_factory=list)
    patch_request_reason: str = "initial"
    max_fix_attempts: int = 3
    changed_files: list[str] = field(default_factory=list)
    manual_intervention_required: bool = False
    patch: dict[str, Any] | None = None
    error: str = ""
    report: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    linked_task_id: str | None = None
    def __post_init__(self) -> None:
        if not isinstance(self.review_results,list):
            raise ValueError("review_results must be a list.")
        from review.models import ReviewReport
        self.review_results=[ReviewReport.from_dict(item).to_dict() for item in self.review_results]
        if self.patch_request_reason not in {"initial","test_failure","review_findings"}:
            raise ValueError("Invalid patch_request_reason.")
        if (
            isinstance(self.max_fix_attempts, bool)
            or not isinstance(self.max_fix_attempts, int)
            or not 1 <= self.max_fix_attempts <= 10
        ):
            raise ValueError("max_fix_attempts must be between 1 and 10.")
    @classmethod
    def create(
        cls,
        workflow_type: str,
        task: str,
        steps: list[WorkflowStep],
    ) -> "WorkflowRun":
        if not task.strip():
            raise ValueError("Workflow task must not be empty.")
        normalized = [
            step
            if isinstance(step, WorkflowStep)
            else WorkflowStep(f"step-{index}", str(step))
            for index, step in enumerate(steps, 1)
        ]
        return cls(
            f"workflow-{uuid4().hex}",
            workflow_type,
            task.strip(),
            normalized,
        )
    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES
    @property
    def completed_steps(self) -> list[str]:
        return [
            step.step_id
            for step in self.steps
            if step.status is StepStatus.COMPLETED
        ]
    @property
    def current_step(self) -> int:
        return len(self.completed_steps)
    def step(self, step_id: str) -> WorkflowStep:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        raise WorkflowStateError(f"Unknown workflow step: {step_id}.")
    def transition(self, target: WorkflowStatus) -> None:
        self.status = validate_transition(self.status, target)
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        for step in result["steps"]:
            step["status"] = step["status"].value
        result["completed_steps"] = self.completed_steps
        return result
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowRun":
        if not isinstance(data, dict):
            raise ValueError("Workflow JSON root must be an object.")
        values = dict(data)
        values.pop("completed_steps", None)
        validate_workflow_id(values.get("workflow_id"))
        values["status"] = WorkflowStatus(values["status"])
        values["steps"] = [
            WorkflowStep.from_dict(item)
            for item in values.get("steps", [])
        ]
        return cls(**values)
