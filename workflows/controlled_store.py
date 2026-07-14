"""Atomic, locked persistence over the existing workflow state directories."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from core.state_integrity import GeneratedStateLock, StateLockError
from workflows.controlled_models import (
    CONTROLLED_SCHEMA_VERSION,
    ControlledWorkflowState,
    ControlledWorkflowValidationError,
    InvestigationEvidence,
)
from workflows.models import WorkflowStatus, validate_workflow_id


MAX_WORKFLOW_STATE_BYTES = 256 * 1024
MAX_WORKFLOW_FILES = 128
WORKFLOW_TEMP_PATTERN = re.compile(
    r"^\.workflow-[0-9a-f]{32}\.[0-9a-f]{32}\.tmp$"
)


class ControlledStoreError(RuntimeError):
    """State persistence failed without exposing an operating-system error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ControlledStoreConflict(ControlledStoreError):
    """Another process or ambiguous state prevents a mutation."""


def _canonical_bytes(state: ControlledWorkflowState) -> bytes:
    return (
        json.dumps(
            state.to_dict(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _safe_legacy_path(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.replace("\\", "/")
    if (
        not normalized
        or len(normalized) > 240
        or normalized.startswith(("/", "//"))
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        return None
    blocked = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "data", "logs"}
    if any(part.lower() in blocked for part in normalized.split("/")):
        return None
    return normalized


def migrate_legacy_state(data: dict[str, object]) -> ControlledWorkflowState:
    """Sanitize v1 metadata without advancing or executing the old workflow."""

    try:
        workflow_id = validate_workflow_id(data.get("workflow_id"))
        raw_type = data.get("workflow_type")
        workflow_type = "bug-fix" if raw_type == "bugfix" else raw_type
        if workflow_type not in {"bug-fix", "feature", "refactor", "test", "review"}:
            raise ValueError
        raw_task = data.get("task")
        if not isinstance(raw_task, str) or not raw_task.strip():
            raise ValueError
        normalized_task = raw_task.strip()[:2_000]
        task_sha256 = hashlib.sha256(normalized_task.encode("utf-8")).hexdigest()
        raw_status = WorkflowStatus(data.get("status"))
        created_at = data.get("created_at")
        updated_at = data.get("updated_at")
        if not isinstance(created_at, str) or not isinstance(updated_at, str):
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ControlledWorkflowValidationError("legacy workflow state is incompatible") from exc

    if raw_status is WorkflowStatus.WAITING_PATCH:
        status = WorkflowStatus.WAITING_PATCH
        next_actions = ("attach_patch", "cancel", "show")
        errors: tuple[str, ...] = ()
    elif raw_status in {WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED, WorkflowStatus.FAILED}:
        status = raw_status
        next_actions = ("show",)
        errors = () if raw_status is not WorkflowStatus.FAILED else ("state_incompatible",)
    else:
        status = WorkflowStatus.FAILED
        next_actions = ("show",)
        errors = ("state_incompatible",)

    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    related = []
    for value in context.get("related_files", []) if isinstance(context, dict) else []:
        safe = _safe_legacy_path(value)
        if safe and safe not in related:
            related.append(safe)
        if len(related) >= 24:
            break
    investigation = InvestigationEvidence(
        tuple(related),
        len(related),
        0,
        "related_evidence_found" if related else "insufficient_evidence",
        "not_configured",
    )
    return ControlledWorkflowState(
        schema_version=CONTROLLED_SCHEMA_VERSION,
        workflow_id=workflow_id,
        workflow_type=workflow_type,
        status=status,
        task_sha256=task_sha256,
        task_chars=len(normalized_task),
        created_at=created_at,
        updated_at=updated_at,
        revision=1,
        next_actions=next_actions,
        investigation=investigation,
        workspace_revision="",
        error_codes=errors,
        migrated_from_schema=1,
    )


class ControlledWorkflowStore:
    """Use v2.12 generated-state locking for v2.13 workflow JSON."""

    def __init__(self, project_root: Path, *, lock_timeout_ms: int = 1_000) -> None:
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / "data" / "workflows"
        self.active_dir = self.root / "active"
        self.history_dir = self.root / "history"
        self.lock_timeout_ms = lock_timeout_ms
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def mutation(self) -> Iterator[None]:
        try:
            with GeneratedStateLock(
                self.project_root,
                self.root,
                "workflows",
                self.lock_timeout_ms,
            ):
                yield
        except StateLockError as exc:
            code = "lock_timeout" if exc.code == "state_lock_timeout" else "state_write_failed"
            raise ControlledStoreConflict(code) from None

    def _files(self, directory: Path) -> list[Path]:
        all_json = sorted(directory.glob("*.json"))
        files = [path for path in all_json if re.fullmatch(r"workflow-[0-9a-f]{32}\.json", path.name)]
        if len(files) != len(all_json):
            raise ControlledStoreError("state_invalid")
        if len(files) > MAX_WORKFLOW_FILES:
            raise ControlledStoreError("state_invalid")
        return files

    def load_active(self, workflow_id: str | None = None) -> ControlledWorkflowState | None:
        files = self._files(self.active_dir)
        if workflow_id is not None:
            validate_workflow_id(workflow_id)
            files = [path for path in files if path.stem == workflow_id]
        if not files:
            return None
        if len(files) != 1:
            raise ControlledStoreConflict("state_invalid")
        return self.load_path(files[0])

    def load_history(self, workflow_id: str | None = None) -> list[ControlledWorkflowState]:
        files = self._files(self.history_dir)
        if workflow_id is not None:
            validate_workflow_id(workflow_id)
            files = [path for path in files if path.stem == workflow_id]
        return [self.load_path(path) for path in reversed(files)]

    def load_any(self, workflow_id: str) -> ControlledWorkflowState:
        active = self.load_active(workflow_id)
        if active is not None:
            return active
        history = self.load_history(workflow_id)
        if len(history) != 1:
            raise ControlledStoreError("state_invalid")
        return history[0]

    def load_path(self, path: Path) -> ControlledWorkflowState:
        try:
            if path.is_symlink() or path.stat().st_size > MAX_WORKFLOW_STATE_BYTES:
                raise ControlledWorkflowValidationError("unsafe workflow state file")
            raw = path.read_bytes()
            if len(raw) > MAX_WORKFLOW_STATE_BYTES:
                raise ControlledWorkflowValidationError("oversized workflow state")
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ControlledWorkflowValidationError("workflow state must be an object")
            state = (
                ControlledWorkflowState.from_dict(data)
                if data.get("schema_version") == CONTROLLED_SCHEMA_VERSION
                else migrate_legacy_state(data)
            )
            if path.stem != state.workflow_id:
                raise ControlledWorkflowValidationError("workflow filename mismatch")
            return state
        except ControlledWorkflowValidationError:
            raise ControlledStoreError("state_incompatible") from None
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            raise ControlledStoreError("state_invalid") from None

    def save_active(self, state: ControlledWorkflowState) -> None:
        self._write(self.active_dir / f"{state.workflow_id}.json", state)

    def save_history(self, state: ControlledWorkflowState) -> None:
        self._write(self.history_dir / f"{state.workflow_id}.json", state)

    def archive(self, state: ControlledWorkflowState) -> None:
        source = self.active_dir / f"{state.workflow_id}.json"
        target = self.history_dir / source.name
        if target.exists():
            raise ControlledStoreError("state_write_failed")
        self._write(target, state)
        try:
            source.unlink()
        except OSError:
            try:
                target.unlink()
            except OSError:
                pass
            raise ControlledStoreError("state_write_failed") from None

    def _write(self, path: Path, state: ControlledWorkflowState) -> None:
        payload = _canonical_bytes(state)
        if len(payload) > MAX_WORKFLOW_STATE_BYTES:
            raise ControlledStoreError("state_invalid")
        temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            if os.name != "nt":
                descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        except OSError:
            raise ControlledStoreError("state_write_failed") from None
        finally:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass


__all__ = [
    "ControlledStoreConflict",
    "ControlledStoreError",
    "ControlledWorkflowStore",
    "MAX_WORKFLOW_STATE_BYTES",
    "migrate_legacy_state",
]
