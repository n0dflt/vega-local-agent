from pathlib import Path

from core.contextual_runtime import (
    ContextualRuntimeStatus,
    try_execute_contextual_request,
)
from core.execution_progress import ExecutionProgressStage
from core.execution_trace import (
    TraceStatus,
    append_trace,
    load_latest_trace,
)
from core.tool_executor import ToolExecutor


SEARCH_REQUEST = (
    "\u041d\u0430\u0439\u0434\u0438 "
    '"legacy_client" '
    "\u0432 "
    "\u043f\u0440\u043e\u0435\u043a\u0442\u0435"
)

DOCUMENT_REQUEST_WITHOUT_PATH = (
    "\u041f\u0440\u043e\u0430\u043d\u0430"
    "\u043b\u0438\u0437\u0438\u0440\u0443\u0439 "
    "\u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442 "
    "\u0438 "
    "\u0441\u0434\u0435\u043b\u0430\u0439 "
    "\u043a\u0440\u0430\u0442\u043a\u0438\u0439 "
    "\u043e\u0442\u0447\u0451\u0442"
)


def _policy(
    *,
    enabled: bool,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "enabled": enabled,
        "allow_explicit_execution": True,
        "automatic_permissions": [
            "READ",
            "DRAFT",
        ],
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


def _search_capabilities(
    permission: str = "READ",
) -> dict[str, object]:
    return {
        "search_in_files": {
            "permission": permission,
            "capabilities": [
                "project.search",
            ],
        },
    }


def test_disabled_policy_falls_back_to_chat(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    registry = {
        "search_in_files": (
            lambda **arguments: calls.append(arguments)
        ),
    }

    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(enabled=False),
    )

    assert result.status is (
        ContextualRuntimeStatus.NOT_HANDLED
    )
    assert result.handled is False
    assert result.reason == "disabled_by_policy"
    assert calls == []


def test_unknown_intent_falls_back_to_chat(
    tmp_path: Path,
) -> None:
    traces: list[object] = []
    registry = {
        "search_in_files": (
            lambda **arguments: arguments
        ),
    }

    result = try_execute_contextual_request(
        "Tell me a joke",
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(enabled=True),
        trace_callback=traces.append,
    )

    assert result.status is (
        ContextualRuntimeStatus.NOT_HANDLED
    )
    assert result.reason == "unsupported_intent"
    assert result.execution_trace is None
    assert traces == []


def test_enabled_safe_request_executes_tool(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def search_in_files(
        query: str,
        path: str = ".",
        max_results: int = 20,
    ) -> dict[str, object]:
        calls.append(
            {
                "query": query,
                "path": path,
                "max_results": max_results,
            }
        )

        return {
            "ok": True,
            "error": None,
            "data": {
                "results": [],
            },
        }

    registry = {
        "search_in_files": search_in_files,
    }

    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(enabled=True),
    )

    assert result.status is (
        ContextualRuntimeStatus.COMPLETED
    )
    assert result.handled is True
    assert result.ok is True
    assert len(calls) == 1
    assert calls[0]["query"] == "legacy_client"
    assert calls[0]["path"] == "."
    assert "No matches found." in result.message
    assert result.execution_trace is not None
    assert result.execution_trace.status is TraceStatus.COMPLETED
    assert result.execution_trace.selected_tools == ("search_in_files",)


def test_tool_reported_failure_does_not_fall_back(
    tmp_path: Path,
) -> None:
    registry = {
        "search_in_files": (
            lambda **arguments: {
                "ok": False,
                "error": "search failed",
                "data": None,
            }
        ),
    }

    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(enabled=True),
    )

    assert result.status is (
        ContextualRuntimeStatus.FAILED
    )
    assert result.handled is True
    assert "Tool reported an unsuccessful result." in result.message
    assert result.execution_trace is not None
    assert result.execution_trace.status is TraceStatus.FAILED
    assert "tool_reported_failure" in result.execution_trace.error_codes


def test_test_run_failure_surfaces_specific_safe_reason(tmp_path: Path) -> None:
    diagnostics = {
        "tool": "test_run",
        "command_id": "tests",
        "group_id": "all",
        "reason_code": "test_failure",
    }
    registry = {
        "test_run": lambda **arguments: {
            "ok": False,
            "error": None,
            "reason_code": "test_failure",
            "diagnostics": diagnostics,
            "data": {
                "returncode": 1,
                "diagnostics": diagnostics,
            },
        },
    }

    result = try_execute_contextual_request(
        "run full pytest tests",
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config={
            "test_run": {
                "permission": "READ",
                "capabilities": ["test.run"],
            },
        },
        policy_config=_policy(enabled=True),
    )

    assert result.status is ContextualRuntimeStatus.FAILED
    assert "Test suite failed with exit code 1." in result.message
    assert result.execution_trace is not None
    assert "test_failure" in result.execution_trace.error_codes


def test_nonautomatic_permission_is_blocked(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    registry = {
        "search_in_files": (
            lambda **arguments: calls.append(arguments)
        ),
    }

    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=_search_capabilities(
            permission="WRITE"
        ),
        policy_config=_policy(enabled=True),
    )

    assert result.status is (
        ContextualRuntimeStatus.BLOCKED
    )
    assert result.handled is True
    assert "WRITE" in result.message
    assert calls == []
    assert result.execution_trace is not None
    assert result.execution_trace.status is TraceStatus.BLOCKED
    assert "permission_not_automatic" in result.execution_trace.error_codes


def test_actionable_invalid_request_does_not_fall_back(
    tmp_path: Path,
) -> None:
    registry = {
        "read_file": lambda **arguments: arguments,
        "summarize_file": (
            lambda **arguments: arguments
        ),
    }

    capabilities = {
        "read_file": {
            "permission": "READ",
            "capabilities": ["document.read"],
        },
        "summarize_file": {
            "permission": "READ",
            "capabilities": [
                "document.summarize",
            ],
        },
    }

    result = try_execute_contextual_request(
        DOCUMENT_REQUEST_WITHOUT_PATH,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=capabilities,
        policy_config=_policy(enabled=True),
    )

    assert result.status is (
        ContextualRuntimeStatus.FAILED
    )
    assert result.handled is True
    assert result.message == (
        "VEGA rejected the generated plan because a required tool "
        "argument was missing."
    )
    assert result.planning_diagnostics == {
        "intent": "document_analysis",
        "candidate_tool": "read_file",
        "rejection_reason": "missing_required_argument",
        "missing_field": "path",
        "fallback_attempts": 0,
        "final_planning_status": "failed",
    }


def test_document_analysis_synthesizes_real_read_content(tmp_path: Path) -> None:
    calls = []
    registry = {
        "read_file": lambda path: {
            "ok": True,
            "error": None,
            "data": {
                "path": path,
                "size": 18,
                "truncated": False,
                "text": "Important evidence",
            },
        }
    }
    capabilities = {
        "read_file": {
            "permission": "READ",
            "capabilities": ["document.read"],
        }
    }

    def chat(model, messages):
        calls.append((model, messages))
        return True, "Synthesized document answer"

    result = try_execute_contextual_request(
        'Проанализируй "docs/report.md" и сделай краткий отчёт',
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=capabilities,
        policy_config=_policy(enabled=True),
        chat_callable=chat,
        model="local-model",
        installed_models=("local-model",),
    )
    assert result.message == "Synthesized document answer"
    assert len(calls) == 1
    assert "Important evidence" in calls[0][1][1]["content"]
    assert result.execution_result.steps[0].tool_name == "read_file"


def test_code_review_synthesizes_nonempty_diff_once(tmp_path: Path) -> None:
    calls = []
    registry = {
        "git_diff": lambda workspace: {
            "stdout": "diff --git a/core/a.py b/core/a.py\n+safe change",
            "stderr": "",
            "returncode": 0,
        }
    }
    capabilities = {
        "git_diff": {
            "permission": "READ",
            "capabilities": ["git.diff"],
        }
    }
    result = try_execute_contextual_request(
        "Посмотри изменения и оцени риски",
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=capabilities,
        policy_config=_policy(enabled=True),
        chat_callable=lambda model, messages: calls.append(messages) or (True, "Review answer"),
        model="local-model",
        installed_models=("local-model",),
    )
    assert result.message == "Review answer"
    assert len(calls) == 1


def test_empty_diff_and_project_search_do_not_synthesize(tmp_path: Path) -> None:
    calls = []
    git_registry = {
        "git_diff": lambda workspace: {
            "stdout": "",
            "stderr": "",
            "returncode": 0,
        }
    }
    git_capabilities = {
        "git_diff": {"permission": "READ", "capabilities": ["git.diff"]}
    }
    empty = try_execute_contextual_request(
        "Посмотри изменения и оцени риски",
        tmp_path,
        ToolExecutor(git_registry),
        registry=git_registry,
        capability_config=git_capabilities,
        policy_config=_policy(enabled=True),
        chat_callable=lambda model, messages: calls.append(messages) or (True, "bad"),
        model="local-model",
        installed_models=("local-model",),
    )
    assert empty.message == "No unstaged changes."

    search_registry = {"search_in_files": lambda **arguments: {"ok": True, "error": None, "data": []}}
    search = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(search_registry),
        registry=search_registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(enabled=True),
        chat_callable=lambda model, messages: calls.append(messages) or (True, "bad"),
        model="local-model",
        installed_models=("local-model",),
    )
    assert search.message == "No matches found."
    assert calls == []


def test_synthesis_failure_preserves_deterministic_success(tmp_path: Path) -> None:
    registry = {
        "read_file": lambda path: {
            "ok": True,
            "error": None,
            "data": {"path": path, "size": 8, "truncated": False, "text": "Evidence"},
        }
    }
    capabilities = {"read_file": {"permission": "READ", "capabilities": ["document.read"]}}
    result = try_execute_contextual_request(
        'Проанализируй "docs/report.md" и сделай краткий отчёт',
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=capabilities,
        policy_config=_policy(enabled=True),
        chat_callable=lambda model, messages: (False, "offline"),
        model="local-model",
        installed_models=("local-model",),
    )
    assert result.ok
    assert "Evidence" in result.message
    assert result.synthesis_result is not None
    assert not result.synthesis_result.ok
    assert result.execution_trace is not None
    assert result.execution_trace.status is TraceStatus.COMPLETED
    assert "synthesis_failed" in result.execution_trace.error_codes


def test_trace_persistence_failure_does_not_change_successful_response(
    tmp_path: Path,
) -> None:
    calls: list[object] = []
    registry = {
        "search_in_files": lambda **arguments: {
            "ok": True,
            "error": None,
            "data": {"results": []},
        }
    }

    def fail(trace) -> None:
        calls.append(trace)
        raise RuntimeError("TOP-SECRET-TRACE")

    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(enabled=True),
        trace_callback=fail,
    )

    assert result.ok
    assert len(calls) == 1
    assert result.execution_trace is calls[0]
    assert "TOP-SECRET-TRACE" not in repr(result.execution_trace)


def test_real_contextual_trace_persists_only_safe_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VEGA_EXECUTION_TRACE", "1")
    registry = {
        "search_in_files": lambda **arguments: {
            "ok": True,
            "error": None,
            "data": {"results": ["EVIDENCE-CONTENT-SECRET"]},
        }
    }

    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(enabled=True),
        trace_callback=lambda trace: append_trace(tmp_path, trace),
    )
    latest = load_latest_trace(tmp_path)

    assert result.ok
    assert latest == result.execution_trace
    persisted = (tmp_path / "logs/diagnostics/execution-traces.jsonl").read_text(
        encoding="utf-8"
    )
    assert "EVIDENCE-CONTENT-SECRET" not in persisted
    assert "legacy_client" not in persisted


def test_contextual_progress_covers_analysis_plan_and_completion(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    events = []
    times = iter((10.0, 12.5))
    registry = {
        "search_in_files": lambda **arguments: calls.append("search") or {
            "ok": True,
            "error": None,
            "data": {"results": []},
        }
    }

    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(enabled=True),
        progress_callback=events.append,
        clock=lambda: next(times),
    )

    assert result.ok
    assert calls == ["search"]
    assert [event.stage for event in events] == [
        ExecutionProgressStage.RECEIVED,
        ExecutionProgressStage.ANALYZING,
        ExecutionProgressStage.PLANNING,
        ExecutionProgressStage.PLAN_READY,
        ExecutionProgressStage.STEP_RUNNING,
        ExecutionProgressStage.STEP_COMPLETED,
        ExecutionProgressStage.COMPLETED,
    ]
    assert events[-1].elapsed_seconds == 2.5


def test_contextual_failure_reports_step_failed_then_failed(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    events = []
    registry = {
        "search_in_files": lambda **arguments: calls.append("search") or {
            "ok": False,
            "error": "TOP-SECRET-DETAIL",
            "data": None,
        }
    }

    result = try_execute_contextual_request(
        SEARCH_REQUEST,
        tmp_path,
        ToolExecutor(registry),
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(enabled=True),
        progress_callback=events.append,
    )

    assert result.status is ContextualRuntimeStatus.FAILED
    assert calls == ["search"]
    assert events[-2].stage is ExecutionProgressStage.STEP_FAILED
    assert events[-1].stage is ExecutionProgressStage.FAILED
    assert "TOP-SECRET-DETAIL" not in repr(events)
