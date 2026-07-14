"""Production runtime construction gated by one immutable policy snapshot."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from core.policy_consistency import configuration_error_report
from core.production_snapshot import ProductionSnapshot, build_production_snapshot
from core.tool_executor import (
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolExecutor,
    ToolRequest,
)
from core.tool_executor_factory import (
    build_production_session_grants,
    build_production_tool_executor,
)
from permissions.session_grants import SessionGrantStore


_BLOCKED_MESSAGE = "Tool execution is blocked by production policy."


class _BlockedToolExecutor(ToolExecutor):
    """ToolExecutor-compatible fail-closed executor with no callables."""

    def __init__(self) -> None:
        super().__init__({})

    def execute(self, request: ToolRequest) -> ToolExecutionResult:
        if not isinstance(request, ToolRequest):
            raise TypeError("request must be a ToolRequest instance.")
        return ToolExecutionResult(
            status=ToolExecutionStatus.FAILED,
            tool_name=request.tool_name,
            error=_BLOCKED_MESSAGE,
            error_code="production_snapshot_blocked",
        )


@dataclass(frozen=True, slots=True)
class ProductionRuntimeBootstrap:
    snapshot: ProductionSnapshot
    session_grants: SessionGrantStore
    tool_executor: ToolExecutor

    @property
    def can_execute_tools(self) -> bool:
        return self.snapshot.can_execute_tools

    @property
    def status(self) -> str:
        report = self.snapshot.consistency_report
        if report.fatal_issues:
            return "Blocked"
        if report.degraded_issues:
            return "Degraded"
        return "Ready"


def build_production_runtime(project_root: Path) -> ProductionRuntimeBootstrap:
    """Build one production runtime, publishing tools only after snapshot approval."""

    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a pathlib.Path")

    snapshot = build_production_snapshot(project_root)
    if not snapshot.can_execute_tools:
        return ProductionRuntimeBootstrap(
            snapshot=snapshot,
            session_grants=SessionGrantStore(),
            tool_executor=_BlockedToolExecutor(),
        )

    permission_policy = snapshot.permission_policy
    if permission_policy is None:
        return ProductionRuntimeBootstrap(
            snapshot=replace(
                snapshot,
                consistency_report=configuration_error_report(
                    layer="production_runtime",
                    subject="permission_policy",
                    exception_type="MissingSnapshotDependency",
                ),
                tool_mapping={},
                tool_capabilities={},
            ),
            session_grants=SessionGrantStore(),
            tool_executor=_BlockedToolExecutor(),
        )

    session_grants: SessionGrantStore | None = None
    try:
        session_grants = build_production_session_grants(permission_policy)
        tool_executor = build_production_tool_executor(
            session_grants,
            registry=snapshot.tool_mapping,
            permission_policy=permission_policy,
        )
    except Exception as exc:
        safe_report = configuration_error_report(
            layer="production_runtime",
            subject="tool_executor",
            exception_type=type(exc).__name__,
        )
        return ProductionRuntimeBootstrap(
            snapshot=replace(
                snapshot,
                consistency_report=safe_report,
                tool_mapping={},
                tool_capabilities={},
            ),
            session_grants=session_grants or SessionGrantStore(),
            tool_executor=_BlockedToolExecutor(),
        )

    return ProductionRuntimeBootstrap(
        snapshot=snapshot,
        session_grants=session_grants,
        tool_executor=tool_executor,
    )


__all__ = ["ProductionRuntimeBootstrap", "build_production_runtime"]
