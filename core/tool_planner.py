from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Tuple

from core.execution_plan import ExecutionPlan, ToolCallStep
from core.intent_analyzer import IntentAnalysis, IntentType
from core.task_interpreter import TaskInterpretation, interpret_task
from core.tool_argument_builder import (
    ToolArgumentError,
    build_tool_arguments,
    validate_tool_arguments,
)


class ToolPlanningError(ValueError):
    """Raised when a safe execution plan cannot be constructed."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "planning_failed",
        capability: str = "",
        candidate_tool: str = "",
        missing_field: str = "",
        fallback_attempts: int = 0,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.capability = capability
        self.candidate_tool = candidate_tool
        self.missing_field = missing_field
        self.fallback_attempts = fallback_attempts


@dataclass(frozen=True)
class ToolDescriptor:
    """Minimal read-only description of a registered VEGA tool."""

    name: str
    permission: str
    capabilities: Tuple[str, ...]
    description: str = ""

    def __post_init__(self) -> None:
        name = self.name.strip()
        permission = self.permission.strip().upper()
        capabilities = tuple(
            capability.strip().lower()
            for capability in self.capabilities
            if capability.strip()
        )
        description = self.description.strip()

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "permission", permission)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "description", description)

        if not name:
            raise ToolPlanningError("tool name must not be empty")

        if not permission:
            raise ToolPlanningError(
                f"tool {name!r} must declare a permission"
            )

        if not capabilities:
            raise ToolPlanningError(
                f"tool {name!r} must declare at least one capability"
            )


_INTENT_ROUTES: Mapping[IntentType, Tuple[str, ...]] = {
    IntentType.DOCUMENT_ANALYSIS: (
        "document.read",
    ),
    IntentType.PROJECT_SEARCH: (
        "project.search",
    ),
    IntentType.WORKSPACE_DIAGNOSTICS: (
        "git.status",
        "test.run",
        "terminal.run",
    ),
    IntentType.TEST_RUN: (
        "test.run",
    ),
    IntentType.CODE_REVIEW: (
        "git.diff",
    ),
    IntentType.DOCUMENTATION_UPDATE: (
        "git.diff",
        "documentation.status",
    ),
    IntentType.RELEASE_CHECK: (
        "release.status",
    ),
}


def _build_capability_index(
    available_tools: Iterable[ToolDescriptor],
) -> dict[str, ToolDescriptor]:
    tools = tuple(available_tools)

    if not tools:
        raise ToolPlanningError(
            "available tool catalog must not be empty"
        )

    names: set[str] = set()
    capability_index: dict[str, ToolDescriptor] = {}

    for tool in sorted(tools, key=lambda item: item.name):
        if tool.name in names:
            raise ToolPlanningError(
                f"duplicate tool name in catalog: {tool.name}"
            )

        names.add(tool.name)

        for capability in tool.capabilities:
            capability_index.setdefault(capability, tool)

    return capability_index


def _resolve_required_capabilities(
    analysis: IntentAnalysis,
    interpretation: TaskInterpretation | None,
) -> Tuple[str, ...]:
    required_capabilities = _INTENT_ROUTES.get(
        analysis.intent
    )

    if required_capabilities is None:
        raise ToolPlanningError(
            f"no route is defined for intent: "
            f"{analysis.intent.value}"
        )

    if (
        analysis.intent is IntentType.CODE_REVIEW
        and interpretation is not None
        and "staged_only" in interpretation.constraints
    ):
        return ("git.diff.cached",)

    if (
        analysis.intent is IntentType.WORKSPACE_DIAGNOSTICS
        and interpretation is not None
    ):
        capabilities = ["git.status"]
        if interpretation.run_tests:
            capabilities.append("test.run")
        if interpretation.run_compileall:
            capabilities.append("terminal.run")
        return tuple(capabilities)

    return required_capabilities


def plan_tools(
    analysis: IntentAnalysis,
    available_tools: Iterable[ToolDescriptor],
    *,
    interpretation: TaskInterpretation | None = None,
    workspace: str = ".",
    max_steps: int = 8,
) -> ExecutionPlan:
    """Build a linear plan using only explicitly available tools."""

    if not isinstance(analysis, IntentAnalysis):
        raise TypeError(
            "analysis must be an IntentAnalysis instance"
        )

    if (
        interpretation is not None
        and not isinstance(
            interpretation,
            TaskInterpretation,
        )
    ):
        raise TypeError(
            "interpretation must be a "
            "TaskInterpretation instance"
        )

    if (
        interpretation is not None
        and interpretation.intent is not analysis.intent
    ):
        raise ToolPlanningError(
            "analysis and interpretation intents "
            "must match"
        )

    if not isinstance(workspace, str) or not workspace.strip():
        raise ToolPlanningError(
            "workspace must be a non-empty string"
        )

    if max_steps < 1:
        raise ToolPlanningError(
            "max_steps must be greater than zero"
        )

    if not analysis.is_actionable:
        raise ToolPlanningError(
            "cannot build a tool plan for an unknown intent"
        )

    if interpretation is None:
        interpretation = interpret_task(analysis)

    required_capabilities = (
        _resolve_required_capabilities(
            analysis,
            interpretation,
        )
    )

    capability_index = _build_capability_index(
        available_tools
    )

    missing_capabilities = tuple(
        capability
        for capability in required_capabilities
        if capability not in capability_index
    )

    if missing_capabilities:
        missing = ", ".join(missing_capabilities)
        raise ToolPlanningError(
            f"required capabilities are unavailable: {missing}"
        )

    steps: list[ToolCallStep] = []

    for index, capability in enumerate(
        required_capabilities,
        start=1,
    ):
        tool = capability_index[capability]
        dependencies = () if index == 1 else (index - 1,)

        try:
            arguments = build_tool_arguments(
                capability,
                interpretation,
                workspace=workspace,
            )
            validate_tool_arguments(capability, arguments)
        except ToolArgumentError as exc:
            raise ToolPlanningError(
                str(exc),
                reason_code=exc.reason_code,
                capability=capability,
                candidate_tool=tool.name,
                missing_field=exc.missing_field,
            ) from exc

        if interpretation is not None:
            if (
                not interpretation.allow_file_changes
                and tool.permission in {"WRITE", "DELETE", "ADMIN"}
            ):
                raise ToolPlanningError(
                    "plan violates the no-file-changes constraint",
                    reason_code="constraint_violation",
                    capability=capability,
                    candidate_tool=tool.name,
                )
            if (
                not interpretation.allow_network
                and capability.startswith("network.")
            ):
                raise ToolPlanningError(
                    "plan violates the no-network constraint",
                    reason_code="constraint_violation",
                    capability=capability,
                    candidate_tool=tool.name,
                )
            if (
                not interpretation.allow_dependency_installation
                and capability.startswith("dependency.")
            ):
                raise ToolPlanningError(
                    "plan violates the no-dependency-installation constraint",
                    reason_code="constraint_violation",
                    capability=capability,
                    candidate_tool=tool.name,
                )

        steps.append(
            ToolCallStep(
                step_id=index,
                tool_name=tool.name,
                arguments=arguments,
                required_permission=tool.permission,
                description=(
                    tool.description
                    or f"Use capability {capability}"
                ),
                depends_on=dependencies,
            )
        )

    return ExecutionPlan(
        goal=analysis.original_text,
        steps=tuple(steps),
        max_steps=max_steps,
        metadata={
            "intent": analysis.intent.value,
            "required_capabilities": tuple(required_capabilities),
            "confidence": analysis.confidence,
            "matched_signals": list(
                analysis.matched_signals
            ),
            "planner": "deterministic-capability-router",
        },
    )
