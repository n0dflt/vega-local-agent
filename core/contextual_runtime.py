from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from core.context_budget import ContextBudgetResult, apply_context_budget
from core.contextual_response import format_plan_execution_response
from core.contextual_synthesis import (
    ContextualChatCallable,
    ContextualSynthesisRequest,
    ContextualSynthesisResult,
    synthesize_contextual_result,
)
from core.contextual_router import (
    ContextualRouteResult,
    ContextualRoutingError,
    load_tool_routing_policy,
    route_contextual_request,
)
from core.intent_analyzer import analyze_intent
from core.model_selection import (
    ModelRoutingPolicyError,
    ModelSelectionDecision,
    load_model_routing_policy,
    select_model,
)
from core.plan_executor import (
    PlanExecutionResult,
    PlanExecutionStatus,
    execute_plan,
)
from core.production_snapshot import ProductionSnapshot
from core.tool_executor import ToolExecutor


_BLOCKED_MESSAGE = "Contextual tool execution is blocked by production policy."


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
    synthesis_result: ContextualSynthesisResult | None = None
    model_decision: ModelSelectionDecision | None = None
    context_budget_result: ContextBudgetResult | None = None

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
    chat_callable: ContextualChatCallable | None = None,
    model: str = "",
    model_policy_config: (
        Mapping[str, Any] | str | Path | None
    ) = None,
    installed_models: Sequence[str] | None = None,
    production_snapshot: ProductionSnapshot | None = None,
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

    if production_snapshot is not None:
        if not isinstance(production_snapshot, ProductionSnapshot):
            raise TypeError(
                "production_snapshot must be a ProductionSnapshot instance"
            )
        if not production_snapshot.can_execute_tools:
            return ContextualRuntimeResult(
                status=ContextualRuntimeStatus.BLOCKED,
                message=_BLOCKED_MESSAGE,
                reason="production_snapshot_blocked",
            )
        registry = production_snapshot.tool_mapping
        capability_config = production_snapshot.tool_capabilities
        policy_config = production_snapshot.routing_policy
        model_policy_config = production_snapshot.model_routing_policy

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

    if policy_config is None:
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.BLOCKED,
            message=_BLOCKED_MESSAGE,
            reason="production_snapshot_blocked",
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

    if model_policy_config is None:
        project_policy = root / "config" / "model_routing_policy.json"
        model_policy_config = (
            project_policy
            if project_policy.is_file()
            else Path(__file__).resolve().parents[1]
            / "config"
            / "model_routing_policy.json"
        )

    try:
        if model_policy_config is None:
            return ContextualRuntimeResult(
                status=ContextualRuntimeStatus.BLOCKED,
                message=_BLOCKED_MESSAGE,
                reason="production_snapshot_blocked",
            )
        model_policy = load_model_routing_policy(model_policy_config)
        from core.model_router import (
            get_current_profile,
            get_installed_ollama_models,
            get_selection_mode,
        )

        current_profile = get_current_profile(root)["name"]
        selection_mode = get_selection_mode(root)
        available_models = (
            tuple(installed_models)
            if installed_models is not None
            else (
                ()
                if model.strip()
                else tuple(get_installed_ollama_models())
            )
        )
        model_decision = select_model(
            analysis.intent,
            model_policy,
            available_models,
            selection_mode=selection_mode,
            current_profile=current_profile,
            explicit_model=model,
            request_text=normalized_text,
        )
    except (ModelRoutingPolicyError, OSError, TypeError, ValueError) as exc:
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.FAILED,
            message=f"Contextual runtime error: {exc}",
            reason="model_policy_error",
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

    deterministic_message = format_plan_execution_response(
        execution_result,
        intent=route_result.analysis.intent.value,
    )
    synthesis_result = None
    context_budget_result = None

    if (
        execution_result.status is PlanExecutionStatus.COMPLETED
        and chat_callable is not None
        and model_decision.available
        and model_decision.model
        and route_result.analysis.intent.value
        in {"document_analysis", "code_review"}
        and execution_result.steps
    ):
        step = execution_result.steps[-1]
        evidence = _extract_synthesis_evidence(
            step.tool_name,
            step.data,
        )
        if evidence:
            budget_profile = (
                model_decision.profile
                if model_decision.profile in model_policy.context_budgets
                else model_policy.fallback_profile
            )
            context_budget_result = apply_context_budget(
                evidence,
                model_policy.context_budgets[budget_profile],
                head_ratio=model_policy.head_ratio,
            )
            synthesis_result = synthesize_contextual_result(
                ContextualSynthesisRequest(
                    original_request=normalized_text,
                    intent=route_result.analysis.intent.value,
                    tool_name=step.tool_name,
                    evidence=context_budget_result.evidence,
                ),
                model=model_decision.model,
                chat=chat_callable,
            )

    message = (
        synthesis_result.response
        if synthesis_result is not None and synthesis_result.ok
        else deterministic_message
    )

    return ContextualRuntimeResult(
        status=status_map[execution_result.status],
        message=message,
        reason=execution_result.status.value,
        route_result=route_result,
        execution_result=execution_result,
        synthesis_result=synthesis_result,
        model_decision=model_decision,
        context_budget_result=context_budget_result,
    )


def _extract_synthesis_evidence(
    tool_name: str,
    value: Any,
) -> str:
    data = value
    if isinstance(data, Mapping) and "ok" in data and "data" in data:
        if data.get("ok") is False:
            return ""
        data = data.get("data")

    if tool_name == "read_file":
        if not isinstance(data, Mapping):
            return ""
        return str(data.get("text", "")).strip()

    if tool_name in {"git_diff", "git_diff_cached"}:
        if isinstance(data, Mapping):
            stdout = data.get("stdout", "")
        else:
            stdout = getattr(data, "stdout", "")
        return str(stdout or "").strip()

    return ""


__all__ = [
    "ContextualRuntimeResult",
    "ContextualRuntimeStatus",
    "try_execute_contextual_request",
]
