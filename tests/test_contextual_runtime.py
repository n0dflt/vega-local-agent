from pathlib import Path

from core.contextual_runtime import (
    ContextualRuntimeStatus,
    try_execute_contextual_request,
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
    )

    assert result.status is (
        ContextualRuntimeStatus.NOT_HANDLED
    )
    assert result.reason == "unsupported_intent"


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
    assert calls[0]["path"] == str(
        tmp_path.resolve()
    )
    assert "Status: COMPLETED" in result.message


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
    assert "search failed" in result.message


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
    assert "source path is required" in result.message
