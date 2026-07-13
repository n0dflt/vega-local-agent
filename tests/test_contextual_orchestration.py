from pathlib import Path
from types import SimpleNamespace

import pytest

from core.contextual_orchestration import (
    ContextualOrchestrationError,
    preview_contextual_orchestration,
)


def _orchestrator(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        context=SimpleNamespace(
            project_root=root,
        )
    )


def _policy() -> dict[str, object]:
    return {
        "enabled": False,
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


def test_preview_uses_safe_relative_search_path(
    tmp_path: Path,
) -> None:
    registry = {
        "search_in_files": lambda **arguments: arguments,
    }

    capabilities = {
        "search_in_files": {
            "permission": "READ",
            "capabilities": ["project.search"],
        }
    }

    result = preview_contextual_orchestration(
        _orchestrator(tmp_path),
        'Найди "legacy_client" в проекте',
        registry=registry,
        capability_config=capabilities,
        policy_config=_policy(),
    )

    assert result.plan.steps[0].tool_name == (
        "search_in_files"
    )
    assert result.plan.steps[0].arguments == {
        "query": "legacy_client",
        "path": ".",
    }

    assert result.policy.enabled is False
    assert result.can_auto_execute is False


def test_preview_does_not_execute_registered_tool(
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
            "permission": "READ",
            "capabilities": ["project.search"],
        }
    }

    preview_contextual_orchestration(
        _orchestrator(tmp_path),
        'Найди "old_api" в проекте',
        registry=registry,
        capability_config=capabilities,
        policy_config=_policy(),
    )

    assert calls == []


def test_missing_context_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ContextualOrchestrationError,
        match="expose a context",
    ):
        preview_contextual_orchestration(
            object(),
            'Найди "old_api" в проекте',
            registry={},
            capability_config={},
            policy_config=_policy(),
        )


def test_missing_project_root_is_rejected() -> None:
    orchestrator = SimpleNamespace(
        context=SimpleNamespace()
    )

    with pytest.raises(
        ContextualOrchestrationError,
        match="project_root",
    ):
        preview_contextual_orchestration(
            orchestrator,
            'Найди "old_api" в проекте',
            registry={},
            capability_config={},
            policy_config=_policy(),
        )


def test_empty_text_is_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ContextualOrchestrationError,
        match="must not be empty",
    ):
        preview_contextual_orchestration(
            _orchestrator(tmp_path),
            "   ",
        )
