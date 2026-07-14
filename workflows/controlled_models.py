"""Strict, payload-free models for v2.13 controlled coding workflows."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, ClassVar
from uuid import uuid4

from workflows.models import WorkflowStatus, validate_workflow_id


CONTROLLED_SCHEMA_VERSION = 2
MAX_TASK_CHARS = 2_000
MAX_ITERATIONS = 3
MAX_RELATED_FILES = 24
MAX_TEST_RESULTS = 3
MAX_REVIEW_FILES = 64
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
TEST_GROUP_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMMAND_ID_PATTERN = TEST_GROUP_PATTERN
SAFE_PATH_PATTERN = re.compile(r"^[^\x00-\x1f]{1,240}$")

WORKFLOW_TYPES = frozenset({"bug-fix", "feature", "refactor", "test", "review"})
CONFIRMATION_ACTIONS = frozenset(
    {"patch_application", "test_execution", "patch_rollback"}
)
NEXT_ACTIONS = frozenset(
    {
        "attach_patch",
        "approve_patch",
        "approve_tests",
        "cancel",
        "resume",
        "rollback",
        "show",
    }
)
SAFE_ERROR_CODES = frozenset(
    {
        "confirmation_binding_invalid",
        "confirmation_replayed",
        "iteration_limit_reached",
        "lock_timeout",
        "managed_patch_invalid",
        "patch_apply_failed",
        "patch_identity_changed",
        "permission_policy_error",
        "review_failed",
        "rollback_refused",
        "state_incompatible",
        "state_invalid",
        "state_write_failed",
        "test_configuration_missing",
        "test_execution_failed",
        "workspace_drift",
    }
)


class ControlledWorkflowValidationError(ValueError):
    """Controlled state does not satisfy the closed schema."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(value: object, field: str, *, empty: bool = False) -> str:
    if empty and value == "":
        return ""
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise ControlledWorkflowValidationError(f"{field} must be a SHA-256 digest")
    return value


def _iso8601(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ControlledWorkflowValidationError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ControlledWorkflowValidationError(f"{field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ControlledWorkflowValidationError(f"{field} must include an offset")
    return value


def _safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not SAFE_PATH_PATTERN.fullmatch(value):
        raise ControlledWorkflowValidationError(f"{field} must be a bounded relative path")
    normalized = value.replace("\\", "/")
    if (
        normalized.startswith(("/", "//"))
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise ControlledWorkflowValidationError(f"{field} must be a safe relative path")
    blocked = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "data", "logs"}
    if any(part.lower() in blocked for part in normalized.split("/")):
        raise ControlledWorkflowValidationError(f"{field} uses a protected directory")
    return normalized


def task_digest(task: str) -> tuple[str, int]:
    if not isinstance(task, str):
        raise ControlledWorkflowValidationError("task must be text")
    normalized = task.strip()
    if not normalized or len(normalized) > MAX_TASK_CHARS:
        raise ControlledWorkflowValidationError(
            f"task must contain 1 to {MAX_TASK_CHARS} characters"
        )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest(), len(normalized)


@dataclass(frozen=True, slots=True)
class InvestigationEvidence:
    related_files: tuple[str, ...]
    inspected_files: int
    content_matches: int
    diagnosis_code: str
    reproduction_code: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"related_files", "inspected_files", "content_matches", "diagnosis_code", "reproduction_code"}
    )

    def __post_init__(self) -> None:
        if not isinstance(self.related_files, tuple) or len(self.related_files) > MAX_RELATED_FILES:
            raise ControlledWorkflowValidationError("related_files exceeds its bound")
        object.__setattr__(
            self,
            "related_files",
            tuple(_safe_relative(item, "related_files") for item in self.related_files),
        )
        for name in ("inspected_files", "content_matches"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 10_000:
                raise ControlledWorkflowValidationError(f"{name} is outside its bound")
        if self.diagnosis_code not in {"related_evidence_found", "insufficient_evidence"}:
            raise ControlledWorkflowValidationError("invalid diagnosis_code")
        if self.reproduction_code not in {"not_configured", "plan_available"}:
            raise ControlledWorkflowValidationError("invalid reproduction_code")

    def to_dict(self) -> dict[str, object]:
        return {
            "related_files": list(self.related_files),
            "inspected_files": self.inspected_files,
            "content_matches": self.content_matches,
            "diagnosis_code": self.diagnosis_code,
            "reproduction_code": self.reproduction_code,
        }

    @classmethod
    def from_dict(cls, data: object) -> "InvestigationEvidence":
        if not isinstance(data, dict) or set(data) != cls._FIELDS:
            raise ControlledWorkflowValidationError("invalid investigation fields")
        return cls(
            tuple(data["related_files"]),
            data["inspected_files"],
            data["content_matches"],
            data["diagnosis_code"],
            data["reproduction_code"],
        )


@dataclass(frozen=True, slots=True)
class PatchEvidence:
    patch_id: str
    identity_sha256: str
    target_path: str
    original_sha256: str
    proposed_sha256: str
    status: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"patch_id", "identity_sha256", "target_path", "original_sha256", "proposed_sha256", "status"}
    )

    def __post_init__(self) -> None:
        if not isinstance(self.patch_id, str) or not PATCH_ID_PATTERN.fullmatch(self.patch_id):
            raise ControlledWorkflowValidationError("invalid patch_id")
        _sha(self.identity_sha256, "identity_sha256")
        object.__setattr__(self, "target_path", _safe_relative(self.target_path, "target_path"))
        _sha(self.original_sha256, "original_sha256")
        _sha(self.proposed_sha256, "proposed_sha256")
        if self.status not in {"pending", "applied", "rolled_back"}:
            raise ControlledWorkflowValidationError("invalid patch status")

    def to_dict(self) -> dict[str, str]:
        return {
            "patch_id": self.patch_id,
            "identity_sha256": self.identity_sha256,
            "target_path": self.target_path,
            "original_sha256": self.original_sha256,
            "proposed_sha256": self.proposed_sha256,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: object) -> "PatchEvidence":
        if not isinstance(data, dict) or set(data) != cls._FIELDS:
            raise ControlledWorkflowValidationError("invalid patch evidence fields")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class TestOutcome:
    group_id: str
    command_id: str
    passed: bool
    returncode: int | None
    timed_out: bool
    duration_ms: int
    outcome_code: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"group_id", "command_id", "passed", "returncode", "timed_out", "duration_ms", "outcome_code"}
    )

    def __post_init__(self) -> None:
        if not isinstance(self.group_id, str) or not TEST_GROUP_PATTERN.fullmatch(self.group_id):
            raise ControlledWorkflowValidationError("invalid test group")
        if not isinstance(self.command_id, str) or not COMMAND_ID_PATTERN.fullmatch(self.command_id):
            raise ControlledWorkflowValidationError("invalid test command")
        if type(self.passed) is not bool or type(self.timed_out) is not bool:
            raise ControlledWorkflowValidationError("test flags must be boolean")
        if self.returncode is not None and (type(self.returncode) is not int or not -1 <= self.returncode <= 255):
            raise ControlledWorkflowValidationError("invalid returncode")
        if type(self.duration_ms) is not int or not 0 <= self.duration_ms <= 3_600_000:
            raise ControlledWorkflowValidationError("invalid test duration")
        if self.outcome_code not in {"passed", "failed", "timed_out", "not_started"}:
            raise ControlledWorkflowValidationError("invalid test outcome code")

    def to_dict(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "command_id": self.command_id,
            "passed": self.passed,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "outcome_code": self.outcome_code,
        }

    @classmethod
    def from_dict(cls, data: object) -> "TestOutcome":
        if not isinstance(data, dict) or set(data) != cls._FIELDS:
            raise ControlledWorkflowValidationError("invalid test outcome fields")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class ReviewFindingEvidence:
    code: str
    severity: str
    file: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"code", "severity", "file"})

    def __post_init__(self) -> None:
        if self.code not in {"conflict_marker", "dynamic_execution", "shell_execution", "credential_marker"}:
            raise ControlledWorkflowValidationError("invalid review finding code")
        if self.severity not in {"medium", "high", "critical"}:
            raise ControlledWorkflowValidationError("invalid review severity")
        object.__setattr__(self, "file", _safe_relative(self.file, "review file"))

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "file": self.file}

    @classmethod
    def from_dict(cls, data: object) -> "ReviewFindingEvidence":
        if not isinstance(data, dict) or set(data) != cls._FIELDS:
            raise ControlledWorkflowValidationError("invalid review finding fields")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class ReviewEvidence:
    scope: str
    diff_sha256: str
    diff_bytes: int
    truncated: bool
    files: tuple[str, ...]
    findings: tuple[ReviewFindingEvidence, ...]

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"scope", "diff_sha256", "diff_bytes", "truncated", "files", "findings"}
    )

    def __post_init__(self) -> None:
        if self.scope not in {"unstaged", "staged"}:
            raise ControlledWorkflowValidationError("invalid review scope")
        _sha(self.diff_sha256, "diff_sha256")
        if type(self.diff_bytes) is not int or not 0 <= self.diff_bytes <= 100_000:
            raise ControlledWorkflowValidationError("invalid diff size")
        if type(self.truncated) is not bool:
            raise ControlledWorkflowValidationError("truncated must be boolean")
        if not isinstance(self.files, tuple) or len(self.files) > MAX_REVIEW_FILES:
            raise ControlledWorkflowValidationError("review files exceed their bound")
        object.__setattr__(self, "files", tuple(_safe_relative(item, "review file") for item in self.files))
        if not isinstance(self.findings, tuple) or len(self.findings) > 100:
            raise ControlledWorkflowValidationError("review findings exceed their bound")
        if any(not isinstance(item, ReviewFindingEvidence) for item in self.findings):
            raise ControlledWorkflowValidationError("invalid review finding")

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "diff_sha256": self.diff_sha256,
            "diff_bytes": self.diff_bytes,
            "truncated": self.truncated,
            "files": list(self.files),
            "findings": [item.to_dict() for item in self.findings],
        }

    @classmethod
    def from_dict(cls, data: object) -> "ReviewEvidence":
        if not isinstance(data, dict) or set(data) != cls._FIELDS:
            raise ControlledWorkflowValidationError("invalid review evidence fields")
        return cls(
            data["scope"],
            data["diff_sha256"],
            data["diff_bytes"],
            data["truncated"],
            tuple(data["files"]),
            tuple(ReviewFindingEvidence.from_dict(item) for item in data["findings"]),
        )


def _binding_digest(values: dict[str, object]) -> str:
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfirmationBinding:
    workflow_id: str
    stage: str
    action: str
    patch_identity: str
    workspace_revision: str
    test_group: str
    command_id: str
    state_revision: int
    created_at: str
    binding_sha256: str

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "workflow_id", "stage", "action", "patch_identity", "workspace_revision",
            "test_group", "command_id", "state_revision", "created_at", "binding_sha256",
        }
    )

    def __post_init__(self) -> None:
        validate_workflow_id(self.workflow_id)
        WorkflowStatus(self.stage)
        if self.action not in CONFIRMATION_ACTIONS:
            raise ControlledWorkflowValidationError("invalid confirmation action")
        _sha(self.patch_identity, "patch_identity", empty=True)
        _sha(self.workspace_revision, "workspace_revision")
        if self.test_group and not TEST_GROUP_PATTERN.fullmatch(self.test_group):
            raise ControlledWorkflowValidationError("invalid confirmation test group")
        if self.command_id and not COMMAND_ID_PATTERN.fullmatch(self.command_id):
            raise ControlledWorkflowValidationError("invalid confirmation command")
        if type(self.state_revision) is not int or self.state_revision < 1:
            raise ControlledWorkflowValidationError("invalid confirmation state revision")
        _iso8601(self.created_at, "confirmation created_at")
        _sha(self.binding_sha256, "binding_sha256")
        expected = _binding_digest(self._unsigned_dict())
        if not hmac.compare_digest(expected, self.binding_sha256):
            raise ControlledWorkflowValidationError("confirmation binding integrity failed")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "stage": self.stage,
            "action": self.action,
            "patch_identity": self.patch_identity,
            "workspace_revision": self.workspace_revision,
            "test_group": self.test_group,
            "command_id": self.command_id,
            "state_revision": self.state_revision,
            "created_at": self.created_at,
        }

    @classmethod
    def create(
        cls,
        *,
        workflow_id: str,
        stage: WorkflowStatus,
        action: str,
        patch_identity: str,
        workspace_revision: str,
        test_group: str = "",
        command_id: str = "",
        state_revision: int,
    ) -> "ConfirmationBinding":
        values = {
            "workflow_id": workflow_id,
            "stage": stage.value,
            "action": action,
            "patch_identity": patch_identity,
            "workspace_revision": workspace_revision,
            "test_group": test_group,
            "command_id": command_id,
            "state_revision": state_revision,
            "created_at": utc_now(),
        }
        return cls(**values, binding_sha256=_binding_digest(values))

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "binding_sha256": self.binding_sha256}

    @classmethod
    def from_dict(cls, data: object) -> "ConfirmationBinding":
        if not isinstance(data, dict) or set(data) != cls._FIELDS:
            raise ControlledWorkflowValidationError("invalid confirmation fields")
        return cls(**data)


@dataclass(frozen=True, slots=True)
class ControlledWorkflowState:
    schema_version: int
    workflow_id: str
    workflow_type: str
    status: WorkflowStatus
    task_sha256: str
    task_chars: int
    created_at: str
    updated_at: str
    revision: int
    next_actions: tuple[str, ...]
    investigation: InvestigationEvidence | None = None
    patches: tuple[PatchEvidence, ...] = ()
    confirmation: ConfirmationBinding | None = None
    test_group: str = ""
    test_command_id: str = ""
    test_results: tuple[TestOutcome, ...] = ()
    iteration_count: int = 0
    max_iterations: int = MAX_ITERATIONS
    rollback_available: bool = False
    workspace_revision: str = ""
    workspace_drift: bool = False
    review: ReviewEvidence | None = None
    error_codes: tuple[str, ...] = ()
    migrated_from_schema: int | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version", "workflow_id", "workflow_type", "status", "task_sha256",
            "task_chars", "created_at", "updated_at", "revision", "next_actions",
            "investigation", "patches", "confirmation", "test_group", "test_command_id",
            "test_results", "iteration_count", "max_iterations", "rollback_available",
            "workspace_revision", "workspace_drift", "review", "error_codes",
            "migrated_from_schema",
        }
    )

    def __post_init__(self) -> None:
        if self.schema_version != CONTROLLED_SCHEMA_VERSION:
            raise ControlledWorkflowValidationError("unsupported controlled workflow schema")
        validate_workflow_id(self.workflow_id)
        if self.workflow_type not in WORKFLOW_TYPES:
            raise ControlledWorkflowValidationError("invalid workflow_type")
        object.__setattr__(self, "status", WorkflowStatus(self.status))
        _sha(self.task_sha256, "task_sha256")
        if type(self.task_chars) is not int or not 1 <= self.task_chars <= MAX_TASK_CHARS:
            raise ControlledWorkflowValidationError("invalid task_chars")
        _iso8601(self.created_at, "created_at")
        _iso8601(self.updated_at, "updated_at")
        if type(self.revision) is not int or self.revision < 1:
            raise ControlledWorkflowValidationError("invalid revision")
        if not isinstance(self.next_actions, tuple) or any(item not in NEXT_ACTIONS for item in self.next_actions):
            raise ControlledWorkflowValidationError("invalid next_actions")
        if len(set(self.next_actions)) != len(self.next_actions):
            raise ControlledWorkflowValidationError("next_actions contains duplicates")
        if self.investigation is not None and not isinstance(self.investigation, InvestigationEvidence):
            raise ControlledWorkflowValidationError("invalid investigation")
        if not isinstance(self.patches, tuple) or len(self.patches) > MAX_ITERATIONS:
            raise ControlledWorkflowValidationError("patch history exceeds iteration limit")
        if any(not isinstance(item, PatchEvidence) for item in self.patches):
            raise ControlledWorkflowValidationError("invalid patch history")
        if self.confirmation is not None:
            if not isinstance(self.confirmation, ConfirmationBinding):
                raise ControlledWorkflowValidationError("invalid confirmation")
            if self.confirmation.workflow_id != self.workflow_id:
                raise ControlledWorkflowValidationError("confirmation belongs to another workflow")
        if self.test_group and not TEST_GROUP_PATTERN.fullmatch(self.test_group):
            raise ControlledWorkflowValidationError("invalid test_group")
        if self.test_command_id and not COMMAND_ID_PATTERN.fullmatch(self.test_command_id):
            raise ControlledWorkflowValidationError("invalid test_command_id")
        if not isinstance(self.test_results, tuple) or len(self.test_results) > MAX_TEST_RESULTS:
            raise ControlledWorkflowValidationError("test results exceed iteration limit")
        if any(not isinstance(item, TestOutcome) for item in self.test_results):
            raise ControlledWorkflowValidationError("invalid test results")
        if type(self.iteration_count) is not int or not 0 <= self.iteration_count <= MAX_ITERATIONS:
            raise ControlledWorkflowValidationError("invalid iteration_count")
        if self.max_iterations != MAX_ITERATIONS:
            raise ControlledWorkflowValidationError("compiled max_iterations is exactly 3")
        if type(self.rollback_available) is not bool or type(self.workspace_drift) is not bool:
            raise ControlledWorkflowValidationError("state flags must be boolean")
        _sha(self.workspace_revision, "workspace_revision", empty=True)
        if self.review is not None and not isinstance(self.review, ReviewEvidence):
            raise ControlledWorkflowValidationError("invalid review")
        if not isinstance(self.error_codes, tuple) or any(code not in SAFE_ERROR_CODES for code in self.error_codes):
            raise ControlledWorkflowValidationError("invalid error code")
        if self.migrated_from_schema not in {None, 1}:
            raise ControlledWorkflowValidationError("invalid migration source")

    @classmethod
    def create(cls, workflow_type: str, task: str, workspace_revision: str) -> "ControlledWorkflowState":
        digest, length = task_digest(task)
        now = utc_now()
        return cls(
            schema_version=CONTROLLED_SCHEMA_VERSION,
            workflow_id=f"workflow-{uuid4().hex}",
            workflow_type=workflow_type,
            status=WorkflowStatus.PLANNED,
            task_sha256=digest,
            task_chars=length,
            created_at=now,
            updated_at=now,
            revision=1,
            next_actions=("resume", "cancel", "show"),
            workspace_revision=workspace_revision,
        )

    def evolve(self, **changes: object) -> "ControlledWorkflowState":
        changes.setdefault("updated_at", utc_now())
        changes.setdefault("revision", self.revision + 1)
        return replace(self, **changes)

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.ROLLED_BACK,
        }

    @property
    def patch(self) -> dict[str, object] | None:
        return self.patches[-1].to_dict() if self.patches else None

    @property
    def changed_files(self) -> list[str]:
        return [item.target_path for item in self.patches if item.status == "applied"]

    @property
    def task(self) -> str:
        return "[redacted]"

    @property
    def required_confirmations(self) -> list[str]:
        return [] if self.confirmation is None else [self.confirmation.action]

    @property
    def verification_results(self) -> list[dict[str, object]]:
        return [item.to_dict() for item in self.test_results]

    @property
    def test_fix_iterations(self) -> list[dict[str, object]]:
        return [
            {"attempt": index + 1, "patch_id": patch.patch_id}
            for index, patch in enumerate(self.patches)
        ]

    @property
    def review_results(self) -> list[dict[str, object]]:
        return [] if self.review is None else [self.review.to_dict()]

    @property
    def error(self) -> str:
        return ",".join(self.error_codes)

    @property
    def report(self) -> str:
        return (
            f"Workflow {self.workflow_id}: {self.workflow_type}; stage={self.status.value}; "
            f"iterations={self.iteration_count}/{self.max_iterations}; "
            f"tests={len(self.test_results)}; rollback={str(self.rollback_available).lower()}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "workflow_type": self.workflow_type,
            "status": self.status.value,
            "task_sha256": self.task_sha256,
            "task_chars": self.task_chars,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "next_actions": list(self.next_actions),
            "investigation": None if self.investigation is None else self.investigation.to_dict(),
            "patches": [item.to_dict() for item in self.patches],
            "confirmation": None if self.confirmation is None else self.confirmation.to_dict(),
            "test_group": self.test_group,
            "test_command_id": self.test_command_id,
            "test_results": [item.to_dict() for item in self.test_results],
            "iteration_count": self.iteration_count,
            "max_iterations": self.max_iterations,
            "rollback_available": self.rollback_available,
            "workspace_revision": self.workspace_revision,
            "workspace_drift": self.workspace_drift,
            "review": None if self.review is None else self.review.to_dict(),
            "error_codes": list(self.error_codes),
            "migrated_from_schema": self.migrated_from_schema,
        }

    @classmethod
    def from_dict(cls, data: object) -> "ControlledWorkflowState":
        if not isinstance(data, dict) or set(data) != cls._FIELDS:
            raise ControlledWorkflowValidationError("controlled state fields do not match schema")
        return cls(
            schema_version=data["schema_version"],
            workflow_id=data["workflow_id"],
            workflow_type=data["workflow_type"],
            status=WorkflowStatus(data["status"]),
            task_sha256=data["task_sha256"],
            task_chars=data["task_chars"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            revision=data["revision"],
            next_actions=tuple(data["next_actions"]),
            investigation=None if data["investigation"] is None else InvestigationEvidence.from_dict(data["investigation"]),
            patches=tuple(PatchEvidence.from_dict(item) for item in data["patches"]),
            confirmation=None if data["confirmation"] is None else ConfirmationBinding.from_dict(data["confirmation"]),
            test_group=data["test_group"],
            test_command_id=data["test_command_id"],
            test_results=tuple(TestOutcome.from_dict(item) for item in data["test_results"]),
            iteration_count=data["iteration_count"],
            max_iterations=data["max_iterations"],
            rollback_available=data["rollback_available"],
            workspace_revision=data["workspace_revision"],
            workspace_drift=data["workspace_drift"],
            review=None if data["review"] is None else ReviewEvidence.from_dict(data["review"]),
            error_codes=tuple(data["error_codes"]),
            migrated_from_schema=data["migrated_from_schema"],
        )


__all__ = [
    "CONFIRMATION_ACTIONS",
    "CONTROLLED_SCHEMA_VERSION",
    "ConfirmationBinding",
    "ControlledWorkflowState",
    "ControlledWorkflowValidationError",
    "InvestigationEvidence",
    "MAX_ITERATIONS",
    "PatchEvidence",
    "ReviewEvidence",
    "ReviewFindingEvidence",
    "SAFE_ERROR_CODES",
    "TestOutcome",
    "task_digest",
]
