"""Strict, integrity-protected workflow checkpoint models."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from workflows.controlled_models import ControlledWorkflowState
from workflows.models import WorkflowRun, WorkflowStatus, validate_workflow_id


CHECKPOINT_ID_PATTERN = re.compile(r"^checkpoint-[0-9a-f]{32}$")
CHECKPOINT_FIELDS = frozenset(
    {
        "schema_version",
        "checkpoint_id",
        "workflow_id",
        "sequence",
        "reason",
        "workflow_status",
        "workflow_payload",
        "payload_sha256",
        "patch_ids",
        "created_at",
    }
)


class CheckpointValidationError(ValueError):
    """A checkpoint does not conform to the supported schema."""


class CheckpointIntegrityError(CheckpointValidationError):
    """A checkpoint payload no longer matches its recorded digest."""


class CheckpointReason(str, Enum):
    WORKFLOW_STARTED = "workflow_started"
    STATE_TRANSITION = "state_transition"
    BEFORE_PATCH_APPLY = "before_patch_apply"
    AFTER_PATCH_APPLY = "after_patch_apply"
    VERIFICATION_RECORDED = "verification_recorded"
    REVIEW_RECORDED = "review_recorded"
    MANUAL = "manual"


def canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Return the deterministic UTF-8 representation used for payload integrity."""
    try:
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CheckpointValidationError("workflow_payload must be valid JSON.") from exc
    return rendered.encode("utf-8")


def payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload_bytes(payload)).hexdigest()


def _timezone_aware_iso8601(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise CheckpointValidationError("created_at must be a non-empty ISO-8601 string.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CheckpointValidationError("created_at must be a valid ISO-8601 string.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CheckpointValidationError("created_at must include a timezone offset.")
    return value


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CheckpointValidationError(f"{field_name} must be a positive integer.")
    return value


@dataclass(frozen=True, slots=True)
class WorkflowCheckpoint:
    schema_version: int
    checkpoint_id: str
    workflow_id: str
    sequence: int
    reason: CheckpointReason
    workflow_status: WorkflowStatus
    workflow_payload: dict[str, Any]
    payload_sha256: str
    patch_ids: list[str]
    created_at: str

    def __post_init__(self) -> None:
        try:
            schema_version = _positive_integer(self.schema_version, "schema_version")
            sequence = _positive_integer(self.sequence, "sequence")
            if not isinstance(self.checkpoint_id, str) or not CHECKPOINT_ID_PATTERN.fullmatch(self.checkpoint_id):
                raise CheckpointValidationError("Invalid checkpoint_id.")
            validate_workflow_id(self.workflow_id)
            reason = CheckpointReason(self.reason)
            status = WorkflowStatus(self.workflow_status)
            if not isinstance(self.workflow_payload, dict):
                raise CheckpointValidationError("workflow_payload must be an object.")
            restored = (
                ControlledWorkflowState.from_dict(self.workflow_payload)
                if self.workflow_payload.get("schema_version") == 2
                else WorkflowRun.from_dict(self.workflow_payload)
            )
            if restored.to_dict() != self.workflow_payload:
                raise CheckpointValidationError("workflow_payload must be a complete serialized WorkflowRun.")
            if restored.workflow_id != self.workflow_id:
                raise CheckpointValidationError("Payload workflow_id does not match checkpoint workflow_id.")
            if restored.status is not status:
                raise CheckpointValidationError("Payload status does not match checkpoint workflow_status.")
            if (
                not isinstance(self.payload_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", self.payload_sha256)
            ):
                raise CheckpointValidationError("payload_sha256 must be 64 lowercase hexadecimal characters.")
            if not isinstance(self.patch_ids, list):
                raise CheckpointValidationError("patch_ids must be a list.")
            if any(not isinstance(item, str) or not item for item in self.patch_ids):
                raise CheckpointValidationError("patch_ids must contain non-empty strings.")
            if len(set(self.patch_ids)) != len(self.patch_ids):
                raise CheckpointValidationError("patch_ids must be unique.")
            created_at = _timezone_aware_iso8601(self.created_at)
            canonical_payload_bytes(self.workflow_payload)
        except CheckpointValidationError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise CheckpointValidationError("Malformed checkpoint data.") from exc
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "workflow_status", status)
        object.__setattr__(self, "created_at", created_at)

    @classmethod
    def create(
        cls,
        run: WorkflowRun | ControlledWorkflowState,
        reason: CheckpointReason | str,
        sequence: int,
        *,
        schema_version: int = 1,
        checkpoint_id: str | None = None,
        created_at: str | None = None,
    ) -> "WorkflowCheckpoint":
        if not isinstance(run, (WorkflowRun, ControlledWorkflowState)):
            raise CheckpointValidationError("run must be a supported workflow state")
        try:
            normalized_reason = CheckpointReason(reason)
        except (TypeError, ValueError) as exc:
            raise CheckpointValidationError("Unsupported checkpoint reason.") from exc
        payload = run.to_dict()
        patch_ids: list[str] = []
        if isinstance(run, ControlledWorkflowState):
            candidates = [item.patch_id for item in run.patches]
        else:
            candidates = [
                (run.patch or {}).get("patch_id"),
                run.artifacts.get("requested_patch_id"),
                *(item.get("patch_id") for item in run.test_fix_iterations if isinstance(item, dict)),
            ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate and candidate not in patch_ids:
                patch_ids.append(candidate)
        from workflows.models import utc_now

        return cls(
            schema_version=schema_version,
            checkpoint_id=checkpoint_id if checkpoint_id is not None else f"checkpoint-{uuid4().hex}",
            workflow_id=run.workflow_id,
            sequence=sequence,
            reason=normalized_reason,
            workflow_status=run.status,
            workflow_payload=payload,
            payload_sha256=payload_sha256(payload),
            patch_ids=patch_ids,
            created_at=created_at if created_at is not None else utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "checkpoint_id": self.checkpoint_id,
            "workflow_id": self.workflow_id,
            "sequence": self.sequence,
            "reason": self.reason.value,
            "workflow_status": self.workflow_status.value,
            "workflow_payload": json.loads(canonical_payload_bytes(self.workflow_payload)),
            "payload_sha256": self.payload_sha256,
            "patch_ids": list(self.patch_ids),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowCheckpoint":
        if not isinstance(data, dict) or set(data) != CHECKPOINT_FIELDS:
            raise CheckpointValidationError("Checkpoint must contain exactly the supported fields.")
        try:
            return cls(**data)
        except CheckpointValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise CheckpointValidationError("Malformed checkpoint data.") from exc

    def verify_integrity(self) -> None:
        actual = payload_sha256(self.workflow_payload)
        if not hmac.compare_digest(actual, self.payload_sha256):
            raise CheckpointIntegrityError("Checkpoint workflow payload integrity check failed.")
