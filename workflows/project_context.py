"""Narrow adapter over the existing workspace and Project Control Layer."""
from __future__ import annotations
import re
from pathlib import Path
from core.task_manager import TaskManager

IGNORED={".git",".venv","venv","__pycache__","data","logs"}
SENSITIVE_MARKERS = (
    ".env",
    "credential",
    "credentials",
    "secret",
    "secrets",
    "private",
    "id_rsa",
    "id_ed25519",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
)

class ProjectContextAdapter:
    def __init__(self, project_root: Path | str, execution_context=None) -> None:
        self.root = Path(project_root).resolve()
        self.execution_context = execution_context

    def collect(self, task: str, workflow_type: str) -> dict:
        files = []
        for path in self.root.rglob("*"):
            if len(files) >= 500:
                break
            try:
                relative = path.relative_to(self.root)
            except ValueError:
                continue
            if any(part in IGNORED for part in relative.parts) or not path.is_file():
                continue
            lowered = relative.as_posix().lower()
            if any(marker in lowered for marker in SENSITIVE_MARKERS):
                continue
            files.append(relative.as_posix())
        tokens={token for token in re.findall(r"[A-Za-zА-Яа-я0-9_]{4,}",task.lower())}
        related=[name for name in files if any(token in name.lower() for token in tokens)]
        tests=[name for name in files if name.startswith("tests/") or "/test_" in name]
        docs=[name for name in files if name.lower().endswith((".md",".rst"))]
        entrypoints = [
            name
            for name in files
            if name in {"scripts/vega.py", "main.py", "app.py"}
            or name.endswith("/__main__.py")
        ]
        try:
            active_task = TaskManager(self.root).get_current_task()
        except Exception as exc:
            active_task = {"error": str(exc)}
        return {
            "project_root": str(self.root),
            "workflow": workflow_type,
            "project_structure": sorted(files),
            "related_files": related[:50],
            "entrypoints": entrypoints,
            "tests": tests[:100],
            "documentation": docs[:100],
            "active_task": active_task,
            "workspace_available": self.root.is_dir(),
            "active_mode": getattr(
                self.execution_context,
                "active_mode_name",
                None,
            ),
        }


class TaskSystemAdapter:
    """Reuse TaskManager storage without treating it as a plan generator."""
    def __init__(self, project_root: Path | str) -> None:
        self.manager = TaskManager(project_root)

    def current_task(self):
        return self.manager.get_current_task()

    def link_plan(self, task_id: str, plan: list[str]):
        self.manager.get_task(task_id)
        return self.manager.add_plan(task_id,plan)
