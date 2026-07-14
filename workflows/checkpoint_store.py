"""Atomic filesystem storage for immutable workflow checkpoints."""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from workflows.checkpoint_models import (
    CHECKPOINT_ID_PATTERN,
    CheckpointIntegrityError,
    CheckpointReason,
    CheckpointValidationError,
    WorkflowCheckpoint,
    canonical_payload_bytes,
)
from workflows.models import WorkflowRun, validate_workflow_id


_PROCESS_LOCK = threading.RLock()

_SENSITIVE_KEY_PARTS = frozenset(
    {"password", "passwd", "secret", "credentials", "credential", "environment", "env"}
)
_SENSITIVE_KEY_PAIRS = frozenset(
    {
        ("access", "token"),
        ("refresh", "token"),
        ("api", "token"),
        ("auth", "token"),
        ("api", "key"),
        ("client", "secret"),
        ("private", "key"),
    }
)
_SENSITIVE_COLLAPSED_KEYS = frozenset(
    {
        "password",
        "passwd",
        "accesstoken",
        "refreshtoken",
        "apitoken",
        "authtoken",
        "apikey",
        "secret",
        "clientsecret",
        "privatekey",
        "credentials",
        "credential",
        "environment",
        "env",
    }
)


class CheckpointStorageError(RuntimeError):
    """Checkpoint storage cannot safely complete an operation."""


class CheckpointNotFoundError(CheckpointStorageError):
    """A requested checkpoint does not exist."""


class CheckpointLimitError(CheckpointStorageError):
    """A configured checkpoint safety limit was reached."""


@dataclass(frozen=True, slots=True)
class CheckpointPolicy:
    schema_version: int
    hash_algorithm: str
    max_checkpoints_per_workflow: int
    max_payload_bytes: int
    fail_closed_on_invalid_checkpoint: bool
    allowed_reasons: frozenset[CheckpointReason]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckpointPolicy":
        fields = {
            "schema_version",
            "hash_algorithm",
            "max_checkpoints_per_workflow",
            "max_payload_bytes",
            "fail_closed_on_invalid_checkpoint",
            "allowed_reasons",
        }
        if not isinstance(data, dict) or set(data) != fields:
            raise CheckpointStorageError("Checkpoint policy has missing or unknown fields.")
        try:
            schema = data["schema_version"]
            count = data["max_checkpoints_per_workflow"]
            size = data["max_payload_bytes"]
            if isinstance(schema, bool) or not isinstance(schema, int) or schema != 1:
                raise CheckpointStorageError("Unsupported checkpoint policy schema_version.")
            if data["hash_algorithm"] != "sha256":
                raise CheckpointStorageError("Unsupported checkpoint hash algorithm.")
            if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10_000:
                raise CheckpointStorageError("max_checkpoints_per_workflow is outside the safe range.")
            if isinstance(size, bool) or not isinstance(size, int) or not 1_024 <= size <= 100 * 1024 * 1024:
                raise CheckpointStorageError("max_payload_bytes is outside the safe range.")
            fail_closed = data["fail_closed_on_invalid_checkpoint"]
            if not isinstance(fail_closed, bool) or not fail_closed:
                raise CheckpointStorageError("Invalid checkpoints must fail closed.")
            raw_reasons = data["allowed_reasons"]
            if not isinstance(raw_reasons, list) or not raw_reasons:
                raise CheckpointStorageError("allowed_reasons must be a non-empty list.")
            if any(not isinstance(item, str) or not item for item in raw_reasons):
                raise CheckpointStorageError("allowed_reasons entries must be non-empty strings.")
            if len(set(raw_reasons)) != len(raw_reasons):
                raise CheckpointStorageError("allowed_reasons must contain unique values.")
            reasons = frozenset(CheckpointReason(item) for item in raw_reasons)
        except CheckpointStorageError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise CheckpointStorageError("Policy contains an unsupported checkpoint reason.") from exc
        return cls(schema, "sha256", count, size, fail_closed, reasons)


class CheckpointStore:
    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.policy = self._load_policy(self.project_root / "config" / "checkpoint_policy.json")
        self.root = self.project_root / "data" / "checkpoints"
        self.active_dir = self.root / "active"
        self.history_dir = self.root / "history"
        self.quarantine_dir = self.root / "quarantine"
        for directory in (self.active_dir, self.history_dir, self.quarantine_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._lock = _PROCESS_LOCK

    @staticmethod
    def _load_policy(path: Path) -> CheckpointPolicy:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointStorageError("Checkpoint policy could not be loaded.") from exc
        return CheckpointPolicy.from_dict(data)

    def _locations(self, include_history: bool) -> tuple[Path, ...]:
        return (self.active_dir, self.history_dir) if include_history else (self.active_dir,)

    def _load_path(self, path: Path) -> WorkflowCheckpoint:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            checkpoint = WorkflowCheckpoint.from_dict(raw)
            if path.stem != checkpoint.checkpoint_id:
                raise CheckpointValidationError("Checkpoint filename does not match its ID.")
            checkpoint.verify_integrity()
            if checkpoint.schema_version != self.policy.schema_version:
                raise CheckpointStorageError("Checkpoint schema_version is not allowed by policy.")
            if checkpoint.reason not in self.policy.allowed_reasons:
                raise CheckpointStorageError("Checkpoint reason is not allowed by policy.")
            if len(canonical_payload_bytes(checkpoint.workflow_payload)) > self.policy.max_payload_bytes:
                raise CheckpointStorageError("Checkpoint payload exceeds max_payload_bytes.")
            self._validate_payload_safety(checkpoint.workflow_payload)
            return checkpoint
        except CheckpointStorageError:
            raise
        except (OSError, json.JSONDecodeError, CheckpointValidationError, CheckpointIntegrityError) as exc:
            raise CheckpointStorageError(f"Invalid checkpoint file: {path.name}.") from exc

    @staticmethod
    def _key_parts(key: str) -> tuple[str, ...]:
        separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
        return tuple(part for part in re.split(r"[^A-Za-z0-9]+", separated.lower()) if part)

    def _validate_payload_safety(self, payload: dict[str, Any]) -> None:
        def inspect(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise CheckpointStorageError("Workflow payload dictionary keys must be strings.")
                    parts = self._key_parts(key)
                    collapsed = "".join(parts)
                    if (
                        collapsed in _SENSITIVE_COLLAPSED_KEYS
                        or any(part in _SENSITIVE_KEY_PARTS for part in parts)
                        or any(pair in zip(parts, parts[1:]) for pair in _SENSITIVE_KEY_PAIRS)
                    ):
                        raise CheckpointStorageError(f"Workflow payload contains a sensitive key: {key!r}.")
                    inspect(item)
                return
            if isinstance(value, list):
                for item in value:
                    inspect(item)
                return
            if isinstance(value, str):
                windows_path = PureWindowsPath(value)
                posix_path = PurePosixPath(value)
                if os.name == "nt" and windows_path.is_absolute():
                    resolved = Path(value).resolve()
                    if not resolved.is_relative_to(self.project_root):
                        raise CheckpointStorageError("Workflow payload contains an external absolute path.")
                elif os.name == "nt" and posix_path.is_absolute():
                    raise CheckpointStorageError("Workflow payload contains an external absolute path.")
                elif os.name != "nt" and posix_path.is_absolute():
                    resolved = Path(value).resolve()
                    if not resolved.is_relative_to(self.project_root):
                        raise CheckpointStorageError("Workflow payload contains an external absolute path.")
                elif os.name != "nt" and windows_path.is_absolute():
                    raise CheckpointStorageError("Workflow payload contains an external absolute path.")

        if not isinstance(payload, dict):
            raise CheckpointStorageError("Workflow payload must be an object.")
        inspect(payload)

    def _all_for_workflow(self, workflow_id: str) -> list[WorkflowCheckpoint]:
        return self.list_for_workflow(workflow_id, include_history=True)

    def create(self, run: WorkflowRun, reason: CheckpointReason | str) -> WorkflowCheckpoint:
        from workflows.controlled_models import ControlledWorkflowState

        if not isinstance(run, (WorkflowRun, ControlledWorkflowState)):
            raise CheckpointStorageError("run must be a supported workflow state")
        try:
            normalized_reason = CheckpointReason(reason)
        except (TypeError, ValueError) as exc:
            raise CheckpointStorageError("Unsupported checkpoint reason.") from exc
        if normalized_reason not in self.policy.allowed_reasons:
            raise CheckpointStorageError("Checkpoint reason is disabled by policy.")
        with self._lock:
            existing = self._all_for_workflow(run.workflow_id)
            if len(existing) >= self.policy.max_checkpoints_per_workflow:
                raise CheckpointLimitError("Maximum checkpoints per workflow reached.")
            sequence = max((item.sequence for item in existing), default=0) + 1
            checkpoint = WorkflowCheckpoint.create(run, normalized_reason, sequence)
            self._validate_payload_safety(checkpoint.workflow_payload)
            serialized = json.dumps(checkpoint.to_dict(), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            if len(canonical_payload_bytes(checkpoint.workflow_payload)) > self.policy.max_payload_bytes:
                raise CheckpointLimitError("Checkpoint payload exceeds max_payload_bytes.")
            destination = self.active_dir / f"{checkpoint.checkpoint_id}.json"
            if any((directory / destination.name).exists() for directory in self._locations(True)):
                raise CheckpointStorageError("Checkpoint already exists.")
            temporary = destination.with_name(f".{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(serialized)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                if destination.exists():
                    raise CheckpointStorageError("Checkpoint already exists.")
                os.replace(temporary, destination)
            except (OSError, CheckpointStorageError) as exc:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                if isinstance(exc, CheckpointStorageError):
                    raise
                raise CheckpointStorageError("Checkpoint write failed.") from exc
            return checkpoint

    def get(self, checkpoint_id: str, include_history: bool = True) -> WorkflowCheckpoint:
        if not isinstance(checkpoint_id, str) or not CHECKPOINT_ID_PATTERN.fullmatch(checkpoint_id):
            raise CheckpointNotFoundError("Invalid checkpoint ID.")
        with self._lock:
            matches = [directory / f"{checkpoint_id}.json" for directory in self._locations(include_history)]
            existing = [path for path in matches if path.is_file()]
            if not existing:
                raise CheckpointNotFoundError(f"Checkpoint not found: {checkpoint_id}.")
            if len(existing) != 1:
                raise CheckpointStorageError("Duplicate checkpoint IDs exist in managed storage.")
            return self._load_path(existing[0])

    def list_for_workflow(self, workflow_id: str, include_history: bool = False) -> list[WorkflowCheckpoint]:
        try:
            validate_workflow_id(workflow_id)
        except ValueError as exc:
            raise CheckpointStorageError("Invalid workflow ID.") from exc
        with self._lock:
            checkpoints: list[WorkflowCheckpoint] = []
            seen: set[str] = set()
            for directory in self._locations(include_history):
                for path in sorted(directory.glob("*.json")):
                    checkpoint = self._load_path(path)
                    if checkpoint.checkpoint_id in seen:
                        raise CheckpointStorageError("Duplicate checkpoint IDs exist in managed storage.")
                    seen.add(checkpoint.checkpoint_id)
                    if checkpoint.workflow_id == workflow_id:
                        checkpoints.append(checkpoint)
            return sorted(checkpoints, key=lambda item: (item.sequence, item.created_at, item.checkpoint_id))

    def latest(self, workflow_id: str, include_history: bool = False) -> WorkflowCheckpoint | None:
        checkpoints = self.list_for_workflow(workflow_id, include_history)
        return checkpoints[-1] if checkpoints else None

    def archive_workflow(self, workflow_id: str) -> int:
        try:
            validate_workflow_id(workflow_id)
        except ValueError as exc:
            raise CheckpointStorageError("Invalid workflow ID.") from exc
        with self._lock:
            matches: list[Path] = []
            for path in sorted(self.active_dir.glob("*.json")):
                checkpoint = self._load_path(path)
                if checkpoint.workflow_id == workflow_id:
                    destination = self.history_dir / path.name
                    if destination.exists():
                        raise CheckpointStorageError("Archive destination already exists.")
                    matches.append(path)
            moved = 0
            for source in matches:
                destination = self.history_dir / source.name
                if destination.exists():
                    raise CheckpointStorageError("Archive destination already exists.")
                os.replace(source, destination)
                moved += 1
            return moved

    def quarantine_file(self, path: str | Path, reason: str) -> Path:
        if not isinstance(reason, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", reason):
            raise CheckpointStorageError("Invalid quarantine reason.")
        candidate = Path(path).resolve()
        managed = (self.active_dir.resolve(), self.history_dir.resolve(), self.quarantine_dir.resolve())
        if not candidate.is_file() or candidate.parent not in managed:
            raise CheckpointStorageError("Only managed checkpoint files can be quarantined.")
        if candidate.parent == self.quarantine_dir.resolve():
            raise CheckpointStorageError("File is already quarantined.")
        destination = self.quarantine_dir / f"{candidate.stem}.{reason}{candidate.suffix}"
        with self._lock:
            if destination.exists():
                raise CheckpointStorageError("Quarantine destination already exists.")
            try:
                os.replace(candidate, destination)
            except OSError as exc:
                raise CheckpointStorageError("Could not quarantine checkpoint file.") from exc
        return destination

    def verify(self, checkpoint_id: str, include_history: bool = True) -> WorkflowCheckpoint:
        checkpoint = self.get(checkpoint_id, include_history)
        checkpoint.verify_integrity()
        return checkpoint
