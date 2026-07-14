"""Production construction for permission-enforced tool execution."""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from core.tool_executor import ToolExecutor
from permissions.evaluator import PermissionEvaluator
from permissions.models import PermissionPolicy
from permissions.policy import load_permission_policy
from permissions.session_grants import SessionGrantStore
from tools.registry import TOOL_REGISTRY


def build_production_session_grants(
    permission_policy: PermissionPolicy | None = None,
) -> SessionGrantStore:
    policy = permission_policy
    if policy is None:
        root = Path(__file__).resolve().parents[1]
        policy = load_permission_policy(root, registered_tools=TOOL_REGISTRY)
    return SessionGrantStore(policy.max_session_grants)


def build_production_tool_executor(
    session_grants: SessionGrantStore | None = None,
    *,
    registry: Mapping[str, Callable[..., Any]] | None = None,
    permission_policy: PermissionPolicy | None = None,
) -> ToolExecutor:
    """Load only VEGA's fixed policy and enforce it on the real registry."""
    effective_registry = TOOL_REGISTRY if registry is None else registry
    policy = permission_policy
    if policy is None:
        root = Path(__file__).resolve().parents[1]
        policy = load_permission_policy(root, registered_tools=effective_registry)
    store = (
        session_grants
        if session_grants is not None
        else SessionGrantStore(policy.max_session_grants)
    )
    return ToolExecutor(
        effective_registry,
        permission_evaluator=PermissionEvaluator(policy),
        session_grants=store,
    )


__all__ = ["build_production_session_grants", "build_production_tool_executor"]
