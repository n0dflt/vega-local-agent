#!/usr/bin/env python3
from __future__ import annotations

import importlib
import py_compile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VEGA_SCRIPT = ROOT / "scripts" / "vega.py"
RAG_DIR = ROOT / "rag"
DOCUMENTS_DIR = ROOT / "data" / "documents"
INDEX_DIR = ROOT / "data" / "index"
INDEX_FILE = INDEX_DIR / "documents_index.json"
TASKS_DIR = ROOT / "data" / "tasks"
TASK_ARCHIVE_DIR = TASKS_DIR / "archive"
TASK_MANAGER = ROOT / "core" / "task_manager.py"
TASK_VIEWS = ROOT / "ui" / "task_views.py"
EXPECTED_VERSION = "v0.7.0"

TASK_MANAGER_FUNCTIONS = [
    "ensure_task_dirs",
    "load_current_task",
    "save_current_task",
    "create_task",
    "add_step",
    "show_plan",
    "complete_step",
    "add_note",
    "build_review",
    "close_task",
    "clear_task",
]

TASK_VIEW_FUNCTIONS = [
    "render_current_task",
    "render_no_task",
    "render_task_created",
    "render_task_plan",
    "render_step_added",
    "render_step_completed",
    "render_note_added",
    "render_task_review",
    "render_task_closed",
    "render_task_cleared",
    "render_workspace",
    "render_task_error",
]


def status_line(label: str, status: str, detail: str = "") -> str:
    line = f"{label}: {status}"
    if detail:
        line += f" - {detail}"
    return line


def add_fail(lines: list[str], label: str, detail: str = "") -> bool:
    lines.append(status_line(label, "FAIL", detail))
    return True


def import_module(name: str) -> tuple[object | None, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        return importlib.import_module(name), ""
    except Exception as exc:
        return None, str(exc)


def check_rag_import() -> tuple[bool, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    modules = ["rag"]
    modules.extend(
        f"rag.{path.stem}"
        for path in sorted(RAG_DIR.glob("*.py"))
        if path.name != "__init__.py"
    )

    try:
        for module_name in modules:
            importlib.import_module(module_name)
    except Exception as exc:
        return False, str(exc)

    return True, ""


def check_syntax() -> tuple[bool, str]:
    try:
        py_compile.compile(str(VEGA_SCRIPT), doraise=True)
        py_compile.compile(str(TASK_MANAGER), doraise=True)
        py_compile.compile(str(TASK_VIEWS), doraise=True)
    except (py_compile.PyCompileError, OSError) as exc:
        return False, str(exc)
    return True, ""


def check_tasks_writable() -> tuple[bool, str]:
    tmp_path = TASKS_DIR / "healthcheck.tmp"
    try:
        tmp_path.write_text("ok", encoding="utf-8")
        tmp_path.unlink(missing_ok=True)
    except OSError as exc:
        return False, str(exc)
    return True, ""


def check_functions(module: object, names: list[str]) -> tuple[bool, str]:
    missing = [name for name in names if not callable(getattr(module, name, None))]
    if missing:
        return False, ", ".join(missing)
    return True, ""


def main() -> int:
    failed = False
    lines = [
        "# VEGA health check",
        "",
        f"Version expected: {EXPECTED_VERSION}",
        "",
    ]

    if VEGA_SCRIPT.exists():
        lines.append(status_line("scripts/vega.py", "OK"))
    else:
        failed = add_fail(lines, "scripts/vega.py", "file not found")

    if RAG_DIR.exists() and RAG_DIR.is_dir():
        lines.append(status_line("rag folder", "OK"))
    else:
        failed = add_fail(lines, "rag folder", "folder not found")

    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    lines.append(status_line("data/documents", "OK"))

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    lines.append(status_line("data/index", "OK"))

    if INDEX_FILE.exists():
        lines.append(status_line("documents index", "OK"))
    else:
        lines.append(status_line("documents index", "WARN", "documents index not found. Run /docs index."))
        lines.append("WARN: documents index not found. Run /docs index.")

    if TASK_MANAGER.exists():
        lines.append(status_line("core/task_manager.py", "OK"))
    else:
        failed = add_fail(lines, "core/task_manager.py", "file not found")

    if TASK_VIEWS.exists():
        lines.append(status_line("ui/task_views.py", "OK"))
    else:
        failed = add_fail(lines, "ui/task_views.py", "file not found")

    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    lines.append(status_line("data/tasks", "OK"))

    TASK_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    lines.append(status_line("data/tasks/archive", "OK"))

    rag_ok, rag_error = check_rag_import()
    if rag_ok:
        lines.append(status_line("rag import", "OK"))
    else:
        failed = add_fail(lines, "rag import", rag_error)
        lines.append(f"FAIL: RAG import error: {rag_error}")

    task_module, task_import_error = import_module("core.task_manager")
    if task_module is None:
        failed = add_fail(lines, "core.task_manager import", task_import_error)
    else:
        lines.append(status_line("core.task_manager import", "OK"))
        ok, detail = check_functions(task_module, TASK_MANAGER_FUNCTIONS)
        if ok:
            lines.append(status_line("core.task_manager functions", "OK"))
        else:
            failed = add_fail(lines, "core.task_manager functions", detail)

    views_module, views_import_error = import_module("ui.task_views")
    if views_module is None:
        failed = add_fail(lines, "ui.task_views import", views_import_error)
    else:
        lines.append(status_line("ui.task_views import", "OK"))
        ok, detail = check_functions(views_module, TASK_VIEW_FUNCTIONS)
        if ok:
            lines.append(status_line("ui.task_views functions", "OK"))
        else:
            failed = add_fail(lines, "ui.task_views functions", detail)

    writable_ok, writable_error = check_tasks_writable()
    if writable_ok:
        lines.append(status_line("data/tasks writable", "OK"))
    else:
        failed = add_fail(lines, "data/tasks writable", writable_error)

    syntax_ok, syntax_error = check_syntax()
    if syntax_ok:
        lines.append(status_line("syntax check", "OK"))
    else:
        failed = add_fail(lines, "syntax check", syntax_error)

    lines.append("")
    lines.append(f"Result: {'FAIL' if failed else 'OK'}")

    print("\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
