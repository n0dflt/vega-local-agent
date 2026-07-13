from pathlib import Path

import pytest

from core.contextual_router import (
    ContextualRoutingDisabled,
    ContextualRoutingError,
    route_contextual_request,
)
from tools.registry import TOOL_REGISTRY


ROOT = Path(__file__).resolve().parents[1]


def _search_capabilities() -> dict[str, object]:
    return {
        "search_in_files": {
            "permission": "READ",
            "capabilities": ["project.search"],
        },
    }


def _document_capabilities() -> dict[str, object]:
    return {
        "read_file": {
            "permission": "READ",
            "capabilities": ["document.read"],
        },
        "summarize_file": {
            "permission": "READ",
            "capabilities": ["document.summarize"],
        },
    }


def _policy(*, enabled: bool) -> dict[str, object]:
    return {
        "enabled": enabled,
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


def test_preview_builds_plan_without_executing_tool() -> None:
    calls: list[dict[str, object]] = []

    registry = {
        "search_in_files": (
            lambda **arguments: calls.append(arguments)
        ),
    }

    result = route_contextual_request(
        'Найди "legacy_client" в проекте',
        registry,
        _search_capabilities(),
        _policy(enabled=False),
        workspace="C:/project",
        preview=True,
    )

    assert calls == []
    assert result.plan.steps[0].tool_name == (
        "search_in_files"
    )
    assert result.plan.steps[0].arguments == {
        "query": "legacy_client",
        "path": "C:/project",
    }
    assert result.requires_confirmation is False
    assert result.can_auto_execute is False


def test_enabled_safe_plan_can_auto_execute() -> None:
    registry = {
        "search_in_files": lambda **arguments: arguments,
    }

    result = route_contextual_request(
        'Найди "legacy_client" в проекте',
        registry,
        _search_capabilities(),
        _policy(enabled=True),
        preview=False,
    )

    assert result.requires_confirmation is False
    assert result.can_auto_execute is True


def test_disabled_policy_blocks_non_preview_route() -> None:
    registry = {
        "search_in_files": lambda **arguments: arguments,
    }

    with pytest.raises(
        ContextualRoutingDisabled,
        match="disabled",
    ):
        route_contextual_request(
            'Найди "legacy_client" в проекте',
            registry,
            _search_capabilities(),
            _policy(enabled=False),
        )


def test_unknown_request_fails_closed() -> None:
    registry = {
        "search_in_files": lambda **arguments: arguments,
    }

    with pytest.raises(
        ContextualRoutingError,
        match="not supported",
    ):
        route_contextual_request(
            "Расскажи что-нибудь интересное",
            registry,
            _search_capabilities(),
            _policy(enabled=True),
        )


def test_missing_document_path_fails_closed() -> None:
    registry = {
        "read_file": lambda **arguments: arguments,
        "summarize_file": lambda **arguments: arguments,
    }

    with pytest.raises(
        ContextualRoutingError,
        match="source path is required",
    ):
        route_contextual_request(
            "Проанализируй документ "
            "и сделай краткий отчёт",
            registry,
            _document_capabilities(),
            _policy(enabled=True),
        )


def test_unsafe_policy_options_are_rejected() -> None:
    policy = _policy(enabled=True)
    policy["allow_shell_generation"] = True

    with pytest.raises(
        ContextualRoutingError,
        match="shell generation",
    ):
        route_contextual_request(
            'Найди "legacy_client" в проекте',
            {
                "search_in_files": (
                    lambda **arguments: arguments
                ),
            },
            _search_capabilities(),
            policy,
        )


def test_production_preview_uses_real_registry() -> None:
    result = route_contextual_request(
        "Посмотри изменения и оцени риски",
        TOOL_REGISTRY,
        ROOT / "config" / "tool_capabilities.json",
        ROOT / "config" / "tool_routing_policy.json",
        workspace=ROOT,
        preview=True,
    )

    assert len(result.plan.steps) == 1
    assert result.plan.steps[0].tool_name == "git_diff"
    assert result.plan.steps[0].arguments == {
        "workspace": str(ROOT),
    }

    serialized = result.to_dict()

    assert serialized["analysis"]["intent"] == (
        "code_review"
    )
    assert serialized["routing"]["policy_enabled"] is True
    assert serialized["routing"]["can_auto_execute"] is True
