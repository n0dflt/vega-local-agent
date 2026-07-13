"""Supported permission-enforced runtime construction for plugin tools."""

from __future__ import annotations

from core.tool_executor import ToolExecutor
from permissions.evaluator import PermissionEvaluator
from permissions.session_grants import SessionGrantStore
from plugins.bootstrap import PluginBootstrapResult


def build_plugin_tool_executor(
    bootstrap_result: PluginBootstrapResult,
    permission_evaluator: PermissionEvaluator,
    *,
    session_grants: SessionGrantStore | None = None,
) -> ToolExecutor:
    """Build the supported plugin execution path with mandatory permissions."""

    if not isinstance(bootstrap_result, PluginBootstrapResult):
        raise TypeError("bootstrap_result must be a PluginBootstrapResult")
    if not isinstance(permission_evaluator, PermissionEvaluator):
        raise TypeError("permission_evaluator must be a PermissionEvaluator")
    if session_grants is not None and not isinstance(session_grants, SessionGrantStore):
        raise TypeError("session_grants must be a SessionGrantStore or None")
    return ToolExecutor(
        bootstrap_result.combined_tool_mapping,
        permission_evaluator=permission_evaluator,
        session_grants=session_grants,
    )


__all__ = ["build_plugin_tool_executor"]
