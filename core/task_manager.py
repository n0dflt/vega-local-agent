from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.task_state import (
    TaskStateError,
    TaskStatus,
    validate_transition,
)


PROJECT_STATE_DIR = Path("data") / "project_state"
TASKS_FILE = PROJECT_STATE_DIR / "tasks.json"
JOURNAL_FILE = PROJECT_STATE_DIR / "journal.jsonl"
VALID_STATUSES = {
    "planned",
    "in_progress",
    "waiting_review",
    "needs_rework",
    "done",
    "blocked",
}


def _project_root(project_root: Path | None = None) -> Path:
    return project_root if project_root is not None else Path.cwd()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _result(ok: bool, message: str = "", **values: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"ok": ok, "message": message}
    data.update(values)
    return data


class TaskManager:
    def __init__(self, project_root: Path | str | None = None) -> None:
        self.root = Path(project_root) if project_root is not None else Path.cwd()
        self.state_dir = self.root / PROJECT_STATE_DIR
        self.tasks_path = self.root / TASKS_FILE
        self.journal_path = self.root / JOURNAL_FILE
        self._ensure_files()

    def _ensure_files(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not self.tasks_path.exists():
            self._save_state({"current_task_id": None, "tasks": []})
        if not self.journal_path.exists():
            self.journal_path.touch()

    def _empty_state(self) -> dict[str, Any]:
        return {"current_task_id": None, "tasks": []}

    def _load_state(self) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            raw = self.tasks_path.read_text(encoding="utf-8").strip()
            data = json.loads(raw) if raw else self._empty_state()
        except (OSError, json.JSONDecodeError):
            data = self._empty_state()

        if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
            data = self._empty_state()
        data.setdefault("current_task_id", None)
        data["tasks"] = [self._normalize_task(task) for task in data["tasks"] if isinstance(task, dict)]
        if data["current_task_id"] and not any(task["id"] == data["current_task_id"] for task in data["tasks"]):
            data["current_task_id"] = None
        self._save_state(data)
        return data

    def _save_state(self, data: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalize_task(self, task: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        status = task.get("status", "planned")
        if status not in VALID_STATUSES:
            status = "planned"
        return {
            "id": str(task.get("id") or datetime.now().strftime("task-%Y%m%d%H%M%S")),
            "title": str(task.get("title") or "Untitled task"),
            "status": status,
            "plan": list(task.get("plan") or task.get("steps") or []),
            "notes": list(task.get("notes") or []),
            "created_at": str(task.get("created_at") or now),
            "updated_at": str(task.get("updated_at") or now),
        }

    def _next_task_id(self) -> str:
        data = self._load_state() if self.tasks_path.exists() else self._empty_state()
        max_number = 0
        for task in data.get("tasks", []):
            task_id = str(task.get("id", ""))
            if task_id.startswith("task-") and task_id[5:].isdigit():
                max_number = max(max_number, int(task_id[5:]))
        return f"task-{max_number + 1:03d}"

    def log_event(self, event: str, task_id: str | None, message: str) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        entry = {"time": _now(), "event": event, "task_id": task_id, "message": message}
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_journal(self, limit: int = 10) -> list[dict[str, Any]]:
        self._ensure_files()
        entries: list[dict[str, Any]] = []
        try:
            lines = self.journal_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return entries
        for line in lines[-limit:]:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def create_task(self, title: str) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise ValueError("Task title is empty.")
        data = self._load_state()
        now = _now()
        task = {
            "id": self._next_task_id(),
            "title": title,
            "status": "planned",
            "plan": [],
            "notes": [],
            "created_at": now,
            "updated_at": now,
        }
        data["tasks"].append(task)
        data["current_task_id"] = task["id"]
        self._save_state(data)
        self.log_event("task_created", task["id"], f"Task created: {title}")
        return task

    def list_tasks(self) -> list[dict[str, Any]]:
        return self._load_state()["tasks"]

    def get_current_task(self) -> dict[str, Any] | None:
        data = self._load_state()
        current_id = data.get("current_task_id")
        if current_id is None and data["tasks"]:
            current_id = data["tasks"][-1]["id"]
            data["current_task_id"] = current_id
            self._save_state(data)
        for task in data["tasks"]:
            if task["id"] == current_id:
                return task
        return None

    def _update_task(self, task_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        data = self._load_state()
        for task in data["tasks"]:
            if task["id"] == task_id:
                task.update(updates)
                task["updated_at"] = _now()
                self._save_state(data)
                return task
        raise ValueError(f"Task not found: {task_id}")

    def set_status(
        self,
        task_id: str,
        status: str,
    ) -> dict[str, Any]:
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Unsupported task status: {status}"
            )

        current_task = self.get_task(task_id)

        try:
            target_status = validate_transition(
                current_task["status"],
                status,
            )
        except TaskStateError as exc:
            raise ValueError(str(exc)) from exc

        task = self._update_task(
            task_id,
            {
                "status": target_status.value,
            },
        )

        self.log_event(
            "status_changed",
            task_id,
            (
                "Task status changed to "
                f"{target_status.value}"
            ),
        )

        if target_status == TaskStatus.NEEDS_REWORK:
            self.log_event(
                "sent_to_rework",
                task_id,
                "Task sent to rework after review.",
            )

        return task

    def add_plan(self, task_id: str, items: list[str]) -> dict[str, Any]:
        cleaned = [item.strip() for item in items if item and item.strip()]
        return self._update_task(task_id, {"plan": cleaned})

    def add_note(self, task_id: str, note: str) -> dict[str, Any]:
        note = note.strip()
        if not note:
            raise ValueError("Task note is empty.")
        task = self.get_task(task_id)
        notes = list(task.get("notes", []))
        notes.append({"time": _now(), "text": note})
        return self._update_task(task_id, {"notes": notes})

    def get_task(self, task_id: str) -> dict[str, Any]:
        for task in self.list_tasks():
            if task["id"] == task_id:
                return task
        raise ValueError(f"Task not found: {task_id}")

    def mark_done(
        self,
        task_id: str,
    ) -> dict[str, Any]:
        task = self.set_status(
            task_id,
            TaskStatus.DONE.value,
        )

        self.log_event(
            "task_done",
            task_id,
            "Task completed successfully.",
        )

        return task


def load_current_task(project_root: Path | None = None) -> tuple[dict[str, Any] | None, str]:
    try:
        return TaskManager(project_root).get_current_task(), ""
    except Exception as exc:
        return None, str(exc)


def has_current_task(project_root: Path | None = None) -> bool:
    task, error = load_current_task(project_root)
    return bool(task) and not error


def create_task(title: str, project_root: Path | None = None) -> dict[str, Any]:
    try:
        task = TaskManager(project_root).create_task(title)
        return _result(True, "Task created.", task=task)
    except ValueError as exc:
        return _result(False, str(exc))


def show_plan(project_root: Path | None = None) -> dict[str, Any]:
    task, error = load_current_task(project_root)
    if error:
        return _result(False, error)
    if task is None:
        return _result(False, "No active task.")
    plan = task.get("plan", [])
    return _result(True, "No plan yet." if not plan else "", task=task, steps=plan)


def add_note(text: str, project_root: Path | None = None) -> dict[str, Any]:
    manager = TaskManager(project_root)
    task = manager.get_current_task()
    if task is None:
        return _result(False, "No active task. Create one with: /task new <title>")
    try:
        task = manager.add_note(task["id"], text)
        return _result(True, "Task note added.", task=task, note=task["notes"][-1])
    except ValueError as exc:
        return _result(False, str(exc))


def build_review(project_root: Path | None = None) -> dict[str, Any]:
    from core.review_gate import ReviewGate

    manager = TaskManager(project_root)
    task = manager.get_current_task()
    if task is None:
        return _result(False, "No active task.")
    if task.get("status") != TaskStatus.IN_PROGRESS.value:
        return _result(
            False,
            "Task must be in progress before review.",
            task=task,
        )

    review = ReviewGate(project_root).review_task(task)
    manager.log_event(
        "review_started",
        task["id"],
        review.get(
            "summary",
            "Review started.",
        ),
    )

    new_status = (
        TaskStatus.WAITING_REVIEW.value
        if review.get("status") == "passed"
        else TaskStatus.NEEDS_REWORK.value
    )

    task = manager.set_status(
        task["id"],
        new_status,
    )
    review["task"] = task
    return _result(True, "", review=review)


def close_task(project_root: Path | None = None) -> dict[str, Any]:
    manager = TaskManager(project_root)
    task = manager.get_current_task()
    if task is None:
        return _result(False, "No active task to close.")
    if task.get("status") != "waiting_review":
        return _result(False, "Task needs review before done. Run /task review first.", task=task)
    task = manager.mark_done(task["id"])
    return _result(True, "Task completed.", task=task, archive_display=str(manager.tasks_path))


def clear_task(project_root: Path | None = None) -> dict[str, Any]:
    return _result(False, "Task deletion is disabled in Project Control Layer.")


def get_workspace_state(
    project_root: Path,
    version: str,
    model: str,
    internet: str,
    log_file: Path | str | None,
) -> dict[str, Any]:
    ensure_task_dirs(project_root)
    task, task_error = load_current_task(project_root)

    index_exists = False
    documents_indexed: int | str = "n/a"
    try:
        from rag.commands import count_indexed_documents, load_index_safe
        from rag.store import get_index_path

        index_path = get_index_path(project_root)
        index_exists = index_path.exists()
        if index_exists:
            index, index_error = load_index_safe(project_root)
            documents_indexed = "n/a" if index_error else count_indexed_documents(index)
        else:
            documents_indexed = 0
    except Exception:
        documents_indexed = "n/a"

    if task_error:
        current_task = "error"
        task_title = "n/a"
    elif task:
        current_task = task.get("status", "active")
        task_title = task.get("title", "n/a")
    else:
        current_task = "none"
        task_title = "n/a"

    return {
        "version": version,
        "project": str(project_root),
        "model": model,
        "internet": internet,
        "current_task": current_task,
        "task_title": task_title,
        "task_error": task_error,
        "documents_index": "YES" if index_exists else "NO",
        "documents_indexed": documents_indexed,
        "log_file": str(log_file) if log_file else "n/a",
    }
