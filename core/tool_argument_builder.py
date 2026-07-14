from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from core.task_interpreter import TaskInterpretation


class ToolArgumentError(ValueError):
    """Raised when safe tool arguments cannot be constructed."""

    def __init__(
        self,
        message: str,
        *,
        capability: str = "",
        reason_code: str = "invalid_arguments",
        missing_field: str = "",
    ) -> None:
        super().__init__(message)
        self.capability = capability
        self.reason_code = reason_code
        self.missing_field = missing_field


_REQUIRED_ARGUMENTS: Mapping[str, tuple[str, ...]] = {
    "document.read": ("path",),
    "document.summarize": ("path",),
    "project.search": ("query", "path"),
    "git.status": ("workspace",),
    "git.diff": ("workspace",),
    "git.diff.cached": ("workspace",),
    "release.status": ("project_root",),
    "documentation.status": ("project_root",),
    "test.run": ("group_id", "project_root"),
    "terminal.run": ("command_id", "project_root"),
}


def validate_tool_arguments(
    capability: str,
    arguments: Mapping[str, Any],
) -> None:
    """Validate required capability arguments before a plan is executable."""

    normalized = capability.strip().lower()
    for field in _REQUIRED_ARGUMENTS.get(normalized, ()):
        value = arguments.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ToolArgumentError(
                f"required argument {field!r} is missing for {normalized}",
                capability=normalized,
                reason_code="missing_required_argument",
                missing_field=field,
            )


def _validate_source_path(source_path: str, workspace: str) -> str:
    root = Path(workspace).resolve()
    candidate = Path(source_path)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (root / candidate).resolve()
    )
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolArgumentError(
            "document source path is outside the workspace",
            capability="document.read",
            reason_code="path_outside_workspace",
        ) from exc
    return source_path


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

    if interpretation is not None and not isinstance(interpretation, TaskInterpretation):
        raise TypeError(
            "interpretation must be a TaskInterpretation instance"
        )

    if normalized_capability in {
        "document.read",
        "document.summarize",
    }:
        if interpretation is None or interpretation.source_path is None:
            raise ToolArgumentError(
                f"source path is required for "
                f"{normalized_capability}",
                capability=normalized_capability,
                reason_code="missing_required_argument",
                missing_field="path",
            )

        return {
            "path": _validate_source_path(
                interpretation.source_path,
                normalized_workspace,
            ),
        }

    if normalized_capability == "project.search":
        if interpretation is None or interpretation.search_query is None:
            raise ToolArgumentError(
                "search query is required for project.search",
                capability=normalized_capability,
                reason_code="missing_required_argument",
                missing_field="query",
            )

        return {
            "query": interpretation.search_query,
            "path": ".",
        }

    if normalized_capability in {
        "git.status",
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

    if normalized_capability == "test.run":
        return {
            "group_id": "all",
            "project_root": normalized_workspace,
        }

    if normalized_capability == "terminal.run":
        return {
            "command_id": "compile",
            "project_root": normalized_workspace,
        }

    return {}
