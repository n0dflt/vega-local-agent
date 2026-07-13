from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.contextual_router import (
    ContextualRouteResult,
    ContextualRoutingError,
    route_contextual_request,
)


class ContextualOrchestrationError(ValueError):
    """Raised when an orchestrator cannot provide routing context."""


def _project_root_from_orchestrator(
    orchestrator: object,
) -> Path:
    context = getattr(orchestrator, "context", None)

    if context is None:
        raise ContextualOrchestrationError(
            "orchestrator must expose a context"
        )

    project_root = getattr(context, "project_root", None)

    if project_root is None:
        raise ContextualOrchestrationError(
            "orchestrator context must expose project_root"
        )

    root = Path(project_root)

    if not root.exists():
        raise ContextualOrchestrationError(
            f"orchestrator project root does not exist: {root}"
        )

    if not root.is_dir():
        raise ContextualOrchestrationError(
            f"orchestrator project root is not a directory: {root}"
        )

    return root.resolve()


def preview_contextual_orchestration(
    orchestrator: object,
    text: str,
    *,
    registry: object | None = None,
    capability_config: (
        Mapping[str, Any] | str | Path | None
    ) = None,
    policy_config: (
        Mapping[str, Any] | str | Path | None
    ) = None,
) -> ContextualRouteResult:
    """
    Build a contextual execution preview for an orchestrator.

    This function never invokes tools and never changes orchestrator state.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    if not text.strip():
        raise ContextualOrchestrationError(
            "text must not be empty"
        )

    root = _project_root_from_orchestrator(orchestrator)

    if registry is None:
        from tools.registry import TOOL_REGISTRY

        registry = TOOL_REGISTRY

    if capability_config is None:
        capability_config = (
            root / "config" / "tool_capabilities.json"
        )

    if policy_config is None:
        policy_config = (
            root / "config" / "tool_routing_policy.json"
        )

    try:
        return route_contextual_request(
            text,
            registry,
            capability_config,
            policy_config,
            workspace=root,
            preview=True,
        )
    except ContextualRoutingError as exc:
        raise ContextualOrchestrationError(str(exc)) from exc


__all__ = [
    "ContextualOrchestrationError",
    "preview_contextual_orchestration",
]
