from __future__ import annotations

from typing import Any

from core.task_interpreter import TaskInterpretation


class ToolArgumentError(ValueError):
    """Raised when safe tool arguments cannot be constructed."""


def build_tool_arguments(
    capability: str,
    interpretation: TaskInterpretation | None,
    *,
    workspace: str = ".",
) -> dict[str, Any]:
    """Build arguments for a known tool capability."""

    normalized_capability = capability.strip().lower()
    normalized_workspace = workspace.strip()

    if not normalized_capability:
        raise ToolArgumentError(
            "capability must not be empty"
        )

    if not normalized_workspace:
        raise ToolArgumentError(
            "workspace must not be empty"
        )

    if interpretation is None:
        return {}

    if not isinstance(interpretation, TaskInterpretation):
        raise TypeError(
            "interpretation must be a TaskInterpretation instance"
        )

    if normalized_capability in {
        "document.read",
        "document.summarize",
    }:
        if interpretation.source_path is None:
            raise ToolArgumentError(
                f"source path is required for "
                f"{normalized_capability}"
            )

        return {
            "path": interpretation.source_path,
        }

    if normalized_capability == "project.search":
        if interpretation.search_query is None:
            raise ToolArgumentError(
                "search query is required for project.search"
            )

        return {
            "query": interpretation.search_query,
            "path": ".",
        }

    if normalized_capability in {
        "git.diff",
        "git.diff.cached",
    }:
        return {
            "workspace": normalized_workspace,
        }

    if normalized_capability in {
        "release.status",
        "documentation.status",
    }:
        return {
            "project_root": normalized_workspace,
        }

    return {}
