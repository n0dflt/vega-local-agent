from __future__ import annotations

from pathlib import Path

from core.contextual_runtime import (
    ContextualRuntimeStatus,
    try_execute_contextual_request,
)
from core.execution_trace import TraceStatus
from core.model_router import MODEL_PROFILES
from core.production_snapshot import build_production_snapshot
from core.tool_executor import ToolExecutor
from core.tool_planner import _INTENT_ROUTES


ROOT = Path(__file__).resolve().parents[1]


def test_real_production_snapshot_has_no_blocking_consistency_issues() -> None:
    snapshot = build_production_snapshot(ROOT)

    assert snapshot.can_execute_tools
    assert snapshot.consistency_report.fatal_issues == ()
    assert snapshot.consistency_report.degraded_issues == ()
    assert snapshot.consistency_report.warnings == ()
    assert snapshot.consistency_report.summary == "fatal=0; degraded=0; warning=0"


def test_every_contextual_intent_has_one_complete_cross_layer_route() -> None:
    snapshot = build_production_snapshot(ROOT)
    tools = tuple(snapshot.tools)
    permissions = {item.tool_name: item for item in snapshot.permissions}
    model_policy = snapshot.model_routing_policy
    inactive = {
        issue.subject for issue in snapshot.consistency_report.warnings
    }

    assert model_policy is not None
    for intent, required_capabilities in _INTENT_ROUTES.items():
        intent_name = intent.value
        owners = tuple(
            domain
            for domain in snapshot.domains
            if domain.enabled and intent_name in domain.intents
        )
        assert len(owners) == 1, intent_name

        profile = model_policy.intent_profiles[intent_name]
        assert profile in MODEL_PROFILES
        assert model_policy.context_budgets[profile] > 0

        if intent_name in inactive:
            continue

        for capability in required_capabilities:
            assert capability in owners[0].capabilities
            candidates = tuple(
                tool
                for tool in tools
                if tool.contextual and capability in tool.capabilities
            )
            assert len(candidates) == 1, (intent_name, capability)
            assert candidates[0].name in snapshot.tool_mapping
            assert candidates[0].name in permissions


def test_confirmation_route_blocks_before_handler_invocation(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    registry = {"test_run": lambda: calls.append("test_run")}
    policy = {
        "schema_version": 1,
        "enabled": True,
        "allow_explicit_execution": True,
        "automatic_permissions": ["READ", "DRAFT"],
        "confirmation_permissions": [
            "WRITE",
            "EXECUTE",
            "SEND",
            "DELETE",
            "ADMIN",
        ],
        "max_tool_steps": 8,
        "allow_arbitrary_tool_names": False,
        "allow_shell_generation": False,
        "fail_closed": True,
    }
    result = try_execute_contextual_request(
        "run pytest tests",
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config={
            "test_run": {
                "permission": "EXECUTE",
                "capabilities": ["test.run"],
            }
        },
        policy_config=policy,
        installed_models=(),
    )

    assert result.status is ContextualRuntimeStatus.BLOCKED
    assert calls == []
    assert result.route_result.requires_confirmation
    assert result.execution_trace.status is TraceStatus.BLOCKED
    assert result.execution_trace.confirmation_required
    assert result.execution_trace.permission_outcomes == (
        "confirmation_required",
    )
