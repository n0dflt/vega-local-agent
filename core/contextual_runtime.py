from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from core.contextual_router import (
    ContextualRouteResult,
    ContextualRoutingError,
    load_tool_routing_policy,
    route_contextual_request,
)
from core.intent_analyzer import analyze_intent
from core.plan_executor import (
    PlanExecutionResult,
    PlanExecutionStatus,
    execute_plan,
)
from core.tool_executor import ToolExecutor


class ContextualRuntimeStatus(str, Enum):
    """Outcome of contextual runtime handling."""

    NOT_HANDLED = "not_handled"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ContextualRuntimeResult:
    """Result of attempting contextual tool execution."""

    status: ContextualRuntimeStatus
    message: str = ""
    reason: str = ""
    route_result: ContextualRouteResult | None = None
    execution_result: PlanExecutionResult | None = None

    @property
    def handled(self) -> bool:
        return (
            self.status
            is not ContextualRuntimeStatus.NOT_HANDLED
        )

    @property
    def ok(self) -> bool:
        return (
            self.status
            is ContextualRuntimeStatus.COMPLETED
        )


def _format_data(
    value: Any,
    *,
    max_chars: int = 4000,
) -> tuple[str, bool]:
    try:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                default=str,
            )
    except (TypeError, ValueError):
        text = repr(value)

    if len(text) <= max_chars:
        return text, False

    return text[:max_chars] + "\n...[truncated]", True


def _format_execution(
    route_result: ContextualRouteResult,
    execution_result: PlanExecutionResult,
) -> str:
    lines = [
        "Contextual tool execution",
        (
            "Intent: "
            f"{route_result.analysis.intent.value}"
        ),
        (
            "Status: "
            f"{execution_result.status.value.upper()}"
        ),
        (
            "Completed steps: "
            f"{len(execution_result.steps)}"
        ),
    ]

    if execution_result.error:
        lines.append(
            f"Error: {execution_result.error}"
        )

    for step in execution_result.steps:
        lines.extend(
            [
                "",
                f"Step {step.step_id}",
                f"  Tool: {step.tool_name}",
                f"  Status: {step.status.value}",
            ]
        )

        if step.error:
            lines.append(
                f"  Error: {step.error}"
            )

        if step.data is not None:
            formatted, truncated = _format_data(
                step.data
            )

            lines.append("  Result:")
            lines.extend(
                f"    {line}"
                for line in formatted.splitlines()
            )

            if truncated:
                lines.append(
                    "  Output truncated: yes"
                )

    return "\n".join(lines)


def try_execute_contextual_request(
    text: str,
    project_root: str | Path,
    tool_executor: ToolExecutor,
    *,
    registry: object | None = None,
    capability_config: (
        Mapping[str, Any] | str | Path | None
    ) = None,
    policy_config: (
        Mapping[str, Any] | str | Path | None
    ) = None,
) -> ContextualRuntimeResult:
    """
    Attempt contextual execution before model fallback.

    Disabled routing and unsupported intents return NOT_HANDLED.
    Actionable failures remain handled and do not fall through
    to the language model.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    if not isinstance(tool_executor, ToolExecutor):
        raise TypeError(
            "tool_executor must be a ToolExecutor instance"
        )

    normalized_text = text.strip()

    if not normalized_text:
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.NOT_HANDLED,
            reason="empty_input",
        )

    root = Path(project_root).resolve()

    if not root.is_dir():
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.FAILED,
            message=(
                "Contextual runtime error: "
                f"project root is not a directory: {root}"
            ),
            reason="invalid_project_root",
        )

    if registry is None:
        from tools.registry import TOOL_REGISTRY

        registry = TOOL_REGISTRY

    if capability_config is None:
        capability_config = (
            root / "config" / "tool_capabilities.json"
        )

    if policy_config is None:
        policy_config = (
            root / "config" / "tool_routing_policy.json"
        )

    try:
        policy = load_tool_routing_policy(
            policy_config
        )
    except ContextualRoutingError as exc:
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.FAILED,
            message=(
                "Contextual runtime error: "
                f"{exc}"
            ),
            reason="policy_error",
        )

    if not policy.enabled:
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.NOT_HANDLED,
            reason="disabled_by_policy",
        )

    analysis = analyze_intent(normalized_text)

    if not analysis.is_actionable:
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.NOT_HANDLED,
            reason="unsupported_intent",
        )

    try:
        route_result = route_contextual_request(
            normalized_text,
            registry,
            capability_config,
            policy_config,
            workspace=root,
            preview=False,
        )
    except ContextualRoutingError as exc:
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.FAILED,
            message=(
                "Contextual runtime error: "
                f"{exc}"
            ),
            reason="routing_error",
        )

    execution_result = execute_plan(
        route_result.plan,
        tool_executor,
        automatic_permissions=(
            policy.automatic_permissions
        ),
    )

    status_map = {
        PlanExecutionStatus.COMPLETED: (
            ContextualRuntimeStatus.COMPLETED
        ),
        PlanExecutionStatus.BLOCKED: (
            ContextualRuntimeStatus.BLOCKED
        ),
        PlanExecutionStatus.FAILED: (
            ContextualRuntimeStatus.FAILED
        ),
    }

    return ContextualRuntimeResult(
        status=status_map[execution_result.status],
        message=_format_execution(
            route_result,
            execution_result,
        ),
        reason=execution_result.status.value,
        route_result=route_result,
        execution_result=execution_result,
    )


__all__ = [
    "ContextualRuntimeResult",
    "ContextualRuntimeStatus",
    "try_execute_contextual_request",
]
