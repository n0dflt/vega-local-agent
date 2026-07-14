from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import time
from typing import Any

from core.context_budget import ContextBudgetResult, apply_context_budget
from core.contextual_response import format_plan_execution_response
from core.contextual_synthesis import (
    ContextualChatCallable,
    ContextualSynthesisRequest,
    ContextualSynthesisResult,
    ContextualSynthesisStatus,
    synthesize_contextual_result,
)
from core.contextual_router import (
    ContextualRouteResult,
    load_tool_routing_policy,
    route_contextual_request,
)
from core.execution_trace import (
    ExecutionTrace,
    TraceRecorder,
    TraceStatus,
    TraceStep,
)
from core.execution_progress import (
    ExecutionProgressEvent,
    ExecutionProgressStage,
)
from core.intent_analyzer import analyze_intent
from core.model_selection import (
    ModelSelectionDecision,
    load_model_routing_policy,
    select_model,
)
from core.plan_executor import (
    PlanExecutionResult,
    PlanExecutionStatus,
    StepExecutionObservation,
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
    execution_trace: ExecutionTrace | None = None

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
    trace_callback: Callable[[ExecutionTrace], object] | None = None,
    progress_callback: Callable[[ExecutionProgressEvent], object] | None = None,
    clock: Callable[[], float] = time.monotonic,
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

    try:
        started_at = float(clock())
    except Exception:
        started_at = 0.0

    def report_progress(event: ExecutionProgressEvent) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(event)
        except Exception:
            return

    def elapsed_seconds() -> float:
        try:
            return max(0.0, float(clock()) - started_at)
        except Exception:
            return 0.0

    def report_failure(title: str) -> None:
        report_progress(
            ExecutionProgressEvent(
                stage=ExecutionProgressStage.FAILED,
                title=title,
                elapsed_seconds=elapsed_seconds(),
            )
        )

    report_progress(
        ExecutionProgressEvent(stage=ExecutionProgressStage.RECEIVED)
    )

    recorder = TraceRecorder(request_type="contextual")

    def note_trace_recording_failure() -> None:
        try:
            recorder.record_error("trace_recording_failed")
        except Exception:
            return

    def finish_trace(
        status: TraceStatus,
        *error_codes: str,
    ) -> ExecutionTrace | None:
        try:
            trace = recorder.finalize(status, error_codes=tuple(error_codes))
        except Exception:
            return None
        if trace_callback is not None:
            try:
                trace_callback(trace)
            except Exception:
                return trace
        return trace

    if production_snapshot is not None:
        if not isinstance(production_snapshot, ProductionSnapshot):
            raise TypeError(
                "production_snapshot must be a ProductionSnapshot instance"
            )
        if not production_snapshot.can_execute_tools:
            report_failure("Выполнение заблокировано политикой безопасности")
            return ContextualRuntimeResult(
                status=ContextualRuntimeStatus.BLOCKED,
                message=_BLOCKED_MESSAGE,
                reason="production_snapshot_blocked",
                execution_trace=finish_trace(
                    TraceStatus.BLOCKED,
                    "production_snapshot_blocked",
                ),
            )
        registry = production_snapshot.tool_mapping
        capability_config = production_snapshot.tool_capabilities
        policy_config = production_snapshot.routing_policy
        model_policy_config = production_snapshot.model_routing_policy

    try:
        root = Path(project_root).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        report_failure("Не удалось проверить рабочую папку")
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.FAILED,
            message="Contextual runtime could not validate the project root.",
            reason="invalid_project_root",
            execution_trace=finish_trace(
                TraceStatus.FAILED,
                "invalid_project_root",
            ),
        )

    if not root.is_dir():
        report_failure("Не удалось проверить рабочую папку")
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.FAILED,
            message="Contextual runtime could not validate the project root.",
            reason="invalid_project_root",
            execution_trace=finish_trace(
                TraceStatus.FAILED,
                "invalid_project_root",
            ),
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
            execution_trace=finish_trace(
                TraceStatus.BLOCKED,
                "production_snapshot_blocked",
            ),
        )

    try:
        policy = load_tool_routing_policy(
            policy_config
        )
    except Exception:
        report_failure("Не удалось проверить правила маршрутизации")
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.FAILED,
            message="Contextual routing policy could not be validated.",
            reason="policy_error",
            execution_trace=finish_trace(
                TraceStatus.FAILED,
                "policy_error",
            ),
        )

    if not policy.enabled:
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.NOT_HANDLED,
            reason="disabled_by_policy",
        )

    report_progress(
        ExecutionProgressEvent(stage=ExecutionProgressStage.ANALYZING)
    )

    try:
        analysis = analyze_intent(normalized_text)
    except Exception:
        report_failure("Не удалось безопасно проанализировать запрос")
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.FAILED,
            message="The request could not be analyzed safely.",
            reason="intent_analysis_failed",
            execution_trace=finish_trace(
                TraceStatus.FAILED,
                "intent_analysis_failed",
            ),
        )

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
                execution_trace=finish_trace(
                    TraceStatus.BLOCKED,
                    "production_snapshot_blocked",
                ),
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
        try:
            from core.model_router import MODEL_PROFILES

            known_model = str(
                MODEL_PROFILES.get(model_decision.profile, {}).get("model", "")
            )
            safe_model = (
                known_model
                if known_model and known_model == model_decision.model
                else ("explicit_model" if model_decision.model else "")
            )
            recorder.record_model(
                profile=model_decision.profile,
                model=safe_model,
                reason_code=model_decision.reason_code,
                fallback_used=model_decision.fallback_used,
            )
        except Exception:
            note_trace_recording_failure()
    except Exception:
        report_failure("Не удалось выбрать модель")
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.FAILED,
            message="Model routing could not be validated.",
            reason="model_policy_error",
            execution_trace=finish_trace(
                TraceStatus.FAILED,
                "model_policy_error",
            ),
        )

    report_progress(
        ExecutionProgressEvent(stage=ExecutionProgressStage.PLANNING)
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
    except Exception:
        report_failure("Не удалось безопасно построить план")
        return ContextualRuntimeResult(
            status=ContextualRuntimeStatus.FAILED,
            message="The request could not be planned safely.",
            reason="routing_error",
            execution_trace=finish_trace(
                TraceStatus.FAILED,
                "routing_error",
            ),
        )

    permission_risks: dict[str, str] = {}
    domain = ""
    try:
        if production_snapshot is not None:
            permission_risks = {
                permission.tool_name: permission.risk
                for permission in production_snapshot.permissions
            }
            owners = tuple(
                item.name
                for item in production_snapshot.domains
                if item.enabled
                and route_result.analysis.intent.value in item.intents
            )
            if len(owners) == 1:
                domain = owners[0]
        required_capabilities = tuple(
            str(value)
            for value in route_result.plan.metadata.get(
                "required_capabilities",
                (),
            )
        )
        recorder.record_route(
            intent=route_result.analysis.intent.value,
            domain=domain,
            required_capabilities=required_capabilities,
            selected_tools=tuple(step.tool_name for step in route_result.plan.steps),
            confirmation_required=route_result.requires_confirmation,
        )
        recorder.record_permissions(
            tuple(
                (
                    "automatic"
                    if step.required_permission in policy.automatic_permissions
                    else "confirmation_required"
                )
                for step in route_result.plan.steps
            )
        )
    except Exception:
        permission_risks = {}
        note_trace_recording_failure()

    def observe_step(observation: StepExecutionObservation) -> None:
        try:
            recorder.record_step(
                TraceStep(
                    step_id=observation.step_id,
                    tool_name=observation.tool_name,
                    permission=observation.permission,
                    risk=observation.risk,
                    status=observation.status,
                    error_code=observation.error_code,
                )
            )
        except Exception:
            note_trace_recording_failure()

    execution_result = execute_plan(
        route_result.plan,
        tool_executor,
        automatic_permissions=(
            policy.automatic_permissions
        ),
        risk_by_tool=permission_risks,
        step_observer=observe_step,
        progress_callback=report_progress,
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

    try:
        deterministic_message = format_plan_execution_response(
            execution_result,
            intent=route_result.analysis.intent.value,
        )
    except Exception:
        deterministic_message = (
            "The controlled tool run finished, but its result could not be "
            "formatted safely."
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
        try:
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
                try:
                    recorder.record_context_budget(context_budget_result.metadata)
                except Exception:
                    note_trace_recording_failure()
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
                try:
                    recorder.record_synthesis(failed=not synthesis_result.ok)
                except Exception:
                    note_trace_recording_failure()
        except Exception:
            synthesis_result = ContextualSynthesisResult(
                ContextualSynthesisStatus.FAILED,
                reason="synthesis_failed",
            )
            try:
                recorder.record_synthesis(failed=True)
            except Exception:
                note_trace_recording_failure()

    message = (
        synthesis_result.response
        if synthesis_result is not None and synthesis_result.ok
        else deterministic_message
    )

    trace_status = {
        PlanExecutionStatus.COMPLETED: TraceStatus.COMPLETED,
        PlanExecutionStatus.BLOCKED: TraceStatus.BLOCKED,
        PlanExecutionStatus.FAILED: TraceStatus.FAILED,
    }[execution_result.status]
    execution_trace = finish_trace(trace_status)

    total_steps = len(route_result.plan.steps)
    if execution_result.status is PlanExecutionStatus.COMPLETED:
        report_progress(
            ExecutionProgressEvent(
                stage=ExecutionProgressStage.COMPLETED,
                current_step=total_steps,
                total_steps=total_steps,
                title="Готово",
                elapsed_seconds=elapsed_seconds(),
            )
        )
    elif not (
        execution_result.status is PlanExecutionStatus.BLOCKED
        and route_result.requires_confirmation
    ):
        current_step = 0
        if execution_result.blocked_step_id is not None:
            for position, step in enumerate(route_result.plan.steps, 1):
                if step.step_id == execution_result.blocked_step_id:
                    current_step = position
                    break
        report_progress(
            ExecutionProgressEvent(
                stage=ExecutionProgressStage.FAILED,
                current_step=current_step,
                total_steps=total_steps,
                title="Выполнение завершилось с ошибкой",
                elapsed_seconds=elapsed_seconds(),
            )
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
        execution_trace=execution_trace,
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
