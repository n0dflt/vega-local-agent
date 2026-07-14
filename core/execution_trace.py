"""Bounded, redacted execution traces for contextual machine decisions."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any


MAX_IDENTIFIER_CHARS = 128
MAX_TRACE_CHARS = 262_144
MAX_TRACE_STEPS = 8
MAX_TRACE_COLLECTION_ITEMS = 8
MAX_TRACE_FILE_BYTES = 5 * 1024 * 1024
MAX_TRACE_BACKUPS = 5
MAX_TRACE_SCAN_FILES = MAX_TRACE_BACKUPS + 1
MAX_TRACE_SCAN_RECORDS = 1000
TRACE_ENVIRONMENT_VARIABLE = "VEGA_EXECUTION_TRACE"
TRACE_RELATIVE_PATH = Path("logs/diagnostics/execution-traces.jsonl")
_ENABLED_VALUES = frozenset({"1", "true", "yes", "on"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")
_CONTEXT_BUDGET_FIELDS = frozenset(
    {"original_chars", "selected_chars", "max_chars", "truncated"}
)
_TRACE_FIELDS = frozenset(
    {
        "trace_id",
        "request_type",
        "intent",
        "domain",
        "required_capabilities",
        "selected_tools",
        "permission_outcomes",
        "confirmation_required",
        "model_profile",
        "model",
        "model_reason_code",
        "fallback_used",
        "context_budget",
        "steps",
        "status",
        "error_codes",
    }
)
_TRACE_FIELDS_WITH_WORKFLOW = _TRACE_FIELDS | {"workflow_decision"}
_WORKFLOW_DECISION_FIELDS = frozenset(
    {
        "workflow_id", "workflow_type", "stage", "action", "outcome",
        "iteration_count", "confirmation_required", "workspace_drift",
        "rollback_available", "error_codes",
    }
)
_WORKFLOW_TYPES = frozenset({"bug-fix", "feature", "refactor", "review", "test"})
_WORKFLOW_ID = re.compile(r"^workflow-[0-9a-f]{32}$")
_WORKFLOW_STAGES = frozenset(
    {
        "planned", "investigating", "waiting_patch", "awaiting_patch_confirmation",
        "patch_applied", "awaiting_test_confirmation", "tests_running", "completed",
        "failed", "cancelled", "rolled_back",
    }
)
_WORKFLOW_OUTCOMES = frozenset(
    {"awaiting_confirmation", "cancelled", "completed", "failed", "in_progress", "rolled_back"}
)
_WORKFLOW_ACTIONS = frozenset(
    {"patch_application", "patch_rollback", "state_transition", "test_execution"}
)
_WORKFLOW_ERROR_CODES = frozenset(
    {
        "confirmation_binding_invalid", "confirmation_replayed", "iteration_limit_reached",
        "lock_timeout", "managed_patch_invalid", "patch_apply_failed", "patch_identity_changed",
        "permission_policy_error", "review_failed", "rollback_refused", "state_incompatible",
        "state_invalid", "state_write_failed", "test_configuration_missing",
        "test_execution_failed", "workspace_drift",
    }
)
_STEP_FIELDS = frozenset(
    {"step_id", "tool_name", "permission", "risk", "status", "error_code"}
)
_MODEL_REASON_CODES = frozenset(
    {
        "",
        "deep_request_policy",
        "explicit_override",
        "explicit_model_unavailable",
        "fallback_profile",
        "installed_model_fallback",
        "intent_profile",
        "manual_profile",
        "model_unavailable",
        "routing_disabled",
    }
)
_ERROR_CODES = frozenset(
    {
        "",
        "confirmation_rejected",
        "confirmation_required",
        "incomplete_dependencies",
        "intent_analysis_failed",
        "invalid_arguments",
        "invalid_project_root",
        "model_policy_error",
        "permission_denied",
        "permission_not_automatic",
        "permission_policy_error",
        "policy_error",
        "production_snapshot_blocked",
        "routing_error",
        "synthesis_failed",
        "trace_recording_failed",
        "tool_execution_failed",
        "tool_reported_failure",
        "tool_signature_invalid",
        "tool_unregistered",
        "unknown_tool",
    }
)
_STEP_STATUSES = frozenset(
    {"blocked", "failed", "invalid_arguments", "success", "unknown_tool"}
)
_RISKS = frozenset({"", "low", "medium", "high", "critical"})
_PERMISSIONS = frozenset(
    {"READ", "DRAFT", "WRITE", "EXECUTE", "SEND", "DELETE", "ADMIN"}
)
_PERMISSION_OUTCOMES = frozenset(
    {"automatic", "confirmation_required", "denied"}
)
_STORE_LOCK = threading.Lock()


class TraceError(ValueError):
    """Base error for invalid or unsafe trace operations."""


class TraceSerializationError(TraceError):
    """Raised when a trace cannot be safely serialized within its bound."""


class TraceLifecycleError(TraceError):
    """Raised when a recorder is changed after terminal finalization."""


class TraceStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TraceScanResult:
    """Bounded result from scanning the active trace file and backups."""

    traces: tuple[ExecutionTrace, ...]
    invalid_records: int
    files_scanned: int
    scan_limit_reached: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "traces", tuple(self.traces))


def _identifier(value: object, field_name: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise TraceError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        if allow_empty:
            return ""
        raise TraceError(f"{field_name} must not be empty")
    if len(normalized) > MAX_IDENTIFIER_CHARS:
        raise TraceError(
            f"{field_name} must be at most {MAX_IDENTIFIER_CHARS} characters"
        )
    if not _IDENTIFIER.fullmatch(normalized):
        raise TraceError(f"{field_name} must be a machine-safe identifier")
    return normalized


def _identifiers(
    values: object,
    field_name: str,
    *,
    maximum: int = MAX_TRACE_COLLECTION_ITEMS,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TraceError(f"{field_name} must be a collection of identifiers")
    try:
        normalized = tuple(
            _identifier(value, field_name, allow_empty=False)  # type: ignore[arg-type]
            for value in values  # type: ignore[union-attr]
        )
    except TypeError as exc:
        raise TraceError(f"{field_name} must be a collection of identifiers") from exc
    if len(normalized) > maximum:
        raise TraceError(f"{field_name} may contain at most {maximum} values")
    return normalized


def _allowlisted_identifier(
    value: object,
    field_name: str,
    allowed: frozenset[str],
) -> str:
    normalized = _identifier(value, field_name)
    if normalized not in allowed:
        raise TraceError(f"{field_name} is not an allowlisted diagnostic code")
    return normalized


def safe_trace_error_code(value: object, *, fallback: str) -> str:
    """Map an untrusted execution error code to a fixed safe vocabulary."""

    if fallback not in _ERROR_CODES or not fallback:
        raise ValueError("fallback must be a non-empty allowlisted error code")
    if isinstance(value, str):
        normalized = value.strip()
        if normalized in _ERROR_CODES and normalized:
            return normalized
    return fallback


def safe_trace_permission(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in _PERMISSIONS:
            return normalized
    return ""


def safe_trace_risk(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _RISKS:
            return normalized
    return ""


def _context_budget(value: Mapping[str, int | bool]) -> Mapping[str, int | bool]:
    if not isinstance(value, Mapping):
        raise TraceError("context_budget must be a mapping")
    if set(value) - _CONTEXT_BUDGET_FIELDS:
        raise TraceError("context_budget contains fields outside the allowlist")
    normalized: dict[str, int | bool] = {}
    for key, item in value.items():
        if key == "truncated":
            if type(item) is not bool:
                raise TraceError("context_budget.truncated must be a boolean")
        elif type(item) is not int or item < 0:
            raise TraceError(f"context_budget.{key} must be a non-negative integer")
        normalized[key] = item
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class TraceStep:
    step_id: int
    tool_name: str
    permission: str
    risk: str
    status: str
    error_code: str = ""

    def __post_init__(self) -> None:
        if type(self.step_id) is not int or not 1 <= self.step_id <= MAX_TRACE_STEPS:
            raise TraceError(f"step_id must be between 1 and {MAX_TRACE_STEPS}")
        object.__setattr__(
            self,
            "tool_name",
            _identifier(self.tool_name, "tool_name", allow_empty=False),
        )
        object.__setattr__(
            self,
            "permission",
            _allowlisted_identifier(self.permission, "permission", _PERMISSIONS),
        )
        object.__setattr__(
            self,
            "risk",
            _allowlisted_identifier(self.risk, "risk", _RISKS),
        )
        object.__setattr__(
            self,
            "status",
            _allowlisted_identifier(self.status, "step status", _STEP_STATUSES),
        )
        object.__setattr__(
            self,
            "error_code",
            _allowlisted_identifier(self.error_code, "error_code", _ERROR_CODES),
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "permission": self.permission,
            "risk": self.risk,
            "status": self.status,
            "error_code": self.error_code,
        }

    @classmethod
    def from_safe_dict(cls, value: object) -> "TraceStep":
        if not isinstance(value, dict) or set(value) != _STEP_FIELDS:
            raise TraceError("trace step contains invalid fields")
        return cls(
            step_id=value["step_id"],
            tool_name=value["tool_name"],
            permission=value["permission"],
            risk=value["risk"],
            status=value["status"],
            error_code=value["error_code"],
        )


@dataclass(frozen=True, slots=True)
class WorkflowTraceDecision:
    workflow_id: str
    workflow_type: str
    stage: str
    action: str
    outcome: str
    iteration_count: int
    confirmation_required: bool
    workspace_drift: bool
    rollback_available: bool
    error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        workflow_id = _identifier(self.workflow_id, "workflow_id", allow_empty=False)
        if not _WORKFLOW_ID.fullmatch(workflow_id):
            raise TraceError("workflow_id is invalid")
        object.__setattr__(self, "workflow_id", workflow_id)
        for name, allowed in (
            ("workflow_type", _WORKFLOW_TYPES),
            ("action", _WORKFLOW_ACTIONS),
            ("outcome", _WORKFLOW_OUTCOMES),
        ):
            value = _identifier(getattr(self, name), name, allow_empty=False)
            if value not in allowed:
                raise TraceError(f"{name} is not allowlisted")
            object.__setattr__(self, name, value)
        stage = _identifier(self.stage, "stage", allow_empty=False)
        if stage not in _WORKFLOW_STAGES:
            raise TraceError("workflow stage is not allowlisted")
        object.__setattr__(self, "stage", stage)
        if type(self.iteration_count) is not int or not 0 <= self.iteration_count <= 3:
            raise TraceError("iteration_count is outside the workflow limit")
        if any(
            type(value) is not bool
            for value in (self.confirmation_required, self.workspace_drift, self.rollback_available)
        ):
            raise TraceError("workflow decision flags must be booleans")
        codes = _identifiers(self.error_codes, "workflow_error_codes")
        if any(code not in _WORKFLOW_ERROR_CODES for code in codes):
            raise TraceError("workflow error code is not allowlisted")
        object.__setattr__(self, "error_codes", codes)

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_type": self.workflow_type,
            "stage": self.stage,
            "action": self.action,
            "outcome": self.outcome,
            "iteration_count": self.iteration_count,
            "confirmation_required": self.confirmation_required,
            "workspace_drift": self.workspace_drift,
            "rollback_available": self.rollback_available,
            "error_codes": list(self.error_codes),
        }

    @classmethod
    def from_safe_dict(cls, value: object) -> "WorkflowTraceDecision":
        if not isinstance(value, dict) or set(value) != _WORKFLOW_DECISION_FIELDS:
            raise TraceError("workflow decision contains invalid fields")
        if not isinstance(value["error_codes"], list):
            raise TraceError("workflow decision error_codes must be an array")
        return cls(**{**value, "error_codes": tuple(value["error_codes"])})


@dataclass(frozen=True, slots=True)
class ExecutionTrace:
    trace_id: str
    request_type: str
    intent: str = ""
    domain: str = ""
    required_capabilities: tuple[str, ...] = ()
    selected_tools: tuple[str, ...] = ()
    permission_outcomes: tuple[str, ...] = ()
    confirmation_required: bool = False
    model_profile: str = ""
    model: str = ""
    model_reason_code: str = ""
    fallback_used: bool = False
    context_budget: Mapping[str, int | bool] = field(default_factory=dict)
    steps: tuple[TraceStep, ...] = ()
    status: TraceStatus = TraceStatus.STARTED
    error_codes: tuple[str, ...] = ()
    workflow_decision: WorkflowTraceDecision | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "trace_id",
            _identifier(self.trace_id, "trace_id", allow_empty=False),
        )
        for name in (
            "request_type",
            "intent",
            "domain",
            "model_profile",
            "model",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "model_reason_code",
            _allowlisted_identifier(
                self.model_reason_code,
                "model_reason_code",
                _MODEL_REASON_CODES,
            ),
        )
        object.__setattr__(
            self,
            "required_capabilities",
            _identifiers(self.required_capabilities, "required_capabilities"),
        )
        object.__setattr__(
            self,
            "selected_tools",
            _identifiers(self.selected_tools, "selected_tools"),
        )
        object.__setattr__(
            self,
            "permission_outcomes",
            tuple(
                _allowlisted_identifier(
                    value,
                    "permission_outcome",
                    _PERMISSION_OUTCOMES,
                )
                for value in _identifiers(
                    self.permission_outcomes,
                    "permission_outcomes",
                )
            ),
        )
        error_codes = _identifiers(self.error_codes, "error_codes")
        object.__setattr__(
            self,
            "error_codes",
            tuple(
                _allowlisted_identifier(code, "error_code", _ERROR_CODES)
                for code in error_codes
            ),
        )
        steps = tuple(self.steps)
        if len(steps) > MAX_TRACE_STEPS:
            raise TraceError(f"trace may contain at most {MAX_TRACE_STEPS} steps")
        if any(not isinstance(step, TraceStep) for step in steps):
            raise TraceError("steps must contain TraceStep values")
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "context_budget", _context_budget(self.context_budget))
        if type(self.confirmation_required) is not bool:
            raise TraceError("confirmation_required must be a boolean")
        if type(self.fallback_used) is not bool:
            raise TraceError("fallback_used must be a boolean")
        if not isinstance(self.status, TraceStatus):
            object.__setattr__(self, "status", TraceStatus(self.status))
        if self.workflow_decision is not None and not isinstance(
            self.workflow_decision, WorkflowTraceDecision
        ):
            raise TraceError("workflow_decision must be a WorkflowTraceDecision or None")

    def to_safe_dict(self) -> dict[str, object]:
        result = {
            "trace_id": self.trace_id,
            "request_type": self.request_type,
            "intent": self.intent,
            "domain": self.domain,
            "required_capabilities": list(self.required_capabilities),
            "selected_tools": list(self.selected_tools),
            "permission_outcomes": list(self.permission_outcomes),
            "confirmation_required": self.confirmation_required,
            "model_profile": self.model_profile,
            "model": self.model,
            "model_reason_code": self.model_reason_code,
            "fallback_used": self.fallback_used,
            "context_budget": dict(self.context_budget),
            "steps": [step.to_safe_dict() for step in self.steps],
            "status": self.status.value,
            "error_codes": list(self.error_codes),
        }
        if self.workflow_decision is not None:
            result["workflow_decision"] = self.workflow_decision.to_safe_dict()
        return result

    @classmethod
    def from_safe_dict(cls, value: object) -> "ExecutionTrace":
        if not isinstance(value, dict) or set(value) not in {_TRACE_FIELDS, _TRACE_FIELDS_WITH_WORKFLOW}:
            raise TraceError("trace contains invalid fields")
        for field_name in (
            "required_capabilities",
            "selected_tools",
            "permission_outcomes",
            "steps",
            "error_codes",
        ):
            if not isinstance(value[field_name], list):
                raise TraceError(f"trace {field_name} must be an array")
        raw_steps = value["steps"]
        status = TraceStatus(value["status"])
        if status is TraceStatus.STARTED:
            raise TraceError("persisted trace must have a terminal status")
        return cls(
            trace_id=value["trace_id"],
            request_type=value["request_type"],
            intent=value["intent"],
            domain=value["domain"],
            required_capabilities=tuple(value["required_capabilities"]),
            selected_tools=tuple(value["selected_tools"]),
            permission_outcomes=tuple(value["permission_outcomes"]),
            confirmation_required=value["confirmation_required"],
            model_profile=value["model_profile"],
            model=value["model"],
            model_reason_code=value["model_reason_code"],
            fallback_used=value["fallback_used"],
            context_budget=value["context_budget"],
            steps=tuple(TraceStep.from_safe_dict(step) for step in raw_steps),
            status=status,
            error_codes=tuple(value["error_codes"]),
            workflow_decision=(
                WorkflowTraceDecision.from_safe_dict(value["workflow_decision"])
                if "workflow_decision" in value
                else None
            ),
        )


class TraceRecorder:
    """Request-local mutable recorder that publishes one frozen trace."""

    __slots__ = (
        "_confirmation_required",
        "_context_budget",
        "_domain",
        "_error_codes",
        "_fallback_used",
        "_finalized",
        "_intent",
        "_model",
        "_model_profile",
        "_model_reason_code",
        "_permission_outcomes",
        "_request_type",
        "_required_capabilities",
        "_selected_tools",
        "_steps",
        "_trace_id",
    )

    def __init__(self, *, request_type: str = "contextual") -> None:
        self._trace_id = uuid.uuid4().hex
        self._request_type = _identifier(
            request_type,
            "request_type",
            allow_empty=False,
        )
        self._intent = ""
        self._domain = ""
        self._required_capabilities: tuple[str, ...] = ()
        self._selected_tools: tuple[str, ...] = ()
        self._permission_outcomes: tuple[str, ...] = ()
        self._confirmation_required = False
        self._model_profile = ""
        self._model = ""
        self._model_reason_code = ""
        self._fallback_used = False
        self._context_budget: Mapping[str, int | bool] = {}
        self._steps: list[TraceStep] = []
        self._error_codes: list[str] = []
        self._finalized = False

    def _ensure_open(self) -> None:
        if self._finalized:
            raise TraceLifecycleError("trace recorder is already finalized")

    def record_route(
        self,
        *,
        intent: str,
        domain: str,
        required_capabilities: tuple[str, ...],
        selected_tools: tuple[str, ...],
        confirmation_required: bool,
    ) -> None:
        self._ensure_open()
        normalized_intent = _identifier(intent, "intent")
        normalized_domain = _identifier(domain, "domain")
        normalized_capabilities = _identifiers(
            required_capabilities,
            "required_capabilities",
        )
        normalized_tools = _identifiers(selected_tools, "selected_tools")
        if type(confirmation_required) is not bool:
            raise TraceError("confirmation_required must be a boolean")
        self._intent = normalized_intent
        self._domain = normalized_domain
        self._required_capabilities = normalized_capabilities
        self._selected_tools = normalized_tools
        self._confirmation_required = confirmation_required

    def record_permissions(self, outcomes: tuple[str, ...]) -> None:
        self._ensure_open()
        self._permission_outcomes = tuple(
            _allowlisted_identifier(
                value,
                "permission_outcome",
                _PERMISSION_OUTCOMES,
            )
            for value in _identifiers(outcomes, "permission_outcomes")
        )

    def record_model(
        self,
        *,
        profile: str,
        model: str,
        reason_code: str,
        fallback_used: bool,
    ) -> None:
        self._ensure_open()
        normalized_profile = _identifier(profile, "model_profile")
        normalized_model = _identifier(model, "model")
        normalized_reason = _allowlisted_identifier(
            reason_code,
            "model_reason_code",
            _MODEL_REASON_CODES,
        )
        if type(fallback_used) is not bool:
            raise TraceError("fallback_used must be a boolean")
        self._model_profile = normalized_profile
        self._model = normalized_model
        self._model_reason_code = normalized_reason
        self._fallback_used = fallback_used

    def record_context_budget(self, value: Mapping[str, int | bool]) -> None:
        self._ensure_open()
        self._context_budget = _context_budget(value)

    def record_step(self, step: TraceStep) -> None:
        self._ensure_open()
        if not isinstance(step, TraceStep):
            raise TypeError("step must be a TraceStep")
        if len(self._steps) >= MAX_TRACE_STEPS:
            raise TraceError(f"trace may contain at most {MAX_TRACE_STEPS} steps")
        self._steps.append(step)
        self._append_error_code(step.error_code)

    def _append_error_code(self, error_code: str) -> None:
        if (
            error_code
            and error_code not in self._error_codes
            and len(self._error_codes) < MAX_TRACE_COLLECTION_ITEMS
        ):
            self._error_codes.append(error_code)

    def record_synthesis(self, *, failed: bool) -> None:
        self._ensure_open()
        if type(failed) is not bool:
            raise TraceError("failed must be a boolean")
        if failed:
            self._append_error_code("synthesis_failed")

    def record_error(self, error_code: str) -> None:
        self._ensure_open()
        safe_code = _allowlisted_identifier(
            error_code,
            "error_code",
            _ERROR_CODES,
        )
        self._append_error_code(safe_code)

    def finalize(
        self,
        status: TraceStatus,
        *,
        error_codes: tuple[str, ...] = (),
    ) -> ExecutionTrace:
        self._ensure_open()
        if status is TraceStatus.STARTED:
            raise TraceLifecycleError("a trace cannot finalize with STARTED status")
        if not isinstance(status, TraceStatus):
            raise TypeError("status must be a TraceStatus")
        for code in _identifiers(error_codes, "error_codes"):
            safe_code = _allowlisted_identifier(code, "error_code", _ERROR_CODES)
            self._append_error_code(safe_code)
        trace = ExecutionTrace(
            trace_id=self._trace_id,
            request_type=self._request_type,
            intent=self._intent,
            domain=self._domain,
            required_capabilities=self._required_capabilities,
            selected_tools=self._selected_tools,
            permission_outcomes=self._permission_outcomes,
            confirmation_required=self._confirmation_required,
            model_profile=self._model_profile,
            model=self._model,
            model_reason_code=self._model_reason_code,
            fallback_used=self._fallback_used,
            context_budget=self._context_budget,
            steps=tuple(self._steps),
            status=status,
            error_codes=tuple(self._error_codes),
        )
        self._finalized = True
        self._trace_id = ""
        self._request_type = ""
        self._intent = ""
        self._domain = ""
        self._required_capabilities = ()
        self._selected_tools = ()
        self._permission_outcomes = ()
        self._confirmation_required = False
        self._model_profile = ""
        self._model = ""
        self._model_reason_code = ""
        self._fallback_used = False
        self._context_budget = MappingProxyType({})
        self._steps = []
        self._error_codes = []
        return trace


def serialize_trace(
    trace: ExecutionTrace,
    *,
    max_chars: int = MAX_TRACE_CHARS,
) -> str:
    if not isinstance(trace, ExecutionTrace):
        raise TypeError("trace must be an ExecutionTrace")
    if type(max_chars) is not int or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    try:
        serialized = json.dumps(
            trace.to_safe_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise TraceSerializationError("trace serialization failed") from exc
    if len(serialized.encode("utf-8")) > max_chars:
        raise TraceSerializationError("serialized trace exceeds the size limit")
    return serialized


def trace_persistence_enabled(
    environ: Mapping[str, str] | None = None,
) -> bool:
    source = os.environ if environ is None else environ
    value = source.get(TRACE_ENVIRONMENT_VARIABLE, "")
    return isinstance(value, str) and value.strip().lower() in _ENABLED_VALUES


def _trace_path(project_root: Path, relative_path: Path = TRACE_RELATIVE_PATH) -> Path:
    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a pathlib.Path")
    return project_root.resolve() / relative_path


def _storage_policy(project_root: Path, policy: Any = None) -> Any:
    if policy is not None:
        return policy
    from core.runtime_diagnostics import DiagnosticsPolicy, load_diagnostics_policy

    policy_path = project_root.resolve() / "config" / "diagnostics_policy.json"
    if not policy_path.exists():
        return DiagnosticsPolicy.defaults(project_root)
    return load_diagnostics_policy(project_root)


def _rotate_trace_store(path: Path, backup_count: int) -> None:
    if backup_count <= 0:
        path.unlink(missing_ok=True)
        return
    oldest = path.with_name(f"{path.name}.{backup_count}")
    oldest.unlink(missing_ok=True)
    for index in range(backup_count - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        if source.exists():
            source.replace(path.with_name(f"{path.name}.{index + 1}"))
    if path.exists():
        path.replace(path.with_name(f"{path.name}.1"))


def append_trace(
    project_root: Path,
    trace: ExecutionTrace,
    policy: Any = None,
) -> Path | None:
    """Best-effort bounded interprocess append; tracing failures never escape."""

    if not trace_persistence_enabled():
        return None
    if not isinstance(trace, ExecutionTrace) or trace.status is TraceStatus.STARTED:
        return None
    try:
        storage = _storage_policy(project_root, policy)
        from core.state_integrity import GeneratedStateLock

        serialized = serialize_trace(trace)
        encoded = (serialized + "\n").encode("utf-8")
        path = _trace_path(project_root, Path(storage.trace_store_path))
        if not _STORE_LOCK.acquire(timeout=storage.lock_timeout_ms / 1000):
            return None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with GeneratedStateLock(
                project_root.resolve(),
                path.parent,
                "trace",
                storage.lock_timeout_ms,
            ):
                current_size = path.stat().st_size if path.exists() else 0
                if current_size + len(encoded) > storage.max_trace_file_bytes:
                    _rotate_trace_store(path, storage.retained_trace_backups)
                with path.open("ab") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
        finally:
            _STORE_LOCK.release()
        return path
    except (OSError, TraceError, TypeError, ValueError, RuntimeError):
        return None


def _read_bounded_lines(path: Path, maximum_bytes: int) -> list[bytes] | None:
    try:
        if not path.is_file() or path.stat().st_size > maximum_bytes:
            return None
        return path.read_bytes().splitlines()
    except OSError:
        return None


def scan_trace_store(
    project_root: Path,
    policy: Any = None,
) -> TraceScanResult:
    """Read recent valid traces with hard file, record, and line bounds."""

    try:
        storage = _storage_policy(project_root, policy)
        active = _trace_path(project_root, Path(storage.trace_store_path))
        paths = [active]
        paths.extend(
            active.with_name(f"{active.name}.{index}")
            for index in range(1, storage.retained_trace_backups + 1)
        )
        paths = paths[: storage.max_trace_scan_files]
    except (OSError, TypeError, ValueError):
        return TraceScanResult((), 0, 0, False)

    traces: list[ExecutionTrace] = []
    invalid = 0
    files_scanned = 0
    limit_reached = False
    for path in paths:
        if not path.exists():
            continue
        files_scanned += 1
        lines = _read_bounded_lines(path, storage.max_trace_file_bytes)
        if lines is None:
            invalid += 1
            continue
        for raw_line in reversed(lines):
            if len(traces) >= storage.max_trace_records:
                limit_reached = True
                break
            if not raw_line.strip():
                continue
            if len(raw_line) > MAX_TRACE_CHARS:
                invalid += 1
                continue
            try:
                value: Any = json.loads(raw_line.decode("utf-8"))
                traces.append(ExecutionTrace.from_safe_dict(value))
            except (UnicodeError, json.JSONDecodeError, TraceError, TypeError, ValueError):
                invalid += 1
        if limit_reached:
            break
    return TraceScanResult(tuple(traces), invalid, files_scanned, limit_reached)


def load_latest_trace(project_root: Path, policy: Any = None) -> ExecutionTrace | None:
    result = scan_trace_store(project_root, policy)
    return result.traces[0] if result.traces else None


def format_trace_summary(trace: ExecutionTrace) -> str:
    """Return a short allowlisted diagnostic summary without payload data."""

    if not isinstance(trace, ExecutionTrace):
        raise TypeError("trace must be an ExecutionTrace")
    tools = ", ".join(trace.selected_tools) if trace.selected_tools else "none"
    errors = ", ".join(trace.error_codes) if trace.error_codes else "none"
    return "\n".join(
        (
            f"Trace status: {trace.status.value}",
            f"Request type: {trace.request_type or 'unknown'}",
            f"Intent: {trace.intent or 'unknown'}",
            f"Domain: {trace.domain or 'unknown'}",
            f"Selected tools: {tools}",
            f"Model profile: {trace.model_profile or 'none'}",
            f"Model reason: {trace.model_reason_code or 'none'}",
            f"Error codes: {errors}",
        )
    )


__all__ = [
    "ExecutionTrace",
    "MAX_IDENTIFIER_CHARS",
    "MAX_TRACE_COLLECTION_ITEMS",
    "MAX_TRACE_CHARS",
    "MAX_TRACE_FILE_BYTES",
    "MAX_TRACE_BACKUPS",
    "MAX_TRACE_SCAN_FILES",
    "MAX_TRACE_SCAN_RECORDS",
    "MAX_TRACE_STEPS",
    "TRACE_ENVIRONMENT_VARIABLE",
    "TRACE_RELATIVE_PATH",
    "TraceError",
    "TraceLifecycleError",
    "TraceRecorder",
    "WorkflowTraceDecision",
    "TraceSerializationError",
    "TraceStatus",
    "TraceScanResult",
    "TraceStep",
    "append_trace",
    "format_trace_summary",
    "load_latest_trace",
    "safe_trace_error_code",
    "safe_trace_permission",
    "safe_trace_risk",
    "scan_trace_store",
    "serialize_trace",
    "trace_persistence_enabled",
]
