from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.execution_plan import ExecutionPlan
from core.intent_analyzer import IntentAnalysis, analyze_intent
from core.task_interpreter import (
    TaskInterpretation,
    TaskInterpretationError,
    interpret_task,
)
from core.tool_catalog import (
    ToolCatalogError,
    build_tool_catalog,
)
from core.tool_planner import (
    ToolPlanningError,
    plan_tools,
)


class ContextualRoutingError(ValueError):
    """Raised when contextual routing cannot safely continue."""


class ContextualRoutingDisabled(ContextualRoutingError):
    """Raised when contextual routing is disabled by policy."""


@dataclass(frozen=True)
class ToolRoutingPolicy:
    """Validated policy controlling contextual tool routing."""

    enabled: bool
    allow_explicit_execution: bool
    automatic_permissions: tuple[str, ...]
    confirmation_permissions: tuple[str, ...]
    max_tool_steps: int
    allow_arbitrary_tool_names: bool
    allow_shell_generation: bool
    fail_closed: bool

    def __post_init__(self) -> None:
        automatic_permissions = tuple(
            dict.fromkeys(
                permission.strip().upper()
                for permission in self.automatic_permissions
                if permission.strip()
            )
        )
        confirmation_permissions = tuple(
            dict.fromkeys(
                permission.strip().upper()
                for permission in self.confirmation_permissions
                if permission.strip()
            )
        )

        object.__setattr__(
            self,
            "automatic_permissions",
            automatic_permissions,
        )
        object.__setattr__(
            self,
            "confirmation_permissions",
            confirmation_permissions,
        )

        if not automatic_permissions:
            raise ContextualRoutingError(
                "automatic_permissions must not be empty"
            )

        overlap = set(automatic_permissions).intersection(
            confirmation_permissions
        )

        if overlap:
            names = ", ".join(sorted(overlap))
            raise ContextualRoutingError(
                f"permissions cannot be both automatic "
                f"and confirmed: {names}"
            )

        if self.max_tool_steps < 1:
            raise ContextualRoutingError(
                "max_tool_steps must be greater than zero"
            )

        if self.allow_arbitrary_tool_names:
            raise ContextualRoutingError(
                "arbitrary tool names are not supported"
            )

        if self.allow_shell_generation:
            raise ContextualRoutingError(
                "shell generation is not supported"
            )


@dataclass(frozen=True)
class ContextualRouteResult:
    """Non-executing result of contextual request routing."""

    analysis: IntentAnalysis
    interpretation: TaskInterpretation
    plan: ExecutionPlan
    policy: ToolRoutingPolicy
    requires_confirmation: bool

    @property
    def can_auto_execute(self) -> bool:
        return (
            self.policy.enabled
            and not self.requires_confirmation
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.analysis.to_dict(),
            "interpretation": self.interpretation.to_dict(),
            "plan": self.plan.to_dict(),
            "routing": {
                "policy_enabled": self.policy.enabled,
                "allow_explicit_execution": (
                    self.policy.allow_explicit_execution
                ),
                "requires_confirmation": (
                    self.requires_confirmation
                ),
                "can_auto_execute": self.can_auto_execute,
            },
        }


def _require_bool(
    data: Mapping[str, Any],
    name: str,
    default: bool,
) -> bool:
    value = data.get(name, default)

    if not isinstance(value, bool):
        raise ContextualRoutingError(
            f"{name} must be a boolean"
        )

    return value


def _read_permissions(
    data: Mapping[str, Any],
    name: str,
) -> tuple[str, ...]:
    value = data.get(name)

    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) for item in value)
    ):
        raise ContextualRoutingError(
            f"{name} must be a list of strings"
        )

    return tuple(value)


def parse_tool_routing_policy(
    data: Mapping[str, Any],
) -> ToolRoutingPolicy:
    """Parse and validate routing policy data."""

    if not isinstance(data, Mapping):
        raise TypeError(
            "routing policy data must be a mapping"
        )

    max_tool_steps = data.get("max_tool_steps", 8)

    if (
        not isinstance(max_tool_steps, int)
        or isinstance(max_tool_steps, bool)
    ):
        raise ContextualRoutingError(
            "max_tool_steps must be an integer"
        )

    return ToolRoutingPolicy(
        enabled=_require_bool(
            data,
            "enabled",
            False,
        ),
        allow_explicit_execution=_require_bool(
            data,
            "allow_explicit_execution",
            False,
        ),
        automatic_permissions=_read_permissions(
            data,
            "automatic_permissions",
        ),
        confirmation_permissions=_read_permissions(
            data,
            "confirmation_permissions",
        ),
        max_tool_steps=max_tool_steps,
        allow_arbitrary_tool_names=_require_bool(
            data,
            "allow_arbitrary_tool_names",
            False,
        ),
        allow_shell_generation=_require_bool(
            data,
            "allow_shell_generation",
            False,
        ),
        fail_closed=_require_bool(
            data,
            "fail_closed",
            True,
        ),
    )


def load_tool_routing_policy(
    source: Mapping[str, Any] | str | Path,
) -> ToolRoutingPolicy:
    """Load routing policy from a mapping or JSON file."""

    if isinstance(source, Mapping):
        return parse_tool_routing_policy(source)

    path = Path(source)

    if not path.is_file():
        raise ContextualRoutingError(
            f"routing policy does not exist: {path}"
        )

    try:
        content = path.read_text(encoding="utf-8-sig")
        data = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextualRoutingError(
            f"cannot read routing policy: {path}"
        ) from exc

    if not isinstance(data, Mapping):
        raise ContextualRoutingError(
            "routing policy root must be an object"
        )

    return parse_tool_routing_policy(data)


def route_contextual_request(
    text: str,
    registry: object,
    capability_config: Mapping[str, Any] | str | Path,
    policy_config: Mapping[str, Any] | str | Path,
    *,
    workspace: str | Path = ".",
    preview: bool = False,
) -> ContextualRouteResult:
    """
    Convert natural language into a validated execution plan.

    This function never invokes tools.
    """

    policy = load_tool_routing_policy(policy_config)

    if not policy.enabled and not preview:
        raise ContextualRoutingDisabled(
            "contextual tool routing is disabled"
        )

    analysis = analyze_intent(text)

    if not analysis.is_actionable:
        raise ContextualRoutingError(
            "request intent is not supported"
        )

    try:
        interpretation = interpret_task(analysis)

        catalog = build_tool_catalog(
            registry,
            capability_config,
        )

        plan = plan_tools(
            analysis,
            catalog,
            interpretation=interpretation,
            workspace=str(workspace),
            max_steps=policy.max_tool_steps,
        )
    except (
        TaskInterpretationError,
        ToolCatalogError,
        ToolPlanningError,
    ) as exc:
        raise ContextualRoutingError(str(exc)) from exc

    requires_confirmation = plan.requires_confirmation(
        policy.automatic_permissions
    )

    return ContextualRouteResult(
        analysis=analysis,
        interpretation=interpretation,
        plan=plan,
        policy=policy,
        requires_confirmation=requires_confirmation,
    )
