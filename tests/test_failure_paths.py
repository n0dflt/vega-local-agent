from __future__ import annotations

from pathlib import Path

import core.contextual_runtime as runtime_module
from core.contextual_runtime import (
    ContextualRuntimeStatus,
    try_execute_contextual_request,
)
from core.execution_trace import TraceStatus, serialize_trace
from core.tool_executor import ToolExecutor


SEARCH_REQUEST = 'find "needle" in project'
DOCUMENT_REQUEST = 'analyze document "docs/report.md" and summarize it'


def policy() -> dict[str, object]:
    return {
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


def search_capabilities() -> dict[str, object]:
    return {
        "search_in_files": {
            "permission": "READ",
            "capabilities": ["project.search"],
        }
    }


def read_capabilities() -> dict[str, object]:
    return {
        "read_file": {
            "permission": "READ",
            "capabilities": ["document.read"],
        }
    }


def test_invalid_project_root_is_safe_and_terminal(tmp_path: Path) -> None:
    secret_root = tmp_path / "TOP-SECRET-ROOT"
    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        secret_root,
        ToolExecutor({"search_in_files": lambda **arguments: arguments}),
        registry={"search_in_files": lambda **arguments: arguments},
        capability_config=search_capabilities(),
        policy_config=policy(),
    )

    assert result.status is ContextualRuntimeStatus.FAILED
    assert result.reason == "invalid_project_root"
    assert str(secret_root) not in result.message
    assert result.execution_trace.status is TraceStatus.FAILED
    assert "invalid_project_root" in result.execution_trace.error_codes


def test_policy_failure_does_not_expose_raw_configuration(
    tmp_path: Path,
) -> None:
    unsafe_policy = policy()
    unsafe_policy["payload"] = "TOP-SECRET-POLICY"
    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor({"search_in_files": lambda **arguments: arguments}),
        registry={"search_in_files": lambda **arguments: arguments},
        capability_config=search_capabilities(),
        policy_config=unsafe_policy,
    )

    assert result.reason == "policy_error"
    assert result.message == "Contextual routing policy could not be validated."
    assert "TOP-SECRET" not in serialize_trace(result.execution_trace)


def test_intent_analysis_failure_is_stable_and_executes_nothing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[object] = []

    def fail_analysis(text):
        raise RuntimeError("TOP-SECRET-REQUEST")

    monkeypatch.setattr(runtime_module, "analyze_intent", fail_analysis)
    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor({"search_in_files": lambda **arguments: calls.append(arguments)}),
        registry={"search_in_files": lambda **arguments: calls.append(arguments)},
        capability_config=search_capabilities(),
        policy_config=policy(),
    )

    assert result.reason == "intent_analysis_failed"
    assert calls == []
    assert "TOP-SECRET" not in result.message
    assert result.execution_trace.error_codes == ("intent_analysis_failed",)


def test_model_policy_failure_is_stable_and_executes_nothing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[object] = []

    def fail_model_policy(source):
        raise RuntimeError("TOP-SECRET-MODEL-POLICY")

    monkeypatch.setattr(
        runtime_module,
        "load_model_routing_policy",
        fail_model_policy,
    )
    registry = {"search_in_files": lambda **arguments: calls.append(arguments)}
    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=search_capabilities(),
        policy_config=policy(),
    )

    assert result.reason == "model_policy_error"
    assert calls == []
    assert result.message == "Model routing could not be validated."
    assert "TOP-SECRET" not in serialize_trace(result.execution_trace)


def test_planning_failure_is_stable_and_executes_nothing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[object] = []

    def fail_route(*args, **kwargs):
        raise RuntimeError("TOP-SECRET-PLAN")

    monkeypatch.setattr(runtime_module, "route_contextual_request", fail_route)
    registry = {"search_in_files": lambda **arguments: calls.append(arguments)}
    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=search_capabilities(),
        policy_config=policy(),
        installed_models=(),
    )

    assert result.reason == "routing_error"
    assert calls == []
    assert result.message == (
        "VEGA could not build a valid plan from registered tools."
    )
    assert "TOP-SECRET" not in serialize_trace(result.execution_trace)


def test_tool_exception_executes_once_and_returns_safe_failure(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fail_tool(**arguments):
        calls.append("called")
        raise RuntimeError("TOP-SECRET-TOOL-RESULT")

    registry = {"search_in_files": fail_tool}
    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=search_capabilities(),
        policy_config=policy(),
    )

    assert result.status is ContextualRuntimeStatus.FAILED
    assert calls == ["called"]
    assert result.execution_result.steps[0].error_code == "tool_execution_failed"
    assert "TOP-SECRET" not in result.message
    assert "TOP-SECRET" not in serialize_trace(result.execution_trace)


def test_unavailable_explicit_model_skips_synthesis_deterministically(
    tmp_path: Path,
) -> None:
    model_calls: list[object] = []
    registry = {
        "read_file": lambda path: {
            "ok": True,
            "error": None,
            "data": {"path": path, "text": "safe evidence"},
        }
    }
    result = try_execute_contextual_request(
        DOCUMENT_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=read_capabilities(),
        policy_config=policy(),
        chat_callable=lambda model, messages: model_calls.append(messages),
        model="missing:model",
        installed_models=(),
    )

    assert result.ok
    assert not result.model_decision.available
    assert result.model_decision.reason_code == "explicit_model_unavailable"
    assert model_calls == []
    assert "safe evidence" in result.message


def test_synthesis_exception_preserves_success_and_redacts_reason(
    tmp_path: Path,
) -> None:
    registry = {
        "read_file": lambda path: {
            "ok": True,
            "error": None,
            "data": {"path": path, "text": "safe evidence"},
        }
    }

    def fail_chat(model, messages):
        raise RuntimeError("TOP-SECRET-MODEL-FAILURE")

    result = try_execute_contextual_request(
        DOCUMENT_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=read_capabilities(),
        policy_config=policy(),
        chat_callable=fail_chat,
        model="installed:model",
        installed_models=("installed:model",),
    )

    assert result.ok
    assert result.synthesis_result.reason == "model_call_failed"
    assert "safe evidence" in result.message
    assert result.execution_trace.status is TraceStatus.COMPLETED
    assert result.execution_trace.error_codes == ("synthesis_failed",)
    assert "TOP-SECRET" not in serialize_trace(result.execution_trace)
