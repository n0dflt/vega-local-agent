from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.contextual_router import (
    ContextualRouteResult,
    ContextualRoutingError,
    route_contextual_request,
)
from core.plan_executor import (
    PlanExecutionResult,
    execute_plan,
)
from core.tool_executor import ToolExecutor


PLAN_HELP = """Contextual planning commands:
  /plan <task>       Build a preview without executing tools
  /plan run <task>   Execute an explicitly requested safe plan

Examples:
  /plan Найди в проекте использование старого API
  /plan run Найди в проекте использование старого API
  /plan Проанализируй "docs/report.md" и сделай краткий отчёт

Execution restrictions:
  Only policy-approved automatic permissions can run.
  WRITE, EXECUTE, SEND, DELETE and ADMIN remain blocked.
  Arbitrary shell commands are never generated."""


def _format_value(
    value: object,
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


def _format_preview(
    result: ContextualRouteResult,
) -> str:
    lines = [
        "Contextual execution plan",
        f"Intent: {result.analysis.intent.value}",
        f"Confidence: {result.analysis.confidence:.2f}",
        "Execution: preview only",
        (
            "Requires confirmation: "
            + (
                "yes"
                if result.requires_confirmation
                else "no"
            )
        ),
        f"Steps: {len(result.plan.steps)}",
    ]

    for step in result.plan.steps:
        lines.extend(
            [
                "",
                f"Step {step.step_id}",
                f"  Tool: {step.tool_name}",
                (
                    "  Permission: "
                    f"{step.required_permission}"
                ),
            ]
        )

        if step.depends_on:
            dependencies = ", ".join(
                str(item)
                for item in step.depends_on
            )
            lines.append(
                f"  Depends on: {dependencies}"
            )

        if step.arguments:
            lines.append("  Arguments:")

            for name, value in sorted(
                step.arguments.items()
            ):
                formatted, _ = _format_value(value)
                lines.append(
                    f"    {name}: {formatted}"
                )
        else:
            lines.append("  Arguments: none")

    return "\n".join(lines)


def _format_execution(
    result: PlanExecutionResult,
) -> str:
    lines = [
        "Contextual plan execution",
        f"Status: {result.status.value.upper()}",
        f"Goal: {result.goal}",
        f"Completed steps: {len(result.steps)}",
    ]

    if result.error:
        lines.append(f"Error: {result.error}")

    for step in result.steps:
        lines.extend(
            [
                "",
                f"Step {step.step_id}",
                f"  Tool: {step.tool_name}",
                f"  Status: {step.status.value}",
            ]
        )

        if step.error:
            lines.append(f"  Error: {step.error}")

        if step.data is not None:
            formatted, truncated = _format_value(
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


def handle_plan_command(
    command: str,
    project_root: str | Path,
    *,
    registry: object | None = None,
    capability_config: (
        Mapping[str, Any] | str | Path | None
    ) = None,
    policy_config: (
        Mapping[str, Any] | str | Path | None
    ) = None,
    tool_executor: ToolExecutor | None = None,
) -> str:
    """Preview or explicitly execute a contextual plan."""

    if not isinstance(command, str):
        raise TypeError("command must be a string")

    root = Path(project_root).resolve()
    stripped = command.strip()
    parts = stripped.split(maxsplit=1)

    if (
        not parts
        or parts[0].lower() != "/plan"
        or len(parts) == 1
        or not parts[1].strip()
    ):
        return PLAN_HELP

    payload = parts[1].strip()
    payload_lower = payload.lower()

    if payload_lower == "run":
        return PLAN_HELP

    run_requested = payload_lower.startswith("run ")

    task_text = (
        payload[4:].strip()
        if run_requested
        else payload
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
        route_result = route_contextual_request(
            task_text,
            registry,
            capability_config,
            policy_config,
            workspace=root,
            preview=True,
        )
    except ContextualRoutingError as exc:
        return f"Plan command error: {exc}"

    if not run_requested:
        return _format_preview(route_result)

    if not route_result.policy.allow_explicit_execution:
        return (
            "Plan command error: explicit plan execution "
            "is disabled by policy"
        )

    if tool_executor is None:
        return (
            "Plan command error: production ToolExecutor "
            "is unavailable"
        )

    if not isinstance(tool_executor, ToolExecutor):
        return (
            "Plan command error: invalid ToolExecutor"
        )

    execution_result = execute_plan(
        route_result.plan,
        tool_executor,
        automatic_permissions=(
            route_result.policy.automatic_permissions
        ),
    )

    return _format_execution(execution_result)


__all__ = [
    "PLAN_HELP",
    "handle_plan_command",
]
