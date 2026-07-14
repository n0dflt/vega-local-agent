"""Safe diagnosis and state-only recovery from immutable active checkpoints."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from uuid import uuid4

from workflows.checkpoint_models import CheckpointReason, WorkflowCheckpoint, canonical_payload_bytes
from workflows.checkpoint_store import CheckpointStorageError, CheckpointStore
from workflows.controlled_models import ControlledWorkflowState
from workflows.models import WORKFLOW_ID_PATTERN, WorkflowRun, WorkflowStatus, validate_workflow_id
from workflows.recovery_models import RecoveryDiagnosis, RecoveryResult, RecoveryState


class RecoveryError(RuntimeError): pass
class RecoveryNotAvailableError(RecoveryError): pass
class RecoveryConflictError(RecoveryError): pass
class RecoveryConfirmationError(RecoveryError): pass
class RecoveryStorageError(RecoveryError): pass


_LOCK = threading.RLock()
_SAFE = frozenset({
    (CheckpointReason.WORKFLOW_STARTED, WorkflowStatus.CREATED),
    (CheckpointReason.STATE_TRANSITION, WorkflowStatus.WAITING_PATCH),
    (CheckpointReason.STATE_TRANSITION, WorkflowStatus.WAITING_CONFIRMATION),
    (CheckpointReason.BEFORE_PATCH_APPLY, WorkflowStatus.EXECUTING),
    (CheckpointReason.AFTER_PATCH_APPLY, WorkflowStatus.VERIFYING),
    (CheckpointReason.VERIFICATION_RECORDED, WorkflowStatus.VERIFYING),
    (CheckpointReason.REVIEW_RECORDED, WorkflowStatus.REVIEWING),
    (CheckpointReason.WORKFLOW_STARTED, WorkflowStatus.PLANNED),
    (CheckpointReason.STATE_TRANSITION, WorkflowStatus.INVESTIGATING),
    (CheckpointReason.STATE_TRANSITION, WorkflowStatus.AWAITING_PATCH_CONFIRMATION),
    (CheckpointReason.BEFORE_PATCH_APPLY, WorkflowStatus.AWAITING_PATCH_CONFIRMATION),
    (CheckpointReason.AFTER_PATCH_APPLY, WorkflowStatus.AWAITING_TEST_CONFIRMATION),
    (CheckpointReason.STATE_TRANSITION, WorkflowStatus.AWAITING_TEST_CONFIRMATION),
    (CheckpointReason.STATE_TRANSITION, WorkflowStatus.TESTS_RUNNING),
    (CheckpointReason.VERIFICATION_RECORDED, WorkflowStatus.WAITING_PATCH),
})


def _deserialize_state(data: dict) -> WorkflowRun | ControlledWorkflowState:
    if data.get("schema_version") == 2:
        return ControlledWorkflowState.from_dict(data)
    return WorkflowRun.from_dict(data)


class WorkflowRecoveryManager:
    def __init__(self, project_root: str | Path, *, checkpoint_store=None) -> None:
        self.project_root = Path(project_root).resolve()
        self.checkpoint_store = checkpoint_store or CheckpointStore(self.project_root)
        self.active_dir = self.project_root / "data" / "workflows" / "active"
        self.history_dir = self.project_root / "data" / "workflows" / "history"
        self.quarantine_dir = self.project_root / "data" / "workflows" / "quarantine"
        try:
            self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RecoveryStorageError("Workflow quarantine storage cannot be created.") from exc
        self._lock = _LOCK

    @staticmethod
    def _warnings(checkpoint: WorkflowCheckpoint) -> list[str]:
        if checkpoint.workflow_status in {WorkflowStatus.EXECUTING, WorkflowStatus.TESTS_RUNNING}:
            return ["Patch application state must be verified by WorkflowEngine.resume()."]
        return []

    def _active_files(self) -> list[Path]:
        try:
            return sorted(self.active_dir.glob("*.json")) if self.active_dir.exists() else []
        except OSError as exc:
            raise RecoveryStorageError("Active workflow storage cannot be inspected.") from exc

    @staticmethod
    def _load_run(path: Path) -> WorkflowRun | ControlledWorkflowState:
        data = json.loads(path.read_text(encoding="utf-8"))
        run = _deserialize_state(data)
        if run.to_dict() != data or path.stem != run.workflow_id:
            raise ValueError("Active workflow filename or payload is invalid.")
        return run

    def _active_checkpoints(self) -> list[WorkflowCheckpoint]:
        directory = Path(self.checkpoint_store.active_dir)
        result = []
        try:
            paths = sorted(directory.glob("*.json"))
            for path in paths:
                result.append(self.checkpoint_store.get(path.stem, include_history=False))
        except (OSError, CheckpointStorageError) as exc:
            raise RecoveryStorageError("Active checkpoint storage is invalid.") from exc
        return result

    def select_checkpoint(self, workflow_id: str) -> WorkflowCheckpoint:
        try:
            validate_workflow_id(workflow_id)
            matches = [item for item in self._active_checkpoints() if item.workflow_id == workflow_id]
        except ValueError as exc:
            raise RecoveryNotAvailableError("Invalid workflow ID.") from exc
        if not matches:
            raise RecoveryNotAvailableError("No active checkpoint is available.")
        sequences = [item.sequence for item in matches]
        if len(sequences) != len(set(sequences)):
            raise RecoveryConflictError("Checkpoint sequencing is ambiguous.")
        latest = max(matches, key=lambda item: item.sequence)
        if (latest.reason, latest.workflow_status) not in _SAFE:
            raise RecoveryNotAvailableError("Latest active checkpoint is not safe for recovery.")
        return latest

    def _diagnosis(self, state, *, checkpoint=None, workflow_id=None, filename=None,
                   valid=False, recoverable=False, warnings=None):
        return RecoveryDiagnosis(
            state, workflow_id, filename, valid,
            checkpoint.checkpoint_id if checkpoint else None,
            checkpoint.sequence if checkpoint else None,
            checkpoint.reason.value if checkpoint else None,
            checkpoint.workflow_status if checkpoint else None,
            recoverable, recoverable, warnings or [],
        )

    def diagnose(self, workflow_id: str | None = None) -> RecoveryDiagnosis:
        if workflow_id is not None:
            try: validate_workflow_id(workflow_id)
            except ValueError as exc: raise RecoveryNotAvailableError("Invalid workflow ID.") from exc
        with self._lock:
            files = self._active_files()
            if len(files) > 1:
                return self._diagnosis(RecoveryState.MULTIPLE_ACTIVE_STATES, workflow_id=workflow_id)
            if files:
                path = files[0]
                try:
                    run = self._load_run(path)
                except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, KeyError):
                    candidate = path.stem if WORKFLOW_ID_PATTERN.fullmatch(path.stem) else None
                    if workflow_id is not None and candidate != workflow_id:
                        return self._diagnosis(RecoveryState.CORRUPT_ACTIVE_STATE, workflow_id=workflow_id,
                                               filename=path.name)
                    try: checkpoint = self.select_checkpoint(candidate) if candidate else None
                    except RecoveryNotAvailableError: checkpoint = None
                    return self._diagnosis(RecoveryState.RECOVERABLE if checkpoint else RecoveryState.CORRUPT_ACTIVE_STATE,
                                           checkpoint=checkpoint, workflow_id=candidate or workflow_id,
                                           filename=path.name, recoverable=checkpoint is not None,
                                           warnings=self._warnings(checkpoint) if checkpoint else [])
                if workflow_id is not None and run.workflow_id != workflow_id:
                    raise RecoveryConflictError("A different valid workflow is active.")
                return self._diagnosis(RecoveryState.HEALTHY, workflow_id=run.workflow_id,
                                       filename=path.name, valid=True)
            checkpoints = self._active_checkpoints()
            ids = sorted({item.workflow_id for item in checkpoints})
            if workflow_id is not None:
                ids = [item for item in ids if item == workflow_id]
            if len(ids) > 1:
                return self._diagnosis(RecoveryState.MULTIPLE_CHECKPOINT_WORKFLOWS)
            if not ids:
                return self._diagnosis(RecoveryState.MISSING_ACTIVE_STATE, workflow_id=workflow_id)
            try: checkpoint = self.select_checkpoint(ids[0])
            except RecoveryError:
                return self._diagnosis(RecoveryState.NOT_RECOVERABLE, workflow_id=ids[0])
            return self._diagnosis(RecoveryState.RECOVERABLE, checkpoint=checkpoint,
                                   workflow_id=ids[0], recoverable=True,
                                   warnings=self._warnings(checkpoint))

    def _quarantine(self, source: Path) -> Path:
        try:
            if source.resolve().parent != self.active_dir.resolve() or not source.is_file():
                raise RecoveryStorageError("Only active workflow files may be quarantined.")
            destination = self.quarantine_dir / f"{source.stem}.corrupt.{uuid4().hex}.json"
            if destination.resolve().parent != self.quarantine_dir.resolve() or destination.exists():
                raise RecoveryStorageError("Quarantine destination is not available.")
            os.replace(source, destination)
        except RecoveryStorageError:
            raise
        except OSError as exc:
            raise RecoveryStorageError("Could not quarantine active workflow.") from exc
        return destination

    def _write(self, destination: Path, payload: dict) -> None:
        try:
            self.active_dir.mkdir(parents=True, exist_ok=True)
            if destination.resolve().parent != self.active_dir.resolve():
                raise RecoveryStorageError("Restored workflow destination is unmanaged.")
            temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
            rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(rendered); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
            if destination.exists():
                raise RecoveryConflictError("Active workflow destination appeared during recovery.")
            os.replace(temporary, destination)
        except (OSError, TypeError, ValueError, RecoveryError) as exc:
            try:
                if "temporary" in locals(): temporary.unlink(missing_ok=True)
            except OSError: pass
            if isinstance(exc, RecoveryError):
                raise
            raise RecoveryStorageError("Restored workflow state could not be written.") from exc

    def recover(self, checkpoint_id: str, confirmation_token: str) -> RecoveryResult:
        if not isinstance(confirmation_token, str) or confirmation_token != "CONFIRM":
            raise RecoveryConfirmationError("The exact confirmation token CONFIRM is required.")
        with self._lock:
            try: checkpoint = self.checkpoint_store.get(checkpoint_id, include_history=False)
            except (CheckpointStorageError, TypeError, ValueError) as exc:
                raise RecoveryNotAvailableError("Requested active checkpoint is unavailable.") from exc
            latest = self.select_checkpoint(checkpoint.workflow_id)
            if latest.checkpoint_id != checkpoint.checkpoint_id:
                raise RecoveryConflictError("Only the latest active checkpoint may be restored.")
            if (checkpoint.reason, checkpoint.workflow_status) not in _SAFE:
                raise RecoveryNotAvailableError("Checkpoint is not safe for recovery.")
            try:
                run = _deserialize_state(checkpoint.workflow_payload)
                if run.to_dict() != checkpoint.workflow_payload:
                    raise ValueError
            except (TypeError, ValueError, KeyError) as exc:
                raise RecoveryStorageError("Checkpoint workflow payload is malformed.") from exc
            files = self._active_files()
            if len(files) > 1: raise RecoveryConflictError("Multiple active workflow files exist.")
            quarantine = None
            if files:
                path = files[0]
                try: active = self._load_run(path)
                except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, KeyError):
                    if path.name != f"{run.workflow_id}.json":
                        raise RecoveryConflictError("A different active workflow file blocks recovery.")
                    quarantine = self._quarantine(path)
                else:
                    if active.workflow_id != run.workflow_id:
                        raise RecoveryConflictError("A valid unrelated workflow is active.")
                    if canonical_payload_bytes(active.to_dict()) == canonical_payload_bytes(checkpoint.workflow_payload):
                        return RecoveryResult(run.workflow_id, checkpoint.checkpoint_id, run.status,
                                              path.name, None, False, True, True, self._warnings(checkpoint))
                    raise RecoveryConflictError("A valid differing active workflow blocks recovery.")
            destination = self.active_dir / f"{validate_workflow_id(run.workflow_id)}.json"
            self._write(destination, checkpoint.workflow_payload)
            try:
                restored = self._load_run(destination)
                if canonical_payload_bytes(restored.to_dict()) != canonical_payload_bytes(checkpoint.workflow_payload):
                    raise ValueError
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
                raise RecoveryStorageError("Restored workflow state failed validation.") from exc
            return RecoveryResult(run.workflow_id, checkpoint.checkpoint_id, run.status, destination.name,
                                  quarantine.name if quarantine else None, True, False, True,
                                  self._warnings(checkpoint))
