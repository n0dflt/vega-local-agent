from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from core.execution_plan import ExecutionPlan
from core.tool_executor import (
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolExecutor,
    ToolRequest,
)


class PlanExecutionStatus(str, Enum):
    """Final outcome of controlled plan execution."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StepExecutionResult:
    """Detached result of one execution-plan step."""

    step_id: int
    tool_name: str
    status: ToolExecutionStatus
    data: Any = None
    error: str = ""
    error_code: str = ""

    @property
    def ok(self) -> bool:
        return self.status is ToolExecutionStatus.SUCCESS

    @classmethod
    def from_tool_result(
        cls,
        step_id: int,
        result: ToolExecutionResult,
    ) -> "StepExecutionResult":
        return cls(
            step_id=step_id,
            tool_name=result.tool_name,
            status=result.status,
            data=result.data,
            error=result.error,
            error_code=result.error_code,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True)
class PlanExecutionResult:
    """Controlled result of a complete execution attempt."""

    status: PlanExecutionStatus
    goal: str
    steps: tuple[StepExecutionResult, ...] = ()
    error: str = ""
    blocked_step_id: int | None = None
    blocked_tool_name: str = ""

    @property
    def ok(self) -> bool:
        return self.status is PlanExecutionStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "goal": self.goal,
            "steps": [
                step.to_dict()
                for step in self.steps
            ],
            "error": self.error,
            "blocked_step_id": self.blocked_step_id,
            "blocked_tool_name": self.blocked_tool_name,
        }


def _normalize_permissions(
    permissions: Iterable[str],
) -> frozenset[str]:
    if isinstance(permissions, str):
        raise TypeError(
            "automatic_permissions must be an iterable "
            "of permission names"
        )

    normalized: set[str] = set()

    for permission in permissions:
        if not isinstance(permission, str):
            raise TypeError(
                "automatic permission names must be strings"
            )

        value = permission.strip().upper()

        if value:
            normalized.add(value)

    if not normalized:
        raise ValueError(
            "automatic_permissions must not be empty"
        )

    return frozenset(normalized)


def execute_plan(
    plan: ExecutionPlan,
    executor: ToolExecutor,
    *,
    automatic_permissions: Iterable[str] = (
        "READ",
        "DRAFT",
    ),
) -> PlanExecutionResult:
    """
    Execute a fully validated plan through ToolExecutor.

    All steps are preflight-checked before the first tool call.
    Execution stops immediately after the first failed step.
    Confirmation tokens are never generated or accepted here.
    """

    if not isinstance(plan, ExecutionPlan):
        raise TypeError(
            "plan must be an ExecutionPlan instance"
        )

    if not isinstance(executor, ToolExecutor):
        raise TypeError(
            "executor must be a ToolExecutor instance"
        )

    allowed_permissions = _normalize_permissions(
        automatic_permissions
    )
    registered_tools = set(
        executor.registered_tools()
    )

    # Full preflight is deliberately completed before any
    # tool is called. This prevents partially executing a
    # plan whose later step is unsafe or unregistered.
    for step in plan.steps:
        if (
            step.required_permission
            not in allowed_permissions
        ):
            return PlanExecutionResult(
                status=PlanExecutionStatus.BLOCKED,
                goal=plan.goal,
                error=(
                    f"step {step.step_id} requires "
                    f"non-automatic permission: "
                    f"{step.required_permission}"
                ),
                blocked_step_id=step.step_id,
                blocked_tool_name=step.tool_name,
            )

        if step.tool_name not in registered_tools:
            return PlanExecutionResult(
                status=PlanExecutionStatus.BLOCKED,
                goal=plan.goal,
                error=(
                    f"step {step.step_id} references "
                    f"unregistered tool: {step.tool_name}"
                ),
                blocked_step_id=step.step_id,
                blocked_tool_name=step.tool_name,
            )

    completed_step_ids: set[int] = set()
    step_results: list[StepExecutionResult] = []

    for step in plan.steps:
        missing_dependencies = [
            dependency
            for dependency in step.depends_on
            if dependency not in completed_step_ids
        ]

        if missing_dependencies:
            return PlanExecutionResult(
                status=PlanExecutionStatus.FAILED,
                goal=plan.goal,
                steps=tuple(step_results),
                error=(
                    f"step {step.step_id} has incomplete "
                    f"dependencies: {missing_dependencies}"
                ),
                blocked_step_id=step.step_id,
                blocked_tool_name=step.tool_name,
            )

        tool_result = executor.execute(
            ToolRequest(
                tool_name=step.tool_name,
                arguments=dict(step.arguments),
            )
        )

        step_result = (
            StepExecutionResult.from_tool_result(
                step.step_id,
                tool_result,
            )
        )
        step_results.append(step_result)

        if not tool_result.ok:
            detail = (
                tool_result.error
                or tool_result.status.value
            )

            return PlanExecutionResult(
                status=PlanExecutionStatus.FAILED,
                goal=plan.goal,
                steps=tuple(step_results),
                error=(
                    f"step {step.step_id} failed: "
                    f"{detail}"
                ),
                blocked_step_id=step.step_id,
                blocked_tool_name=step.tool_name,
            )

        completed_step_ids.add(step.step_id)

    return PlanExecutionResult(
        status=PlanExecutionStatus.COMPLETED,
        goal=plan.goal,
        steps=tuple(step_results),
    )


__all__ = [
    "PlanExecutionResult",
    "PlanExecutionStatus",
    "StepExecutionResult",
    "execute_plan",
]
