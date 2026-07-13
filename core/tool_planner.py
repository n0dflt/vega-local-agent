from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Tuple

from core.execution_plan import ExecutionPlan, ToolCallStep
from core.intent_analyzer import IntentAnalysis, IntentType


class ToolPlanningError(ValueError):
    """Raised when a safe execution plan cannot be constructed."""


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
        "document.summarize",
    ),
    IntentType.PROJECT_SEARCH: (
        "project.search",
    ),
    IntentType.BUG_FIX: (
        "project.search",
        "patch.propose",
        "test.run",
    ),
    IntentType.TEST_RUN: (
        "test.run",
    ),
    IntentType.CODE_REVIEW: (
        "git.diff",
        "code.review",
    ),
    IntentType.DOCUMENTATION_UPDATE: (
        "git.diff",
        "documentation.update",
    ),
    IntentType.RELEASE_CHECK: (
        "release.check",
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


def plan_tools(
    analysis: IntentAnalysis,
    available_tools: Iterable[ToolDescriptor],
    *,
    max_steps: int = 8,
) -> ExecutionPlan:
    """Build a linear plan using only explicitly available tools."""

    if not isinstance(analysis, IntentAnalysis):
        raise TypeError(
            "analysis must be an IntentAnalysis instance"
        )

    if max_steps < 1:
        raise ToolPlanningError(
            "max_steps must be greater than zero"
        )

    if not analysis.is_actionable:
        raise ToolPlanningError(
            "cannot build a tool plan for an unknown intent"
        )

    required_capabilities = _INTENT_ROUTES.get(analysis.intent)

    if required_capabilities is None:
        raise ToolPlanningError(
            f"no route is defined for intent: "
            f"{analysis.intent.value}"
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

        steps.append(
            ToolCallStep(
                step_id=index,
                tool_name=tool.name,
                arguments={},
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
            "confidence": analysis.confidence,
            "matched_signals": list(
                analysis.matched_signals
            ),
            "planner": "deterministic-capability-router",
        },
    )
