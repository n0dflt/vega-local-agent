"""Local-only, bounded, payload-free runtime diagnostics for VEGA."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from core.execution_trace import (
    MAX_IDENTIFIER_CHARS,
    MAX_TRACE_BACKUPS,
    MAX_TRACE_FILE_BYTES,
    MAX_TRACE_SCAN_FILES,
    MAX_TRACE_SCAN_RECORDS,
    ExecutionTrace,
    TraceScanResult,
    scan_trace_store,
    trace_persistence_enabled,
)
from core.state_integrity import (
    MAX_LOCK_TIMEOUT_MS,
    MAX_QUARANTINE_FILES,
    MAX_STALE_TEMP_AGE_SECONDS,
    MAX_STATE_SCAN_FILES,
    STATE_ERROR_CODES,
    GeneratedStateLock,
    StateIntegrityDiagnostics,
    StateLockError,
    inspect_local_state,
)
from scripts.version import VERSION


DIAGNOSTICS_POLICY_RELATIVE_PATH = Path("config/diagnostics_policy.json")
DIAGNOSTICS_SCHEMA_VERSION = 2
REPORT_SCHEMA_VERSION = 2
MAX_DOCTOR_REPORT_BYTES = 1024 * 1024
MAX_RETAINED_DOCTOR_REPORTS = 20
MAX_REPORT_RETENTION_SCAN_FILES = 100
MAX_INDEX_BYTES = 5 * 1024 * 1024
MAX_COUNT = 1_000_000
MAX_DIAGNOSTIC_CODES = 32
MAX_DIAGNOSTICS_PATH_CHARS = 240

_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "trace_store_path",
        "max_trace_file_bytes",
        "retained_trace_backups",
        "max_trace_scan_files",
        "max_trace_records",
        "doctor_reports_dir",
        "max_doctor_report_bytes",
        "retained_doctor_reports",
        "lock_timeout_ms",
        "stale_temp_age_seconds",
        "max_state_scan_files",
        "retained_quarantine_files",
    }
)
_BLOCKED_PATH_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".cache",
        "cache",
        "node_modules",
    }
)
_STATUSES = frozenset({"healthy", "degraded", "blocked", "unavailable"})
_ERROR_CODES = frozenset(
    {
        "diagnostics_policy_error",
        "diagnostics_build_failed",
        "diagnostics_serialization_failed",
        "diagnostics_export_failed",
        "diagnostics_report_too_large",
        "diagnostics_retention_failed",
        "production_snapshot_blocked",
        "model_unavailable",
        "model_not_installed",
        "documents_directory_missing",
        "documents_index_missing",
        "documents_index_invalid",
        "memory_unavailable",
        "terminal_policy_error",
        "trace_store_unavailable",
        "trace_record_invalid",
        "trace_scan_limit_reached",
        "workflow_state_invalid",
        "workflow_scan_limit_reached",
    }
    | STATE_ERROR_CODES
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")
_REPORT_NAME = re.compile(r"^doctor-\d{8}T\d{12}Z\.json$")


class DiagnosticsError(ValueError):
    """Base error for invalid or unsafe diagnostic operations."""


class DiagnosticsPolicyError(DiagnosticsError):
    """Raised when the diagnostics policy is missing or invalid."""


class DiagnosticsSerializationError(DiagnosticsError):
    """Raised when a report cannot be serialized inside its hard bound."""


class DiagnosticsExportError(DiagnosticsError):
    """Raised when an explicit report export fails safely."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DiagnosticsPolicyError("diagnostics policy contains duplicate fields")
        result[key] = value
    return result


def _integer(value: object, field: str, maximum: int, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or not minimum <= value <= maximum:
        raise DiagnosticsPolicyError(
            f"{field} must be an integer from {minimum} to {maximum}"
        )
    return value


def _validate_relative_path(root: Path, value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiagnosticsPolicyError(f"{field} must be a non-empty relative path")
    raw = value.strip().replace("\\", "/")
    if len(raw) > MAX_DIAGNOSTICS_PATH_CHARS:
        raise DiagnosticsPolicyError(
            f"{field} must be at most {MAX_DIAGNOSTICS_PATH_CHARS} characters"
        )
    candidate = Path(raw)
    windows_candidate = PureWindowsPath(raw)
    posix_candidate = PurePosixPath(raw)
    if (
        windows_candidate.is_absolute()
        or windows_candidate.drive
        or posix_candidate.is_absolute()
        or raw.startswith(("/", "\\"))
    ):
        raise DiagnosticsPolicyError(f"{field} cannot be absolute")
    if ".." in candidate.parts:
        raise DiagnosticsPolicyError(f"{field} cannot contain parent traversal")
    if any(part.lower() in _BLOCKED_PATH_PARTS for part in candidate.parts):
        raise DiagnosticsPolicyError(f"{field} contains a blocked directory")
    normalized = Path(*candidate.parts)
    resolved_root = root.resolve()
    resolved = (resolved_root / normalized).resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise DiagnosticsPolicyError(f"{field} escapes the project root") from exc
    return normalized.as_posix()


@dataclass(frozen=True, slots=True)
class DiagnosticsPolicy:
    """Validated immutable resource and path policy for local diagnostics."""

    schema_version: int
    trace_store_path: str
    max_trace_file_bytes: int
    retained_trace_backups: int
    max_trace_scan_files: int
    max_trace_records: int
    doctor_reports_dir: str
    max_doctor_report_bytes: int
    retained_doctor_reports: int
    lock_timeout_ms: int
    stale_temp_age_seconds: int
    max_state_scan_files: int
    retained_quarantine_files: int

    def __post_init__(self) -> None:
        if self.schema_version != DIAGNOSTICS_SCHEMA_VERSION:
            raise DiagnosticsPolicyError("unsupported diagnostics policy schema_version")
        for field, value in (
            ("trace_store_path", self.trace_store_path),
            ("doctor_reports_dir", self.doctor_reports_dir),
        ):
            candidate = Path(value)
            windows_candidate = PureWindowsPath(value)
            posix_candidate = PurePosixPath(value)
            if (
                not isinstance(value, str)
                or not value
                or len(value) > MAX_DIAGNOSTICS_PATH_CHARS
                or windows_candidate.is_absolute()
                or windows_candidate.drive
                or posix_candidate.is_absolute()
                or ".." in candidate.parts
                or any(part.lower() in _BLOCKED_PATH_PARTS for part in candidate.parts)
            ):
                raise DiagnosticsPolicyError(f"{field} is not a safe relative path")
        _integer(self.max_trace_file_bytes, "max_trace_file_bytes", MAX_TRACE_FILE_BYTES)
        _integer(
            self.retained_trace_backups,
            "retained_trace_backups",
            MAX_TRACE_BACKUPS,
            allow_zero=True,
        )
        _integer(self.max_trace_scan_files, "max_trace_scan_files", MAX_TRACE_SCAN_FILES)
        if self.max_trace_scan_files > self.retained_trace_backups + 1:
            raise DiagnosticsPolicyError(
                "max_trace_scan_files exceeds the configured trace file count"
            )
        _integer(self.max_trace_records, "max_trace_records", MAX_TRACE_SCAN_RECORDS)
        _integer(
            self.max_doctor_report_bytes,
            "max_doctor_report_bytes",
            MAX_DOCTOR_REPORT_BYTES,
        )
        _integer(
            self.retained_doctor_reports,
            "retained_doctor_reports",
            MAX_RETAINED_DOCTOR_REPORTS,
        )
        _integer(self.lock_timeout_ms, "lock_timeout_ms", MAX_LOCK_TIMEOUT_MS)
        _integer(
            self.stale_temp_age_seconds,
            "stale_temp_age_seconds",
            MAX_STALE_TEMP_AGE_SECONDS,
        )
        _integer(
            self.max_state_scan_files,
            "max_state_scan_files",
            MAX_STATE_SCAN_FILES,
        )
        _integer(
            self.retained_quarantine_files,
            "retained_quarantine_files",
            MAX_QUARANTINE_FILES,
        )
        if self.retained_quarantine_files > self.max_state_scan_files:
            raise DiagnosticsPolicyError(
                "retained_quarantine_files exceeds max_state_scan_files"
            )

    @classmethod
    def defaults(cls, project_root: Path) -> "DiagnosticsPolicy":
        if not isinstance(project_root, Path):
            raise TypeError("project_root must be a pathlib.Path")
        return cls(
            schema_version=DIAGNOSTICS_SCHEMA_VERSION,
            trace_store_path="logs/diagnostics/execution-traces.jsonl",
            max_trace_file_bytes=MAX_TRACE_FILE_BYTES,
            retained_trace_backups=3,
            max_trace_scan_files=4,
            max_trace_records=256,
            doctor_reports_dir="logs/diagnostics/reports",
            max_doctor_report_bytes=512 * 1024,
            retained_doctor_reports=10,
            lock_timeout_ms=500,
            stale_temp_age_seconds=3600,
            max_state_scan_files=64,
            retained_quarantine_files=10,
        )


def load_diagnostics_policy(project_root: Path) -> DiagnosticsPolicy:
    """Load the complete strict policy or raise without returning partial state."""

    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a pathlib.Path")
    root = project_root.resolve()
    path = root / DIAGNOSTICS_POLICY_RELATIVE_PATH
    try:
        if path.stat().st_size > 64 * 1024:
            raise DiagnosticsPolicyError("diagnostics policy exceeds the size limit")
        raw = json.loads(
            path.read_text(encoding="utf-8-sig"),
            object_pairs_hook=_strict_object,
        )
    except DiagnosticsPolicyError:
        raise
    except FileNotFoundError as exc:
        raise DiagnosticsPolicyError("diagnostics policy is missing") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DiagnosticsPolicyError("diagnostics policy could not be loaded") from exc
    if not isinstance(raw, dict) or set(raw) != _POLICY_FIELDS:
        raise DiagnosticsPolicyError("diagnostics policy fields do not match the contract")
    return DiagnosticsPolicy(
        schema_version=raw["schema_version"],
        trace_store_path=_validate_relative_path(
            root, raw["trace_store_path"], "trace_store_path"
        ),
        max_trace_file_bytes=_integer(
            raw["max_trace_file_bytes"], "max_trace_file_bytes", MAX_TRACE_FILE_BYTES
        ),
        retained_trace_backups=_integer(
            raw["retained_trace_backups"],
            "retained_trace_backups",
            MAX_TRACE_BACKUPS,
            allow_zero=True,
        ),
        max_trace_scan_files=_integer(
            raw["max_trace_scan_files"], "max_trace_scan_files", MAX_TRACE_SCAN_FILES
        ),
        max_trace_records=_integer(
            raw["max_trace_records"], "max_trace_records", MAX_TRACE_SCAN_RECORDS
        ),
        doctor_reports_dir=_validate_relative_path(
            root, raw["doctor_reports_dir"], "doctor_reports_dir"
        ),
        max_doctor_report_bytes=_integer(
            raw["max_doctor_report_bytes"],
            "max_doctor_report_bytes",
            MAX_DOCTOR_REPORT_BYTES,
        ),
        retained_doctor_reports=_integer(
            raw["retained_doctor_reports"],
            "retained_doctor_reports",
            MAX_RETAINED_DOCTOR_REPORTS,
        ),
        lock_timeout_ms=_integer(
            raw["lock_timeout_ms"], "lock_timeout_ms", MAX_LOCK_TIMEOUT_MS
        ),
        stale_temp_age_seconds=_integer(
            raw["stale_temp_age_seconds"],
            "stale_temp_age_seconds",
            MAX_STALE_TEMP_AGE_SECONDS,
        ),
        max_state_scan_files=_integer(
            raw["max_state_scan_files"],
            "max_state_scan_files",
            MAX_STATE_SCAN_FILES,
        ),
        retained_quarantine_files=_integer(
            raw["retained_quarantine_files"],
            "retained_quarantine_files",
            MAX_QUARANTINE_FILES,
        ),
    )


def _safe_identifier(value: object, field: str, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DiagnosticsError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized and empty:
        return ""
    if (
        not normalized
        or len(normalized) > MAX_IDENTIFIER_CHARS
        or not _SAFE_IDENTIFIER.fullmatch(normalized)
    ):
        raise DiagnosticsError(f"{field} must be a bounded machine identifier")
    return normalized


def _status(value: object) -> str:
    normalized = _safe_identifier(value, "status")
    if normalized not in _STATUSES:
        raise DiagnosticsError("status is not allowlisted")
    return normalized


def _codes(values: object) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise DiagnosticsError("error_codes must be a collection")
    try:
        result = tuple(_safe_identifier(value, "error_code") for value in values)  # type: ignore[union-attr]
    except TypeError as exc:
        raise DiagnosticsError("error_codes must be a collection") from exc
    if len(result) > MAX_DIAGNOSTIC_CODES or any(code not in _ERROR_CODES for code in result):
        raise DiagnosticsError("error_codes contain values outside the allowlist")
    return tuple(dict.fromkeys(result))


def _count(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_COUNT:
        raise DiagnosticsError(f"{field} must be a bounded non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class ProductionDiagnostics:
    status: str
    can_execute_tools: bool
    fatal_issues: int
    degraded_issues: int
    warnings: int
    issue_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _status(self.status))
        if type(self.can_execute_tools) is not bool:
            raise DiagnosticsError("can_execute_tools must be boolean")
        for name in ("fatal_issues", "degraded_issues", "warnings"):
            _count(getattr(self, name), name)
        codes = tuple(_safe_identifier(code, "issue_code") for code in self.issue_codes)
        if len(codes) > MAX_DIAGNOSTIC_CODES:
            raise DiagnosticsError("issue_codes exceed the collection limit")
        object.__setattr__(self, "issue_codes", tuple(dict.fromkeys(codes)))

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "can_execute_tools": self.can_execute_tools,
            "fatal_issues": self.fatal_issues,
            "degraded_issues": self.degraded_issues,
            "warnings": self.warnings,
            "issue_codes": list(self.issue_codes),
        }


@dataclass(frozen=True, slots=True)
class ModelDiagnostics:
    status: str
    selection_mode: str
    current_profile: str
    current_model: str
    ollama_available: bool
    model_installed: bool
    fallback_status: str
    error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _status(self.status))
        for name in ("selection_mode", "current_profile", "current_model", "fallback_status"):
            object.__setattr__(self, name, _safe_identifier(getattr(self, name), name, empty=True))
        if type(self.ollama_available) is not bool or type(self.model_installed) is not bool:
            raise DiagnosticsError("model availability fields must be boolean")
        object.__setattr__(self, "error_codes", _codes(self.error_codes))

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "selection_mode": self.selection_mode,
            "current_profile": self.current_profile,
            "current_model": self.current_model,
            "ollama_available": self.ollama_available,
            "model_installed": self.model_installed,
            "fallback_status": self.fallback_status,
            "error_codes": list(self.error_codes),
        }


@dataclass(frozen=True, slots=True)
class DocumentsDiagnostics:
    status: str
    directory_exists: bool
    index_exists: bool
    documents: int
    chunks: int
    error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _status(self.status))
        if type(self.directory_exists) is not bool or type(self.index_exists) is not bool:
            raise DiagnosticsError("document existence fields must be boolean")
        _count(self.documents, "documents")
        _count(self.chunks, "chunks")
        object.__setattr__(self, "error_codes", _codes(self.error_codes))

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "directory_exists": self.directory_exists,
            "index_exists": self.index_exists,
            "documents": self.documents,
            "chunks": self.chunks,
            "error_codes": list(self.error_codes),
        }


@dataclass(frozen=True, slots=True)
class CountedSubsystemDiagnostics:
    status: str
    available: bool
    count: int
    error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _status(self.status))
        if type(self.available) is not bool:
            raise DiagnosticsError("available must be boolean")
        _count(self.count, "count")
        object.__setattr__(self, "error_codes", _codes(self.error_codes))

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "available": self.available,
            "count": self.count,
            "error_codes": list(self.error_codes),
        }


@dataclass(frozen=True, slots=True)
class TraceLatestDiagnostics:
    status: str
    request_type: str
    intent: str
    domain: str
    model_profile: str
    error_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _safe_identifier(self.status, "trace status"))
        for name in ("request_type", "intent", "domain", "model_profile"):
            object.__setattr__(self, name, _safe_identifier(getattr(self, name), name, empty=True))
        safe = tuple(_safe_identifier(code, "trace error code") for code in self.error_codes)
        if len(safe) > MAX_DIAGNOSTIC_CODES:
            raise DiagnosticsError("trace error codes exceed the limit")
        object.__setattr__(self, "error_codes", safe)

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "request_type": self.request_type,
            "intent": self.intent,
            "domain": self.domain,
            "model_profile": self.model_profile,
            "error_codes": list(self.error_codes),
        }


def _counter_pairs(values: object, field: str) -> tuple[tuple[str, int], ...]:
    try:
        pairs = tuple(values)  # type: ignore[arg-type]
    except TypeError as exc:
        raise DiagnosticsError(f"{field} must be a collection") from exc
    if len(pairs) > MAX_DIAGNOSTIC_CODES:
        raise DiagnosticsError(f"{field} exceeds the collection limit")
    normalized: list[tuple[str, int]] = []
    seen: set[str] = set()
    for pair in pairs:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise DiagnosticsError(f"{field} entries must be pairs")
        key = _safe_identifier(pair[0], field)
        if key in seen:
            raise DiagnosticsError(f"{field} contains duplicate identifiers")
        seen.add(key)
        normalized.append((key, _count(pair[1], field)))
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class TraceAggregateDiagnostics:
    scanned_records: int
    completed: int
    blocked: int
    failed: int
    corrupt_skipped: int
    error_code_counts: tuple[tuple[str, int], ...] = ()
    request_type_counts: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        for name in ("scanned_records", "completed", "blocked", "failed", "corrupt_skipped"):
            _count(getattr(self, name), name)
        object.__setattr__(self, "error_code_counts", _counter_pairs(self.error_code_counts, "error_code_counts"))
        object.__setattr__(self, "request_type_counts", _counter_pairs(self.request_type_counts, "request_type_counts"))

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "scanned_records": self.scanned_records,
            "completed": self.completed,
            "blocked": self.blocked,
            "failed": self.failed,
            "corrupt_skipped": self.corrupt_skipped,
            "error_code_counts": dict(self.error_code_counts),
            "request_type_counts": dict(self.request_type_counts),
        }


@dataclass(frozen=True, slots=True)
class TraceStoreDiagnostics:
    status: str
    enabled: bool
    store_path: str
    active_exists: bool
    active_bytes: int
    backup_count: int
    valid_records: int
    corrupt_records_detected: bool
    latest: TraceLatestDiagnostics | None
    aggregate: TraceAggregateDiagnostics
    error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _status(self.status))
        if any(type(value) is not bool for value in (self.enabled, self.active_exists, self.corrupt_records_detected)):
            raise DiagnosticsError("trace state flags must be boolean")
        _count(self.active_bytes, "active_bytes")
        _count(self.backup_count, "backup_count")
        _count(self.valid_records, "valid_records")
        candidate = Path(self.store_path)
        if (
            PureWindowsPath(self.store_path).is_absolute()
            or PureWindowsPath(self.store_path).drive
            or PurePosixPath(self.store_path).is_absolute()
            or ".." in candidate.parts
        ):
            raise DiagnosticsError("store_path must be relative")
        object.__setattr__(self, "store_path", candidate.as_posix())
        if self.latest is not None and not isinstance(self.latest, TraceLatestDiagnostics):
            raise DiagnosticsError("latest must be TraceLatestDiagnostics or None")
        if not isinstance(self.aggregate, TraceAggregateDiagnostics):
            raise DiagnosticsError("aggregate must be TraceAggregateDiagnostics")
        object.__setattr__(self, "error_codes", _codes(self.error_codes))

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "enabled": self.enabled,
            "store_path": self.store_path,
            "active_exists": self.active_exists,
            "active_bytes": self.active_bytes,
            "backup_count": self.backup_count,
            "valid_records": self.valid_records,
            "corrupt_records_detected": self.corrupt_records_detected,
            "latest": self.latest.to_safe_dict() if self.latest is not None else None,
            "aggregate": self.aggregate.to_safe_dict(),
            "error_codes": list(self.error_codes),
        }


@dataclass(frozen=True, slots=True)
class RuntimeFilesDiagnostics:
    smoke_test_exists: bool
    release_policy_exists: bool
    diagnostics_policy_exists: bool

    def __post_init__(self) -> None:
        if any(
            type(value) is not bool
            for value in (
                self.smoke_test_exists,
                self.release_policy_exists,
                self.diagnostics_policy_exists,
            )
        ):
            raise DiagnosticsError("runtime file fields must be boolean")

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "smoke_test_exists": self.smoke_test_exists,
            "release_policy_exists": self.release_policy_exists,
            "diagnostics_policy_exists": self.diagnostics_policy_exists,
        }


@dataclass(frozen=True, slots=True)
class WorkflowDiagnostics:
    """Payload-free snapshot of the controlled workflow state machine."""

    status: str
    available: bool
    active_count: int
    history_count: int
    workflow_id: str = ""
    workflow_type: str = ""
    stage: str = ""
    next_actions: tuple[str, ...] = ()
    confirmation_required: bool = False
    iteration_count: int = 0
    rollback_available: bool = False
    workspace_drift: bool = False
    workflow_error_codes: tuple[str, ...] = ()
    error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _status(self.status))
        if any(
            type(value) is not bool
            for value in (
                self.available, self.confirmation_required,
                self.rollback_available, self.workspace_drift,
            )
        ):
            raise DiagnosticsError("workflow diagnostic flags must be booleans")
        _count(self.active_count, "active_count")
        _count(self.history_count, "history_count")
        if type(self.iteration_count) is not int or not 0 <= self.iteration_count <= 3:
            raise DiagnosticsError("workflow iteration count is outside the limit")
        from workflows.controlled_models import NEXT_ACTIONS, SAFE_ERROR_CODES, WORKFLOW_TYPES
        from workflows.models import WORKFLOW_ID_PATTERN, WorkflowStatus

        workflow_id = _safe_identifier(self.workflow_id, "workflow_id", empty=True)
        if workflow_id and not WORKFLOW_ID_PATTERN.fullmatch(workflow_id):
            raise DiagnosticsError("workflow_id is invalid")
        workflow_type = _safe_identifier(self.workflow_type, "workflow_type", empty=True)
        if workflow_type and workflow_type not in WORKFLOW_TYPES:
            raise DiagnosticsError("workflow_type is not allowlisted")
        stage = _safe_identifier(self.stage, "stage", empty=True)
        if stage:
            try:
                WorkflowStatus(stage)
            except ValueError as exc:
                raise DiagnosticsError("workflow stage is not allowlisted") from exc
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "workflow_type", workflow_type)
        object.__setattr__(self, "stage", stage)
        actions = tuple(_safe_identifier(value, "next_action") for value in self.next_actions)
        if len(actions) > 8 or any(action not in NEXT_ACTIONS for action in actions):
            raise DiagnosticsError("workflow next actions exceed the limit")
        object.__setattr__(self, "next_actions", actions)
        workflow_codes = tuple(
            _safe_identifier(value, "workflow_error_code") for value in self.workflow_error_codes
        )
        if len(workflow_codes) > 8 or any(value not in SAFE_ERROR_CODES for value in workflow_codes):
            raise DiagnosticsError("workflow error codes are not allowlisted")
        object.__setattr__(self, "workflow_error_codes", workflow_codes)
        object.__setattr__(self, "error_codes", _codes(self.error_codes))

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "available": self.available,
            "active_count": self.active_count,
            "history_count": self.history_count,
            "workflow_id": self.workflow_id,
            "workflow_type": self.workflow_type,
            "stage": self.stage,
            "next_actions": list(self.next_actions),
            "confirmation_required": self.confirmation_required,
            "iteration_count": self.iteration_count,
            "rollback_available": self.rollback_available,
            "workspace_drift": self.workspace_drift,
            "workflow_error_codes": list(self.workflow_error_codes),
            "error_codes": list(self.error_codes),
        }


@dataclass(frozen=True, slots=True)
class RuntimeDiagnosticsReport:
    """Immutable allowlisted runtime report with no user or tool payload data."""

    schema_version: int
    version: str
    created_at: str
    report_type: str
    status: str
    error_codes: tuple[str, ...]
    production_snapshot: ProductionDiagnostics
    model_runtime: ModelDiagnostics
    documents: DocumentsDiagnostics
    memory: CountedSubsystemDiagnostics
    terminal_policy: CountedSubsystemDiagnostics
    execution_traces: TraceStoreDiagnostics
    local_state: StateIntegrityDiagnostics
    controlled_workflows: WorkflowDiagnostics
    runtime_files: RuntimeFilesDiagnostics

    def __post_init__(self) -> None:
        if self.schema_version != REPORT_SCHEMA_VERSION:
            raise DiagnosticsError("unsupported report schema_version")
        object.__setattr__(self, "version", _safe_identifier(self.version, "version"))
        object.__setattr__(self, "report_type", _safe_identifier(self.report_type, "report_type"))
        object.__setattr__(self, "status", _status(self.status))
        object.__setattr__(self, "error_codes", _codes(self.error_codes))
        try:
            datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise DiagnosticsError("created_at must be an ISO-8601 timestamp") from exc

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "version": self.version,
            "created_at": self.created_at,
            "report_type": self.report_type,
            "status": self.status,
            "error_codes": list(self.error_codes),
            "production_snapshot": self.production_snapshot.to_safe_dict(),
            "model_runtime": self.model_runtime.to_safe_dict(),
            "documents": self.documents.to_safe_dict(),
            "memory": self.memory.to_safe_dict(),
            "terminal_policy": self.terminal_policy.to_safe_dict(),
            "execution_traces": self.execution_traces.to_safe_dict(),
            "local_state": self.local_state.to_safe_dict(),
            "controlled_workflows": self.controlled_workflows.to_safe_dict(),
            "runtime_files": self.runtime_files.to_safe_dict(),
        }


@dataclass(frozen=True, slots=True)
class DiagnosticsExportResult:
    relative_path: str
    report: RuntimeDiagnosticsReport


def _latest(trace: ExecutionTrace | None) -> TraceLatestDiagnostics | None:
    if trace is None:
        return None
    return TraceLatestDiagnostics(
        status=trace.status.value,
        request_type=trace.request_type,
        intent=trace.intent,
        domain=trace.domain,
        model_profile=trace.model_profile,
        error_codes=trace.error_codes,
    )


def summarize_recent_traces(scan: TraceScanResult) -> TraceAggregateDiagnostics:
    """Aggregate only terminal statuses and allowlisted machine identifiers."""

    if not isinstance(scan, TraceScanResult):
        raise TypeError("scan must be a TraceScanResult")
    statuses = Counter(trace.status.value for trace in scan.traces)
    error_codes = Counter(code for trace in scan.traces for code in trace.error_codes)
    request_types = Counter(
        trace.request_type for trace in scan.traces if trace.request_type
    )
    return TraceAggregateDiagnostics(
        scanned_records=len(scan.traces),
        completed=statuses["completed"],
        blocked=statuses["blocked"],
        failed=statuses["failed"],
        corrupt_skipped=scan.invalid_records,
        error_code_counts=tuple(sorted(error_codes.items())),
        request_type_counts=tuple(sorted(request_types.items())),
    )


def get_trace_store_status(
    project_root: Path,
    policy: DiagnosticsPolicy,
) -> TraceStoreDiagnostics:
    """Return bounded trace-store metadata without exposing an absolute path."""

    active = project_root.resolve() / policy.trace_store_path
    errors: list[str] = []
    try:
        active_exists = active.is_file()
        active_bytes = min(active.stat().st_size, MAX_COUNT) if active_exists else 0
        backup_count = sum(
            active.with_name(f"{active.name}.{index}").is_file()
            for index in range(1, policy.retained_trace_backups + 1)
        )
        scan = scan_trace_store(project_root, policy)
    except OSError:
        active_exists = False
        active_bytes = 0
        backup_count = 0
        scan = TraceScanResult((), 0, 0, False)
        errors.append("trace_store_unavailable")
    if scan.invalid_records:
        errors.append("trace_record_invalid")
    if scan.scan_limit_reached:
        errors.append("trace_scan_limit_reached")
    status = "degraded" if errors else "healthy"
    return TraceStoreDiagnostics(
        status=status,
        enabled=trace_persistence_enabled(),
        store_path=policy.trace_store_path,
        active_exists=active_exists,
        active_bytes=active_bytes,
        backup_count=backup_count,
        valid_records=len(scan.traces),
        corrupt_records_detected=bool(scan.invalid_records),
        latest=_latest(scan.traces[0] if scan.traces else None),
        aggregate=summarize_recent_traces(scan),
        error_codes=tuple(errors),
    )


def _build_production(project_root: Path, supplied: Any = None) -> ProductionDiagnostics:
    from core.production_snapshot import build_production_snapshot

    snapshot = supplied if supplied is not None else build_production_snapshot(project_root)
    report = snapshot.consistency_report
    if report.fatal_issues:
        status = "blocked"
    elif report.degraded_issues:
        status = "degraded"
    else:
        status = "healthy"
    codes = tuple(issue.code.value for issue in report.issues[:MAX_DIAGNOSTIC_CODES])
    return ProductionDiagnostics(
        status=status,
        can_execute_tools=snapshot.can_execute_tools,
        fatal_issues=len(report.fatal_issues),
        degraded_issues=len(report.degraded_issues),
        warnings=len(report.warnings),
        issue_codes=codes,
    )


def _build_model(project_root: Path, supplied: Mapping[str, object] | None) -> ModelDiagnostics:
    if supplied is None:
        from core.model_router import (
            get_current_profile,
            get_selection_mode,
            is_ollama_available,
        )

        profile = get_current_profile(project_root)
        ollama_available = is_ollama_available()
        supplied = {
            "selection_mode": get_selection_mode(project_root).value,
            "current_profile": profile["name"],
            "current_model": profile["model"],
            "ollama_available": ollama_available,
            # Diagnostics never launches Ollama merely to probe installed models.
            "model_installed": False,
            "fallback_status": "not_used",
        }
    ollama = supplied.get("ollama_available") is True
    installed = supplied.get("model_installed") is True
    errors: tuple[str, ...] = ()
    if not ollama:
        errors = ("model_unavailable",)
    elif not installed:
        errors = ("model_not_installed",)
    return ModelDiagnostics(
        status="healthy" if not errors else "degraded",
        selection_mode=supplied.get("selection_mode", "") if isinstance(supplied.get("selection_mode", ""), str) else "",
        current_profile=supplied.get("current_profile", "") if isinstance(supplied.get("current_profile", ""), str) else "",
        current_model=supplied.get("current_model", "") if isinstance(supplied.get("current_model", ""), str) else "",
        ollama_available=ollama,
        model_installed=installed,
        fallback_status=supplied.get("fallback_status", "") if isinstance(supplied.get("fallback_status", ""), str) else "",
        error_codes=errors,
    )


def _build_documents(project_root: Path) -> DocumentsDiagnostics:
    directory = project_root / "data" / "documents"
    index_path = project_root / "data" / "index" / "documents_index.json"
    errors: list[str] = []
    documents = 0
    chunks = 0
    if not directory.is_dir():
        errors.append("documents_directory_missing")
    if not index_path.is_file():
        errors.append("documents_index_missing")
    else:
        try:
            if index_path.stat().st_size > MAX_INDEX_BYTES:
                raise ValueError
            value = json.loads(index_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError
            documents = _count(value.get("documents_count"), "documents")
            chunks = _count(value.get("chunks_count"), "chunks")
        except (OSError, UnicodeError, json.JSONDecodeError, DiagnosticsError, ValueError):
            errors.append("documents_index_invalid")
            documents = chunks = 0
    return DocumentsDiagnostics(
        status="healthy" if not errors else "degraded",
        directory_exists=directory.is_dir(),
        index_exists=index_path.is_file(),
        documents=documents,
        chunks=chunks,
        error_codes=tuple(errors),
    )


def _build_memory(project_root: Path) -> CountedSubsystemDiagnostics:
    from memory.project_memory import get_memory_stats

    result = get_memory_stats(project_root)
    data = result.get("data") if isinstance(result, dict) else None
    if result.get("ok") and isinstance(data, dict) and type(data.get("entries")) is int:
        return CountedSubsystemDiagnostics("healthy", True, min(data["entries"], MAX_COUNT))
    return CountedSubsystemDiagnostics(
        "unavailable", False, 0, ("memory_unavailable",)
    )


def _build_terminal(project_root: Path) -> CountedSubsystemDiagnostics:
    from tools.terminal_tools import list_allowed_commands

    result = list_allowed_commands(project_root)
    commands = result.get("data") if isinstance(result, dict) else None
    if result.get("ok") and isinstance(commands, list):
        return CountedSubsystemDiagnostics("healthy", True, len(commands))
    return CountedSubsystemDiagnostics(
        "unavailable", False, 0, ("terminal_policy_error",)
    )


def _build_workflows(project_root: Path) -> WorkflowDiagnostics:
    """Inspect bounded workflow JSON without creating files or taking actions."""
    from workflows.controlled_models import CONTROLLED_SCHEMA_VERSION, ControlledWorkflowState
    from workflows.controlled_store import MAX_WORKFLOW_FILES, MAX_WORKFLOW_STATE_BYTES, migrate_legacy_state

    root = project_root / "data" / "workflows"
    errors: list[str] = []
    active_states: list[ControlledWorkflowState] = []
    history_count = 0

    def inspect(directory: Path, *, active: bool) -> None:
        nonlocal history_count
        if not directory.exists():
            return
        if directory.is_symlink() or not directory.is_dir():
            errors.append("workflow_state_invalid")
            return
        paths = sorted(directory.glob("*.json"))
        if len(paths) > MAX_WORKFLOW_FILES:
            errors.append("workflow_scan_limit_reached")
            paths = paths[:MAX_WORKFLOW_FILES]
        for path in paths:
            try:
                if not re.fullmatch(r"workflow-[0-9a-f]{32}\.json", path.name):
                    raise ValueError
                if path.is_symlink() or path.stat().st_size > MAX_WORKFLOW_STATE_BYTES:
                    raise ValueError
                raw = path.read_bytes()
                if len(raw) > MAX_WORKFLOW_STATE_BYTES:
                    raise ValueError
                data = json.loads(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError
                state = (
                    ControlledWorkflowState.from_dict(data)
                    if data.get("schema_version") == CONTROLLED_SCHEMA_VERSION
                    else migrate_legacy_state(data)
                )
                if path.stem != state.workflow_id:
                    raise ValueError
                if active:
                    active_states.append(state)
                else:
                    history_count += 1
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
                errors.append("workflow_state_invalid")

    inspect(root / "active", active=True)
    inspect(root / "history", active=False)
    if len(active_states) > 1:
        errors.append("workflow_state_invalid")
    state = active_states[0] if len(active_states) == 1 else None
    return WorkflowDiagnostics(
        status="degraded" if errors else "healthy",
        available=root.exists(),
        active_count=min(len(active_states), MAX_COUNT),
        history_count=min(history_count, MAX_COUNT),
        workflow_id=state.workflow_id if state else "",
        workflow_type=state.workflow_type if state else "",
        stage=state.status.value if state else "",
        next_actions=state.next_actions if state else (),
        confirmation_required=state.confirmation is not None if state else False,
        iteration_count=state.iteration_count if state else 0,
        rollback_available=state.rollback_available if state else False,
        workspace_drift=state.workspace_drift if state else False,
        workflow_error_codes=state.error_codes if state else (),
        error_codes=tuple(dict.fromkeys(errors)),
    )


def build_runtime_diagnostics(
    project_root: Path,
    *,
    policy: DiagnosticsPolicy | None = None,
    created_at: datetime | None = None,
    model_status: Mapping[str, object] | None = None,
    production_snapshot: Any = None,
) -> RuntimeDiagnosticsReport:
    """Build one local observer report without tools, model calls, or shell calls."""

    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a pathlib.Path")
    root = project_root.resolve()
    active_policy = policy if policy is not None else load_diagnostics_policy(root)
    errors: list[str] = []

    try:
        production = _build_production(root, production_snapshot)
    except Exception:
        production = ProductionDiagnostics("blocked", False, 1, 0, 0, ("configuration_error",))
        errors.append("diagnostics_build_failed")
    try:
        model = _build_model(root, model_status)
    except Exception:
        model = ModelDiagnostics("unavailable", "", "", "", False, False, "", ("model_unavailable",))
        errors.append("diagnostics_build_failed")
    try:
        documents = _build_documents(root)
    except Exception:
        documents = DocumentsDiagnostics("unavailable", False, False, 0, 0, ("documents_index_invalid",))
        errors.append("diagnostics_build_failed")
    try:
        memory = _build_memory(root)
    except Exception:
        memory = CountedSubsystemDiagnostics("unavailable", False, 0, ("memory_unavailable",))
        errors.append("diagnostics_build_failed")
    try:
        terminal = _build_terminal(root)
    except Exception:
        terminal = CountedSubsystemDiagnostics("unavailable", False, 0, ("terminal_policy_error",))
        errors.append("diagnostics_build_failed")
    traces = get_trace_store_status(root, active_policy)
    try:
        local_state = inspect_local_state(root, active_policy)
    except Exception:
        local_state = StateIntegrityDiagnostics(
            lock_available=False,
            stale_temporary_files=0,
            recoverable_torn_trace_tail=False,
            corrupted_generated_files=0,
            quarantined_files=0,
            scan_limit_reached=False,
            trace_store_path=active_policy.trace_store_path,
            reports_path=active_policy.doctor_reports_dir,
            quarantine_path=(
                Path(active_policy.trace_store_path).parent / "quarantine"
            ).as_posix(),
            error_codes=("state_lock_operation_failed",),
        )
        errors.append("diagnostics_build_failed")
    try:
        controlled_workflows = _build_workflows(root)
    except Exception:
        controlled_workflows = WorkflowDiagnostics(
            "unavailable", False, 0, 0, error_codes=("workflow_state_invalid",)
        )
        errors.append("diagnostics_build_failed")
    runtime_files = RuntimeFilesDiagnostics(
        smoke_test_exists=(root / "scripts" / "smoke_test.py").is_file(),
        release_policy_exists=(root / "config" / "release_policy.json").is_file(),
        diagnostics_policy_exists=(root / DIAGNOSTICS_POLICY_RELATIVE_PATH).is_file(),
    )
    if production.status == "blocked":
        overall = "blocked"
        if "production_snapshot_blocked" not in errors:
            errors.append("production_snapshot_blocked")
    elif errors or any(
        section.status != "healthy"
        for section in (model, documents, memory, terminal, traces, local_state, controlled_workflows)
    ):
        overall = "degraded"
    else:
        overall = "healthy"
    timestamp = created_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    created = timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return RuntimeDiagnosticsReport(
        schema_version=REPORT_SCHEMA_VERSION,
        version=VERSION,
        created_at=created,
        report_type="runtime_diagnostics",
        status=overall,
        error_codes=tuple(dict.fromkeys(errors)),
        production_snapshot=production,
        model_runtime=model,
        documents=documents,
        memory=memory,
        terminal_policy=terminal,
        execution_traces=traces,
        local_state=local_state,
        controlled_workflows=controlled_workflows,
        runtime_files=runtime_files,
    )


def serialize_diagnostics_report(
    report: RuntimeDiagnosticsReport,
    *,
    max_bytes: int = MAX_DOCTOR_REPORT_BYTES,
) -> str:
    """Serialize with deterministic keys and enforce the UTF-8 byte limit."""

    if not isinstance(report, RuntimeDiagnosticsReport):
        raise TypeError("report must be a RuntimeDiagnosticsReport")
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_DOCTOR_REPORT_BYTES:
        raise ValueError("max_bytes is outside the diagnostics hard limit")
    try:
        value = json.dumps(
            report.to_safe_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise DiagnosticsSerializationError("diagnostics_serialization_failed") from exc
    if len(value.encode("utf-8")) > max_bytes:
        raise DiagnosticsSerializationError("diagnostics_report_too_large")
    return value


def _retain_reports(directory: Path, keep: int) -> None:
    candidates = sorted(
        (
            item
            for item in directory.iterdir()
            if item.is_file() and _REPORT_NAME.fullmatch(item.name)
        ),
        key=lambda item: item.name,
        reverse=True,
    )[:MAX_REPORT_RETENTION_SCAN_FILES]
    for old in candidates[keep:]:
        old.unlink()


def export_diagnostics_report(
    project_root: Path,
    *,
    policy: DiagnosticsPolicy | None = None,
    report: RuntimeDiagnosticsReport | None = None,
) -> DiagnosticsExportResult:
    """Atomically export one report after an explicit caller request."""

    if not isinstance(project_root, Path):
        raise TypeError("project_root must be a pathlib.Path")
    root = project_root.resolve()
    active_policy = policy if policy is not None else load_diagnostics_policy(root)
    active_report = report if report is not None else build_runtime_diagnostics(root, policy=active_policy)
    try:
        serialized = serialize_diagnostics_report(
            active_report,
            max_bytes=active_policy.max_doctor_report_bytes,
        )
    except DiagnosticsSerializationError as exc:
        raise DiagnosticsExportError(str(exc)) from exc
    directory = root / active_policy.doctor_reports_dir
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"doctor-{timestamp}.json"
    target = directory / filename
    temporary: Path | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with GeneratedStateLock(
            root,
            directory,
            "reports",
            active_policy.lock_timeout_ms,
        ):
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=directory,
                prefix=f".{filename}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(serialized)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
            try:
                _retain_reports(directory, active_policy.retained_doctor_reports)
            except OSError:
                # The completed atomic export remains valid; retention is best effort.
                pass
    except StateLockError as exc:
        raise DiagnosticsExportError(exc.code) from exc
    except OSError as exc:
        raise DiagnosticsExportError("diagnostics_export_failed") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    relative = target.relative_to(root).as_posix()
    return DiagnosticsExportResult(relative, active_report)


def format_diagnostics_summary(report: RuntimeDiagnosticsReport) -> str:
    """Format a compact safe summary without filesystem roots or payload data."""

    if not isinstance(report, RuntimeDiagnosticsReport):
        raise TypeError("report must be a RuntimeDiagnosticsReport")
    trace = report.execution_traces
    return "\n".join(
        (
            "VEGA Doctor",
            f"Version: {report.version}",
            f"Runtime status: {report.status}",
            f"Production snapshot: {report.production_snapshot.status}",
            f"Tool execution allowed: {'YES' if report.production_snapshot.can_execute_tools else 'NO'}",
            f"Model runtime: {report.model_runtime.status}",
            f"Documents: {report.documents.status} ({report.documents.documents} documents, {report.documents.chunks} chunks)",
            f"Project memory: {report.memory.status} ({report.memory.count} entries)",
            f"Terminal policy: {report.terminal_policy.status} ({report.terminal_policy.count} commands)",
            f"Execution tracing: {'enabled' if trace.enabled else 'disabled'}",
            f"Trace store: {trace.store_path}",
            f"Trace records scanned: {trace.valid_records}",
            f"Local state integrity: {report.local_state.status}",
            f"Controlled workflows: {report.controlled_workflows.status} "
            f"({report.controlled_workflows.active_count} active, "
            f"{report.controlled_workflows.history_count} history)",
        )
    )


def format_trace_status(status: TraceStoreDiagnostics) -> str:
    if not isinstance(status, TraceStoreDiagnostics):
        raise TypeError("status must be TraceStoreDiagnostics")
    return "\n".join(
        (
            f"Execution tracing: {'enabled' if status.enabled else 'disabled'}",
            f"Store path: {status.store_path}",
            f"Active exists: {'yes' if status.active_exists else 'no'}",
            f"Active bytes: {status.active_bytes}",
            f"Backup count: {status.backup_count}",
            f"Valid records: {status.valid_records}",
            f"Corrupt records detected: {'yes' if status.corrupt_records_detected else 'no'}",
        )
    )


def format_trace_aggregate(aggregate: TraceAggregateDiagnostics) -> str:
    if not isinstance(aggregate, TraceAggregateDiagnostics):
        raise TypeError("aggregate must be TraceAggregateDiagnostics")
    errors = ", ".join(f"{key}={value}" for key, value in aggregate.error_code_counts) or "none"
    return "\n".join(
        (
            f"Scanned records: {aggregate.scanned_records}",
            f"Completed: {aggregate.completed}",
            f"Blocked: {aggregate.blocked}",
            f"Failed: {aggregate.failed}",
            f"Error codes: {errors}",
            f"Corrupt records skipped: {aggregate.corrupt_skipped}",
        )
    )


__all__ = [
    "CountedSubsystemDiagnostics",
    "DIAGNOSTICS_POLICY_RELATIVE_PATH",
    "DiagnosticsError",
    "DiagnosticsExportError",
    "DiagnosticsExportResult",
    "DiagnosticsPolicy",
    "DiagnosticsPolicyError",
    "DiagnosticsSerializationError",
    "DocumentsDiagnostics",
    "ModelDiagnostics",
    "ProductionDiagnostics",
    "RuntimeDiagnosticsReport",
    "RuntimeFilesDiagnostics",
    "StateIntegrityDiagnostics",
    "TraceAggregateDiagnostics",
    "TraceLatestDiagnostics",
    "TraceStoreDiagnostics",
    "WorkflowDiagnostics",
    "build_runtime_diagnostics",
    "export_diagnostics_report",
    "format_diagnostics_summary",
    "format_trace_aggregate",
    "format_trace_status",
    "get_trace_store_status",
    "load_diagnostics_policy",
    "serialize_diagnostics_report",
    "summarize_recent_traces",
]
