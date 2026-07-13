from pathlib import Path

from core.command_router import (
    CommandRouter,
    CommandTarget,
)
from core.intent_router import IntentRouter
from core.tool_executor import ToolExecutor
from core.plan_command import (
    PLAN_HELP,
    handle_plan_command,
)


def _policy(
    *,
    allow_explicit_execution: bool = False,
) -> dict[str, object]:
    return {
        "enabled": False,
        "allow_explicit_execution": (
            allow_explicit_execution
        ),
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


def _search_capabilities() -> dict[str, object]:
    return {
        "search_in_files": {
            "permission": "READ",
            "capabilities": [
                "project.search",
            ],
        },
    }


def test_plan_route_has_dedicated_target() -> None:
    intent = IntentRouter().route(
        '/plan Найди "old_api" в проекте'
    )
    route = CommandRouter().route(intent)

    assert route.target is CommandTarget.PLAN
    assert route.command_name == "/plan"
    assert route.command_arguments == (
        'Найди "old_api" в проекте'
    )


def test_plan_without_task_returns_help(
    tmp_path: Path,
) -> None:
    result = handle_plan_command(
        "/plan",
        tmp_path,
    )

    assert result == PLAN_HELP
    assert "preview" in result.lower()


def test_plan_builds_preview_without_execution(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    registry = {
        "search_in_files": (
            lambda **arguments: calls.append(arguments)
        ),
    }

    result = handle_plan_command(
        '/plan Найди "legacy_client" в проекте',
        tmp_path,
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(),
    )

    assert calls == []
    assert "Contextual execution plan" in result
    assert "Intent: project_search" in result
    assert "Tool: search_in_files" in result
    assert "Permission: READ" in result
    assert "query: legacy_client" in result
    assert "path: ." in result
    assert "Execution: preview only" in result


def test_plan_reports_controlled_error(
    tmp_path: Path,
) -> None:
    registry = {
        "search_in_files": (
            lambda **arguments: arguments
        ),
    }

    result = handle_plan_command(
        "/plan Расскажи что-нибудь интересное",
        tmp_path,
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(),
    )

    assert result.startswith("Plan command error:")
    assert "not supported" in result


def test_plan_document_without_path_fails_closed(
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

    result = handle_plan_command(
        (
            "/plan Проанализируй документ "
            "и сделай краткий отчёт"
        ),
        tmp_path,
        registry=registry,
        capability_config=capabilities,
        policy_config=_policy(),
    )

    assert result.startswith("Plan command error:")
    assert "source path is required" in result


def test_plan_run_executes_safe_tool(
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

    result = handle_plan_command(
        (
            "/plan run \u041d\u0430\u0439\u0434\u0438 "
            '"legacy_client" \u0432 \u043f\u0440\u043e\u0435\u043a\u0442\u0435'
        ),
        tmp_path,
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(
            allow_explicit_execution=True
        ),
        tool_executor=ToolExecutor(registry),
    )

    assert len(calls) == 1
    assert calls[0]["query"] == "legacy_client"
    assert calls[0]["path"] == "."
    assert "No matches found." in result
    assert "Tool: search_in_files" in result


def test_plan_run_requires_policy_permission(
    tmp_path: Path,
) -> None:
    registry = {
        "search_in_files": (
            lambda **arguments: arguments
        ),
    }

    result = handle_plan_command(
        (
            "/plan run \u041d\u0430\u0439\u0434\u0438 "
            '"legacy_client" \u0432 \u043f\u0440\u043e\u0435\u043a\u0442\u0435'
        ),
        tmp_path,
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(
            allow_explicit_execution=False
        ),
        tool_executor=ToolExecutor(registry),
    )

    assert "disabled by policy" in result


def test_plan_run_requires_tool_executor(
    tmp_path: Path,
) -> None:
    registry = {
        "search_in_files": (
            lambda **arguments: arguments
        ),
    }

    result = handle_plan_command(
        (
            "/plan run \u041d\u0430\u0439\u0434\u0438 "
            '"legacy_client" \u0432 \u043f\u0440\u043e\u0435\u043a\u0442\u0435'
        ),
        tmp_path,
        registry=registry,
        capability_config=_search_capabilities(),
        policy_config=_policy(
            allow_explicit_execution=True
        ),
    )

    assert "ToolExecutor is unavailable" in result


def test_plan_run_blocks_nonautomatic_permission(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    registry = {
        "search_in_files": (
            lambda **arguments: calls.append(arguments)
        ),
    }

    capabilities = {
        "search_in_files": {
            "permission": "WRITE",
            "capabilities": ["project.search"],
        },
    }

    result = handle_plan_command(
        (
            "/plan run \u041d\u0430\u0439\u0434\u0438 "
            '"legacy_client" \u0432 \u043f\u0440\u043e\u0435\u043a\u0442\u0435'
        ),
        tmp_path,
        registry=registry,
        capability_config=capabilities,
        policy_config=_policy(
            allow_explicit_execution=True
        ),
        tool_executor=ToolExecutor(registry),
    )

    assert calls == []
    assert "Request blocked." in result
    assert "WRITE" in result
