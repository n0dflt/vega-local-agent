"""Strict serializable models for workflow recovery."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from workflows.checkpoint_models import CHECKPOINT_ID_PATTERN, CheckpointReason
from workflows.models import WorkflowStatus, validate_workflow_id


class RecoveryValidationError(ValueError):
    """Recovery data does not conform to the supported schema."""


class RecoveryState(str, Enum):
    HEALTHY = "healthy"
    MISSING_ACTIVE_STATE = "missing_active_state"
    CORRUPT_ACTIVE_STATE = "corrupt_active_state"
    RECOVERABLE = "recoverable"
    NOT_RECOVERABLE = "not_recoverable"
    MULTIPLE_ACTIVE_STATES = "multiple_active_states"
    MULTIPLE_CHECKPOINT_WORKFLOWS = "multiple_checkpoint_workflows"


def _optional_string(value: object, name: str) -> str | None:
    if value is not None and (not isinstance(value, str) or not value):
        raise RecoveryValidationError(f"{name} must be a non-empty string or null.")
    return value


def _filename(value: object, name: str) -> str | None:
    value = _optional_string(value, name)
    if value is not None and ("/" in value or "\\" in value or value in {".", ".."}):
        raise RecoveryValidationError(f"{name} must be a managed filename.")
    return value


def _required_filename(value: object, name: str) -> str:
    result = _filename(value, name)
    if result is None:
        raise RecoveryValidationError(f"{name} must be a managed filename.")
    return result


def _checkpoint_id(value: object) -> str:
    if not isinstance(value, str) or not CHECKPOINT_ID_PATTERN.fullmatch(value):
        raise RecoveryValidationError("Invalid checkpoint_id.")
    return value


def _warnings(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise RecoveryValidationError("warnings must be a list of non-empty strings.")
    return list(value)


@dataclass(frozen=True, slots=True)
class RecoveryDiagnosis:
    state: RecoveryState
    workflow_id: str | None = None
    active_state_filename: str | None = None
    active_state_valid: bool = False
    checkpoint_id: str | None = None
    checkpoint_sequence: int | None = None
    checkpoint_reason: str | None = None
    checkpoint_status: WorkflowStatus | None = None
    recoverable: bool = False
    requires_confirmation: bool = False
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        try:
            state = RecoveryState(self.state)
            if self.workflow_id is not None:
                validate_workflow_id(self.workflow_id)
            filename = _filename(self.active_state_filename, "active_state_filename")
            checkpoint_id = None if self.checkpoint_id is None else _checkpoint_id(self.checkpoint_id)
            reason = None if self.checkpoint_reason is None else CheckpointReason(self.checkpoint_reason).value
            status = None if self.checkpoint_status is None else WorkflowStatus(self.checkpoint_status)
            if isinstance(self.checkpoint_sequence, bool) or (
                self.checkpoint_sequence is not None
                and (not isinstance(self.checkpoint_sequence, int) or self.checkpoint_sequence < 1)
            ):
                raise RecoveryValidationError("checkpoint_sequence must be a positive integer or null.")
            for name in ("active_state_valid", "recoverable", "requires_confirmation"):
                if not isinstance(getattr(self, name), bool):
                    raise RecoveryValidationError(f"{name} must be a boolean.")
            warnings = _warnings(self.warnings)
        except RecoveryValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise RecoveryValidationError("Malformed recovery diagnosis.") from exc
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "active_state_filename", filename)
        object.__setattr__(self, "checkpoint_id", checkpoint_id)
        object.__setattr__(self, "checkpoint_reason", reason)
        object.__setattr__(self, "checkpoint_status", status)
        object.__setattr__(self, "warnings", warnings)

    def to_dict(self) -> dict[str, Any]:
        return {name: (value.value if isinstance(value, Enum) else list(value) if name == "warnings" else value)
                for name, value in ((field, getattr(self, field)) for field in self.__dataclass_fields__)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecoveryDiagnosis":
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise RecoveryValidationError("RecoveryDiagnosis must contain exactly the supported fields.")
        try:
            return cls(**data)
        except RecoveryValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise RecoveryValidationError("Malformed recovery diagnosis.") from exc


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    workflow_id: str
    checkpoint_id: str
    restored_status: WorkflowStatus
    active_state_filename: str
    quarantine_filename: str | None
    recovered: bool
    already_recovered: bool
    requires_resume: bool
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        try:
            validate_workflow_id(self.workflow_id)
            checkpoint_id = _checkpoint_id(self.checkpoint_id)
            status = WorkflowStatus(self.restored_status)
            active = _required_filename(self.active_state_filename, "active_state_filename")
            quarantine = _filename(self.quarantine_filename, "quarantine_filename")
            for name in ("recovered", "already_recovered", "requires_resume"):
                if not isinstance(getattr(self, name), bool):
                    raise RecoveryValidationError(f"{name} must be a boolean.")
            if self.recovered == self.already_recovered or not self.requires_resume:
                raise RecoveryValidationError("Recovery result flags are inconsistent.")
            warnings = _warnings(self.warnings)
        except RecoveryValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise RecoveryValidationError("Malformed recovery result.") from exc
        object.__setattr__(self, "checkpoint_id", checkpoint_id)
        object.__setattr__(self, "restored_status", status)
        object.__setattr__(self, "active_state_filename", active)
        object.__setattr__(self, "quarantine_filename", quarantine)
        object.__setattr__(self, "warnings", warnings)

    def to_dict(self) -> dict[str, Any]:
        return {name: (value.value if isinstance(value, Enum) else list(value) if name == "warnings" else value)
                for name, value in ((field, getattr(self, field)) for field in self.__dataclass_fields__)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecoveryResult":
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise RecoveryValidationError("RecoveryResult must contain exactly the supported fields.")
        try:
            return cls(**data)
        except RecoveryValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise RecoveryValidationError("Malformed recovery result.") from exc
