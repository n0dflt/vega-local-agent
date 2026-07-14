from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from core.execution_progress import (
    ExecutionProgressEvent,
    ExecutionProgressStage,
    safe_progress_title,
)
from core.execution_plan import ExecutionPlan
from core.execution_trace import (
    safe_trace_error_code,
    safe_trace_permission,
    safe_trace_risk,
)
from core.tool_executor import (
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolExecutor,
    ToolRequest,
)
from core.tool_confirmation import (
    ToolConfirmationManager,
    execute_tool_with_confirmation,
)


class PlanExecutionStatus(str, Enum):
    """Final outcome of controlled plan execution."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StepExecutionObservation:
    """Allowlisted, payload-free observation of one plan step decision."""

    step_id: int
    tool_name: str
    permission: str
    risk: str
    status: str
    error_code: str = ""


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


def _reported_tool_failure(
    tool_name: str,
    data: Any,
) -> tuple[str, str, Mapping[str, Any] | None]:
    """Return a safe category reported inside a tool result."""

    if isinstance(data, Mapping):
        if data.get("ok") is not False:
            return "", "", None

        if tool_name == "test_run":
            reason_code = data.get("reason_code")
            nested = data.get("data")
            diagnostics = data.get("diagnostics")
            if isinstance(nested, Mapping):
                diagnostics = nested.get("diagnostics", diagnostics)
            safe_diagnostics = (
                dict(diagnostics)
                if isinstance(diagnostics, Mapping)
                else None
            )
            if reason_code == "test_failure":
                returncode = nested.get("returncode") if isinstance(nested, Mapping) else None
                if isinstance(returncode, int) and not isinstance(returncode, bool):
                    return (
                        f"Test suite failed with exit code {returncode}.",
                        "test_failure",
                        safe_diagnostics,
                    )
                return (
                    "Test suite failed.",
                    "test_failure",
                    safe_diagnostics,
                )
            if reason_code == "timeout":
                return (
                    "Test execution exceeded the configured timeout.",
                    "timeout",
                    safe_diagnostics,
                )
            if reason_code == "runtime_unavailable":
                return (
                    "Test runner could not start the configured Python runtime.",
                    "runtime_unavailable",
                    safe_diagnostics,
                )
            if reason_code == "result_parse_error":
                return (
                    "Test result could not be parsed.",
                    "result_parse_error",
                    safe_diagnostics,
                )

        return "Tool reported an unsuccessful result.", "tool_reported_failure", None

    try:
        ok = getattr(data, "ok", None)
    except Exception:
        return "", "", None

    if ok is not False:
        return "", "", None
    return "Tool reported an unsuccessful result.", "tool_reported_failure", None


def execute_plan(
    plan: ExecutionPlan,
    executor: ToolExecutor,
    *,
    automatic_permissions: Iterable[str] = (
        "READ",
        "DRAFT",
    ),
    confirmation_permissions: Iterable[str] = (),
    confirmation_manager: ToolConfirmationManager | None = None,
    risk_by_tool: Mapping[str, str] | None = None,
    step_observer: Callable[[StepExecutionObservation], None] | None = None,
    progress_callback: Callable[[ExecutionProgressEvent], object] | None = None,
) -> PlanExecutionResult:
    """
    Execute a fully validated plan through ToolExecutor.

    All steps are preflight-checked before the first tool call.
    Execution stops immediately after the first failed step.
    Confirmed permissions use the existing one-time confirmation manager;
    without it, non-automatic steps remain blocked before execution.
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
    confirmed_permissions = frozenset(
        permission.strip().upper()
        for permission in confirmation_permissions
        if isinstance(permission, str) and permission.strip()
    )
    registered_tools = set(
        executor.registered_tools()
    )
    try:
        configured_risks = dict(risk_by_tool or {})
    except Exception:
        configured_risks = {}

    titles = tuple(
        safe_progress_title(step.description) or f"Операция {position}"
        for position, step in enumerate(plan.steps, 1)
    )
    ordinal_by_step_id = {
        step.step_id: position
        for position, step in enumerate(plan.steps, 1)
    }
    title_by_step_id = {
        step.step_id: titles[position - 1]
        for position, step in enumerate(plan.steps, 1)
    }

    def report(event: ExecutionProgressEvent) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(event)
        except Exception:
            return

    report(
        ExecutionProgressEvent(
            stage=ExecutionProgressStage.PLAN_READY,
            total_steps=len(plan.steps),
            plan_titles=titles,
        )
    )

    def observe(
        step,
        status: str,
        error_code: str = "",
    ) -> None:
        if step_observer is None:
            return
        try:
            safe_permission = safe_trace_permission(step.required_permission)
            if not safe_permission:
                return
            safe_error_code = ""
            if error_code:
                safe_error_code = safe_trace_error_code(
                    error_code,
                    fallback="tool_execution_failed",
                )
            observation = StepExecutionObservation(
                step_id=step.step_id,
                tool_name=step.tool_name,
                permission=safe_permission,
                risk=safe_trace_risk(configured_risks.get(step.tool_name, "")),
                status=status,
                error_code=safe_error_code,
            )
            step_observer(observation)
        except Exception:
            return

    # Full preflight is deliberately completed before any
    # tool is called. This prevents partially executing a
    # plan whose later step is unsafe or unregistered.
    for step in plan.steps:
        can_request_confirmation = (
            confirmation_manager is not None
            and step.required_permission in confirmed_permissions
        )
        if (
            step.required_permission not in allowed_permissions
            and not can_request_confirmation
        ):
            observe(step, "blocked", "permission_not_automatic")
            position = ordinal_by_step_id[step.step_id]
            report(
                ExecutionProgressEvent(
                    stage=ExecutionProgressStage.AWAITING_CONFIRMATION,
                    current_step=position,
                    total_steps=len(plan.steps),
                    title=(
                        "Ожидаю подтверждение: "
                        f"{title_by_step_id[step.step_id]}"
                    ),
                )
            )
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
            observe(step, "blocked", "tool_unregistered")
            position = ordinal_by_step_id[step.step_id]
            report(
                ExecutionProgressEvent(
                    stage=ExecutionProgressStage.STEP_FAILED,
                    current_step=position,
                    total_steps=len(plan.steps),
                    title=(
                        f"Шаг «{title_by_step_id[step.step_id]}» "
                        "недоступен"
                    ),
                )
            )
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
        position = ordinal_by_step_id[step.step_id]
        title = title_by_step_id[step.step_id]
        missing_dependencies = [
            dependency
            for dependency in step.depends_on
            if dependency not in completed_step_ids
        ]

        if missing_dependencies:
            observe(step, "failed", "incomplete_dependencies")
            report(
                ExecutionProgressEvent(
                    stage=ExecutionProgressStage.STEP_FAILED,
                    current_step=position,
                    total_steps=len(plan.steps),
                    title=(
                        f"Шаг «{title}» "
                        "завершился с ошибкой"
                    ),
                )
            )
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

        report(
            ExecutionProgressEvent(
                stage=ExecutionProgressStage.STEP_RUNNING,
                current_step=position,
                total_steps=len(plan.steps),
                title=title,
            )
        )

        if step.required_permission not in allowed_permissions:
            report(
                ExecutionProgressEvent(
                    stage=ExecutionProgressStage.AWAITING_CONFIRMATION,
                    current_step=position,
                    total_steps=len(plan.steps),
                    title=f"Ожидаю подтверждение: {title}",
                )
            )

        try:
            request = ToolRequest(
                tool_name=step.tool_name,
                arguments=dict(step.arguments),
            )
            if step.required_permission in allowed_permissions:
                tool_result = executor.execute(request)
            else:
                tool_result = execute_tool_with_confirmation(
                    executor,
                    request,
                    confirmation_manager,
                )
        except Exception:
            tool_result = ToolExecutionResult(
                status=ToolExecutionStatus.FAILED,
                tool_name=step.tool_name,
                error="Tool execution failed.",
                error_code="tool_execution_failed",
            )

        reported_error = ""
        reported_error_code = ""
        reported_diagnostics = None

        if tool_result.ok:
            (
                reported_error,
                reported_error_code,
                reported_diagnostics,
            ) = _reported_tool_failure(
                step.tool_name,
                tool_result.data
            )

        if reported_error:
            tool_result = ToolExecutionResult(
                status=ToolExecutionStatus.FAILED,
                tool_name=tool_result.tool_name,
                data=(
                    {"diagnostics": dict(reported_diagnostics)}
                    if reported_diagnostics is not None
                    else None
                ),
                error=reported_error,
                error_code=(
                    reported_error_code
                    or "tool_reported_failure"
                ),
            )

        step_result = (
            StepExecutionResult.from_tool_result(
                step.step_id,
                tool_result,
            )
        )
        step_results.append(step_result)

        observation_error_code = tool_result.error_code
        if not tool_result.ok and not observation_error_code:
            observation_error_code = (
                tool_result.status.value
                if tool_result.status is not ToolExecutionStatus.FAILED
                else "tool_execution_failed"
            )
        if observation_error_code:
            observation_error_code = safe_trace_error_code(
                observation_error_code,
                fallback="tool_execution_failed",
            )
        observe(
            step,
            tool_result.status.value,
            observation_error_code,
        )

        if not tool_result.ok:
            report(
                ExecutionProgressEvent(
                    stage=ExecutionProgressStage.STEP_FAILED,
                    current_step=position,
                    total_steps=len(plan.steps),
                    title=(
                        f"Шаг «{title}» "
                        "завершился с ошибкой"
                    ),
                )
            )
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
        report(
            ExecutionProgressEvent(
                stage=ExecutionProgressStage.STEP_COMPLETED,
                current_step=position,
                total_steps=len(plan.steps),
                title=title,
            )
        )

    return PlanExecutionResult(
        status=PlanExecutionStatus.COMPLETED,
        goal=plan.goal,
        steps=tuple(step_results),
    )


__all__ = [
    "PlanExecutionResult",
    "PlanExecutionStatus",
    "StepExecutionObservation",
    "StepExecutionResult",
    "execute_plan",
]
