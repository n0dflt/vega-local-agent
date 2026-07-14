from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import core.production_runtime as runtime_module
from core.policy_consistency import (
    PolicyConsistencyIssue,
    PolicyConsistencyReport,
    PolicyIssueCode,
    PolicyIssueSeverity,
)
from core.production_runtime import (
    ProductionRuntimeBootstrap,
    build_production_runtime,
)
from core.production_snapshot import ProductionSnapshot, build_production_snapshot
from core.contextual_runtime import ContextualRuntimeStatus, try_execute_contextual_request
from core.tool_executor import ToolExecutionStatus, ToolExecutor, ToolRequest
from permissions.session_grants import SessionGrantStore


ROOT = Path(__file__).resolve().parents[1]


def make_snapshot(
    *severities: PolicyIssueSeverity,
) -> ProductionSnapshot:
    issues = tuple(
        PolicyConsistencyIssue(
            code=PolicyIssueCode.CONFIGURATION_ERROR,
            severity=severity,
            layer="test",
            subject=f"issue_{index}",
        )
        for index, severity in enumerate(severities)
    )
    baseline = build_production_snapshot(ROOT)
    return replace(
        baseline,
        consistency_report=PolicyConsistencyReport(issues),
        tool_mapping={"sentinel": lambda: "called"} if not any(
            severity is PolicyIssueSeverity.FATAL for severity in severities
        ) else {},
    )


def patch_builders(monkeypatch, snapshot: ProductionSnapshot):
    store = SessionGrantStore()
    executor = ToolExecutor({"sentinel": lambda: "called"})
    calls = {"snapshot": 0, "grants": 0, "executor": 0}

    def build_snapshot(project_root):
        assert project_root == ROOT
        calls["snapshot"] += 1
        return snapshot

    def build_grants(permission_policy):
        assert permission_policy is snapshot.permission_policy
        calls["grants"] += 1
        return store

    def build_executor(session_grants, *, registry, permission_policy):
        assert session_grants is store
        assert dict(registry) == dict(snapshot.tool_mapping)
        assert permission_policy is snapshot.permission_policy
        calls["executor"] += 1
        return executor

    monkeypatch.setattr(runtime_module, "build_production_snapshot", build_snapshot)
    monkeypatch.setattr(runtime_module, "build_production_session_grants", build_grants)
    monkeypatch.setattr(runtime_module, "build_production_tool_executor", build_executor)
    return calls, store, executor


def test_enabled_runtime_uses_normal_builders(monkeypatch) -> None:
    calls, store, executor = patch_builders(monkeypatch, make_snapshot())

    runtime = build_production_runtime(ROOT)

    assert runtime.can_execute_tools
    assert runtime.status == "Ready"
    assert runtime.session_grants is store
    assert runtime.tool_executor is executor
    assert calls == {"snapshot": 1, "grants": 1, "executor": 1}


@pytest.mark.parametrize(
    ("severities", "status"),
    [
        ((PolicyIssueSeverity.DEGRADED,), "Degraded"),
        ((PolicyIssueSeverity.WARNING,), "Ready"),
        (
            (PolicyIssueSeverity.DEGRADED, PolicyIssueSeverity.WARNING),
            "Degraded",
        ),
    ],
)
def test_degraded_and_warning_issues_do_not_block_tools(
    monkeypatch,
    severities,
    status,
) -> None:
    calls, _, executor = patch_builders(monkeypatch, make_snapshot(*severities))

    runtime = build_production_runtime(ROOT)

    assert runtime.can_execute_tools
    assert runtime.status == status
    assert runtime.tool_executor is executor
    assert calls == {"snapshot": 1, "grants": 1, "executor": 1}


def test_fatal_snapshot_blocks_without_calling_normal_builders(monkeypatch) -> None:
    calls, _, normal_executor = patch_builders(
        monkeypatch,
        make_snapshot(PolicyIssueSeverity.FATAL),
    )

    runtime = build_production_runtime(ROOT)

    assert not runtime.can_execute_tools
    assert runtime.status == "Blocked"
    assert runtime.tool_executor is not normal_executor
    assert isinstance(runtime.session_grants, SessionGrantStore)
    assert calls == {"snapshot": 1, "grants": 0, "executor": 0}


def test_blocked_executor_never_invokes_a_registered_callable(monkeypatch) -> None:
    called = []
    calls, _, _ = patch_builders(
        monkeypatch,
        make_snapshot(PolicyIssueSeverity.FATAL),
    )
    monkeypatch.setattr(
        runtime_module,
        "build_production_tool_executor",
        lambda *args, **kwargs: ToolExecutor(
            {"sentinel": lambda: called.append(True)}
        ),
    )

    runtime = build_production_runtime(ROOT)
    result = runtime.tool_executor.execute(ToolRequest("sentinel"))

    assert result.status is ToolExecutionStatus.FAILED
    assert result.error_code == "production_snapshot_blocked"
    assert result.error == "Tool execution is blocked by production policy."
    assert called == []
    assert calls["snapshot"] == 1
    assert calls["grants"] == 0


def test_blocked_executor_fails_every_valid_request(monkeypatch) -> None:
    patch_builders(monkeypatch, make_snapshot(PolicyIssueSeverity.FATAL))
    executor = build_production_runtime(ROOT).tool_executor

    first = executor.execute(ToolRequest("known", {"value": 1}))
    second = executor.execute_named("missing")

    assert first.status is ToolExecutionStatus.FAILED
    assert second.status is ToolExecutionStatus.FAILED
    assert first.error_code == second.error_code == "production_snapshot_blocked"


def test_snapshot_builder_is_called_exactly_once(monkeypatch) -> None:
    calls, _, _ = patch_builders(monkeypatch, make_snapshot())

    build_production_runtime(ROOT)

    assert calls["snapshot"] == 1


def test_executor_builder_error_becomes_safe_fatal_report(monkeypatch) -> None:
    secret = "TOP-SECRET-runtime-builder-value"
    calls, store, _ = patch_builders(monkeypatch, make_snapshot())

    def fail_executor(session_grants, **kwargs):
        assert session_grants is store
        calls["executor"] += 1
        raise RuntimeError(secret)

    monkeypatch.setattr(runtime_module, "build_production_tool_executor", fail_executor)

    runtime = build_production_runtime(ROOT)
    safe_output = repr(runtime.snapshot.consistency_report.to_safe_dict())

    assert not runtime.can_execute_tools
    assert runtime.status == "Blocked"
    assert runtime.session_grants is store
    assert runtime.snapshot.consistency_report.fatal_issues
    assert runtime.snapshot.consistency_report.summary == (
        "fatal=1; degraded=0; warning=0"
    )
    assert dict(runtime.snapshot.tool_mapping) == {}
    assert dict(runtime.snapshot.tool_capabilities) == {}
    assert "RuntimeError" in safe_output
    assert secret not in safe_output
    assert secret not in repr(runtime)
    assert calls == {"snapshot": 1, "grants": 1, "executor": 1}


def test_bootstrap_dataclass_is_frozen(monkeypatch) -> None:
    patch_builders(monkeypatch, make_snapshot())
    runtime = build_production_runtime(ROOT)

    assert isinstance(runtime, ProductionRuntimeBootstrap)
    with pytest.raises(FrozenInstanceError):
        runtime.tool_executor = ToolExecutor({})


def test_build_requires_path() -> None:
    with pytest.raises(TypeError, match="pathlib.Path"):
        build_production_runtime(str(ROOT))


def test_real_runtime_publishes_exact_snapshot_mapping() -> None:
    runtime = build_production_runtime(ROOT)

    assert runtime.can_execute_tools
    assert runtime.tool_executor.registered_tools() == tuple(
        sorted(runtime.snapshot.tool_mapping)
    )


def test_contextual_runtime_uses_snapshot_instead_of_caller_registry() -> None:
    runtime = build_production_runtime(ROOT)

    result = try_execute_contextual_request(
        '\u041d\u0430\u0439\u0434\u0438 "snapshot-only-needle" \u0432 \u043f\u0440\u043e\u0435\u043a\u0442\u0435',
        ROOT,
        runtime.tool_executor,
        registry={"poison": lambda: None},
        capability_config={},
        policy_config={"enabled": False},
        model="test-model",
        production_snapshot=runtime.snapshot,
    )

    assert result.status is ContextualRuntimeStatus.COMPLETED
    assert result.route_result is not None
    assert result.route_result.plan.steps[0].tool_name == "search_in_files"


def test_blocked_snapshot_stops_contextual_routing(monkeypatch) -> None:
    called: list[bool] = []
    snapshot = make_snapshot(PolicyIssueSeverity.FATAL)
    monkeypatch.setattr(
        "core.contextual_runtime.route_contextual_request",
        lambda *args, **kwargs: called.append(True),
    )

    result = try_execute_contextual_request(
        "Find anything in the project",
        ROOT,
        ToolExecutor({}),
        production_snapshot=snapshot,
    )

    assert result.status is ContextualRuntimeStatus.BLOCKED
    assert result.reason == "production_snapshot_blocked"
    assert called == []
