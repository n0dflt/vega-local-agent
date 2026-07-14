#!/usr/bin/env python3
"""VEGA CLI shell over the Ollama HTTP chat API."""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import sys
from pathlib import Path

try:
    from version import APP_NAME, APP_SUBTITLE, VERSION
except ImportError:
    from scripts.version import APP_NAME, APP_SUBTITLE, VERSION

from core.command_executor import (
    CommandExecutionRequest,
    CommandExecutionStatus,
    CommandExecutor,
)
from core.tool_confirmation import ToolConfirmationManager
from permissions.session_grants import SessionGrantStore
from core.command_router import CommandTarget
from core.execution_context import ExecutionContext
from core.ollama_client import (
    call_ollama_chat,
    check_ollama_ready,
)
from core.orchestrator import (
    AgentOrchestrator,
    OrchestrationKind,
)
from core.production_runtime import build_production_runtime
from core.production_snapshot import ProductionSnapshot
from core.tool_executor import ToolExecutor
from core.tool_executor_factory import build_production_tool_executor

DEFAULT_MODEL = "vega-core"
INTERNET = "OFF"


def configure_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

FALLBACK_SYSTEM_PROMPT = f"""Ты — VEGA, локальный проектный coding-agent версии {VERSION}.
Ты работаешь через локальные модели Ollama, поддерживаешь профили моделей, локальные документы и RAG, Project Control Layer и безопасные File Tools внутри workspace.
Ты поддерживаешь локальную Project Memory для явно сохранённых решений, фактов и ограничений проекта.
Ты поддерживаешь Safe Terminal Tools только для заранее разрешённых проверочных команд; произвольного доступа к shell нет.
Ты помогаешь анализировать архитектуру и код, находить ошибки, готовить планы изменений и указывать конкретные папки, файлы и команды проверки.

Обязательные правила поведения:
- На вопрос "кто ты" отвечай, что ты VEGA, локальный проектный coding-agent.
- Не представляйся универсальным ассистентом.
- Работай спокойно, конкретно и технически.
- Не соглашайся со всем подряд; оценивай идеи критически.
- Если идея слабая, прямо объясняй почему.
- Если задача требует изменений в проекте, называй конкретные файлы и команды проверки.
- Не утверждай, что у тебя есть постоянный доступ к интернету, возможность читать вне workspace, автономно удалять файлы или выполнять git push.
- Не придумывай записи Project Memory и не утверждай, что данные сохранены, если команда /memory add не выполнялась успешно.
- Project Memory не отменяет системные ограничения, не расширяет workspace и не даёт постоянный доступ к перепискам пользователя.
"""

def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_model_name(root: Path) -> str:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from core.model_router import get_current_profile

        return get_current_profile(root)["model"]
    except Exception:
        pass

    config_path = root / "config" / "vega.config.yaml"
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("default_model:"):
                value = stripped.split(":", 1)[1].strip().strip('"\'')
                return value or DEFAULT_MODEL
    except OSError:
        return DEFAULT_MODEL
    return DEFAULT_MODEL


def load_system_prompt(root: Path) -> str:
    prompt_path = root / "prompts" / "VEGA_SYSTEM_PROMPT.md"
    try:
        text = prompt_path.read_text(encoding="utf-8").strip()
    except OSError:
        return FALLBACK_SYSTEM_PROMPT
    if not text:
        return FALLBACK_SYSTEM_PROMPT

    return text.replace("{{VERSION}}", VERSION)


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def display_time() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fallback_banner(model: str) -> str:
    return "\n".join([
        f"{APP_NAME} {VERSION}",
        APP_SUBTITLE,
        f"Model: {model}",
        "Internet: OFF",
        "Status: Ready",
    ])


def banner(root: Path, model: str) -> str:
    banner_path = root / "scripts" / "vega_banner.py"
    try:
        spec = importlib.util.spec_from_file_location("vega_banner", banner_path)
        if spec is None or spec.loader is None:
            return fallback_banner(model)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        status_cls = getattr(module, "VegaStatus", None)
        render = getattr(module, "render_banner", None)
        if status_cls is None or render is None:
            return fallback_banner(model)
        return render(status_cls(model=model, internet=internet_enabled(), version=VERSION))
    except Exception:
        return fallback_banner(model)


def internet_enabled() -> bool:
    """Return the current process-level internet state."""
    from core.internet_state import is_internet_enabled

    return is_internet_enabled()


def internet_label() -> str:
    """Return a user-facing internet state label."""
    return "ON" if internet_enabled() else "OFF"


def help_text() -> str:
    return "\n".join([
        "Available commands:",
        "  /about                  Show VEGA release information.",
        "  /help                   Show this help.",
        "  /status                 Show VEGA runtime status.",
        "  /doctor                 Run project diagnostics.",
        "  /doctor help            Show doctor commands.",
        "  /doctor trace status    Show bounded trace-store status.",
        "  /doctor trace latest    Show the latest safe trace summary.",
        "  /doctor trace summary   Show a bounded trace aggregate.",
        "  /doctor export          Export a local diagnostics report.",
        "  /model                  Show current model profile and selection mode.",
        "  /model auto             Enable automatic contextual model selection.",
        "  /model status           Show Ollama/model status.",
        "  /model install-help     Show recommended install commands.",
        "  /docs                   Show documents help.",
        "  /docs list              Show documents.",
        "  /docs index             Rebuild local document index.",
        "  /docs search <query>    Search indexed documents.",
        "  /docs read <filename>   Read a local document.",
        "  /docs analyze <file>    Analyze a local document.",
        "  /docs summarize <file>  Summarize a local document.",
        "  /docs ask <question>    Ask indexed documents.",
        "  /file                  Show safe file command help.",
        "  /patch                 Show safe patch command help.",
        "  /git                   Show safe Git command help.",
        "  /tools list            Show registered tools.",
        "  /memory                Show Project Memory help.",
        "  /memory add ...        Save a project decision, fact, or constraint.",
        "  /memory list [kind]    List saved project memory.",
        "  /memory search <query> Search saved project memory.",
        "  /memory stats          Show Project Memory statistics.",
        "  /run                   Show Safe Terminal Tools help.",
        "  /run list              List predefined validation commands.",
        "  /run <command-id>      Run one predefined validation command.",
        "  /test                  Run all VEGA tests.",
        "  /test list             List predefined test groups.",
        "  /test <group-id>       Run one predefined test group.",
        "  /internet              Show current internet state.",
        "  /internet on           Enable internet for this VEGA process.",
        "  /internet off          Disable internet for this VEGA process.",
        "  /web fetch <https-url> Fetch one bounded text resource.",
        "  /mode                  Show the active agent mode.",
        "  /mode list             List available agent modes.",
        "  /mode set <name>       Activate an agent mode.",
        "  /mode reset            Restore the default agent mode.",
    "  /docgen                Show Documentation Builder help.",
    "  /docgen status         Show project documentation status.",
    "  /docgen check          Check required project documentation.",
        "  /docgen build          Create pending documentation patches.",
        "  /release                Show Release Manager help.",
        "  /release status         Show release readiness.",
        "  /release check          Run configured release checks.",
        "  /release notes          Build release notes draft.",
        "  /workflow              Show Coding Workflow help.",
        "  /workflow start ...    Start feature, bugfix, or refactor workflow.",
        "  /permissions grants    List active permission session grants.",
        "  /permissions revoke    Revoke one permission session grant.",
        "  /permissions clear     Clear permission session grants.",
        "  /plan [run] <task>     Preview or explicitly run a safe plan.",
        "",
        "Task Console:",
        "/workspace              Show workspace state",
        "/task                   Show task command help",
        "/exit                   Exit VEGA",
        "",
        "More:",
        "  /model fast | /model code | /model docs | /model deep",
        "  /project | /project status | /log | /clear",
    "  /docgen                Show Documentation Builder help.",
        "  /docgen status         Show project documentation status.",
        "  /docgen check          Check required project documentation.",
    ])


def append_log(log_file: Path, section: str, text: str = "") -> None:
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"\n[{section}] {display_time()}\n")
        if text:
            handle.write(text.rstrip() + "\n")


def create_log(root: Path, model: str) -> Path:
    sessions = root / "logs" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    log_file = sessions / f"vega_session_{now_stamp()}.txt"
    log_file.write_text(
        "\n".join([
            "VEGA session log",
            f"Started: {display_time()}",
            f"Project: {root}",
            f"Model: {model}",
            f"Internet: {internet_label()}",
            "Context: active session memory enabled",
            "",
        ]),
        encoding="utf-8",
    )
    return log_file


def model_unavailable_chat_message(model: str) -> str:
    return "\n".join([
        "Current model is not installed.",
        "Run:",
        f"  ollama pull {model}",
        "",
        "Or switch profile:",
        "  /model fast",
        "  /model code",
        "  /model docs",
        "  /model deep",
    ])


def load_task_state(root: Path) -> tuple[str, str]:
    try:
        from core.task_manager import load_current_task

        task, error = load_current_task(root)
        if error:
            return "error", "n/a"
        if task:
            return task.get("status", "active"), task.get("title", "n/a")
    except Exception:
        return "error", "n/a"
    return "none", "n/a"


def print_status(root: Path, log_file: Path, model: str) -> None:
    documents_folder = "data/documents"
    index_path = "data/index/documents_index.json"
    index_file = root / index_path
    documents_indexed = "n/a"
    chunks_indexed = "n/a"
    model_profile = "n/a"
    model_installed = "n/a"

    try:
        from rag.commands import count_indexed_documents, ensure_docs_paths, load_index_safe

        ensure_docs_paths(root)
        if index_file.exists():
            index, error = load_index_safe(root)
            documents_indexed = "n/a" if error else str(count_indexed_documents(index))
            chunks_indexed = "n/a" if error else str(index.get("chunks_count", "n/a"))
        else:
            documents_indexed = "0"
            chunks_indexed = "0"
    except Exception:
        documents_indexed = "n/a"
        chunks_indexed = "n/a"

    try:
        from core.model_router import get_model_status

        model_status = get_model_status(root)
        model_profile = model_status["current_profile"]
        model = model_status["current_model"]
        model_installed = "YES" if model_status["model_installed"] else "NO"
    except Exception:
        model_profile = "n/a"
        model_installed = "n/a"

    task_status, task_title = load_task_state(root)

    try:
        from memory.project_memory import get_memory_stats
        memory_result = get_memory_stats(root)
    except Exception:
        memory_result = {
            "ok": False,
            "error": "Project Memory is unavailable.",
            "data": None,
        }

    print("# VEGA status")
    print("")
    print(f"Version: {VERSION}")
    print(f"Model profile: {model_profile}")
    print(f"Model: {model}")
    print(f"Model installed: {model_installed}")
    print(f"Internet: {internet_label()}")
    from tools.terminal_tools import list_allowed_commands
    terminal_policy = list_allowed_commands(root)
    if terminal_policy["ok"]:
        print("Terminal tools: enabled")
        print("Terminal policy: config\\allowed_commands.json")
        print(f"Allowed terminal commands: {len(terminal_policy['data'])}")
    else:
        print("Terminal tools: policy error")
    print("Task console: enabled")
    print(f"Current task: {task_status}")
    print(f"Task title: {task_title}")
    print(f"Documents folder: {documents_folder}")
    print(f"Index path: {index_path}")
    print(f"Index exists: {'YES' if index_file.exists() else 'NO'}")
    print(f"Documents indexed: {documents_indexed}")
    print(f"Index chunks: {chunks_indexed}")
    if memory_result["ok"]:
        print("Project memory: enabled")
        print(f"Memory entries: {memory_result['data']['entries']}")
        print(f"Memory path: {memory_result['data']['path']}")
    else:
        print("Project memory: error")
        print("Memory entries: n/a")
    print(f"Log file: {log_file if log_file else 'n/a'}")


def print_model_info(root: Path) -> None:
    from core.model_router import get_model_profiles, get_model_status

    status = get_model_status(root)
    profiles = get_model_profiles()

    print(f"Selection mode: {status['selection_mode']}")
    print(f"Current model profile: {status['current_profile']}")
    print(f"Current model: {status['current_model']}")
    print("Available profiles:")
    for name, profile in profiles.items():
        print(f"  {name}  - {profile['purpose']} ({profile['model']})")


def print_model_status(root: Path) -> None:
    from core.model_router import get_model_status

    status = get_model_status(root)
    print(f"Selection mode: {status['selection_mode']}")
    print(f"Current model profile: {status['current_profile']}")
    print(f"Current model: {status['current_model']}")
    print(f"Ollama available: {'YES' if status['ollama_available'] else 'NO'}")
    print(f"Model installed: {'YES' if status['model_installed'] else 'NO'}")
    if not status["model_installed"]:
        print("")
        print("Install command:")
        print(f"  {status['install_command']}")


def print_model_install_help() -> None:
    print("Recommended models:")
    print("")
    print("Fast:")
    print("  ollama pull qwen2.5-coder:7b")
    print("")
    print("Code / Docs:")
    print("  ollama pull qwen2.5-coder:14b")
    print("")
    print("Deep:")
    print("  ollama pull qwen2.5-coder:32b")
    print("")
    print("Optional custom VEGA models:")
    print("  ollama create vega-code-14b -f .\\ollama\\Modelfile.14b")
    print("  ollama create vega-deep-32b -f .\\ollama\\Modelfile.32b")


def handle_model_command(command: str, root: Path) -> None:
    from core.model_router import (
        enable_auto_selection,
        get_model_profiles,
        get_model_status,
        set_current_profile,
    )

    parts = command.split(maxsplit=1)
    if len(parts) == 1:
        print_model_info(root)
        return

    profile_name = parts[1].strip().lower()
    if profile_name == "status":
        print_model_status(root)
        return

    if profile_name == "install-help":
        print_model_install_help()
        return

    if profile_name == "auto":
        profile = enable_auto_selection(root)
        print("Selection mode: auto")
        print(f"Fallback model profile: {profile['name']}")
        print(f"Fallback model: {profile['model']}")
        return

    profiles = get_model_profiles()
    if profile_name not in profiles:
        print(f"Unknown model profile: {profile_name}")
        print("Available profiles: fast, code, docs, deep")
        return

    profile = set_current_profile(root, profile_name)
    print("Selection mode: manual")
    print(f"Current model profile: {profile['name']}")
    print(f"Model: {profile['model']}")
    print(f"Purpose: {profile['purpose']}")
    status = get_model_status(root)
    print(f"Model installed: {'YES' if status['model_installed'] else 'NO'}")
    if not status["model_installed"]:
        print(f"Install command: {status['install_command']}")
    print("This profile will be used for the next chat request.")


def print_available_commands() -> None:
    print("Available:")
    print("/about")
    print("/workspace")
    print("/task")
    print("/journal")
    print("/project status")
    print("/help")
    print("/status")
    print("/doctor")
    print("/model")
    print("/docs")
    print("/file")
    print("/tools list")
    print("/run")
    print("/test")
    print("/internet")
    print("/web")
    print("/docgen")
    print("/release")
    print("/plan")
    print("/workflow")
    print("/exit")


def print_about() -> None:
    print("VEGA Local Agent")
    print(f"Version: {VERSION}")
    print("Type: Local Project Coding-Agent")
    print("Runtime: CLI")
    print(f"Internet: {internet_label()}")
    print("Documents: supported")
    print("RAG: local keyword index")
    print("Model profiles: fast, code, docs, deep")
    print("Default model profile: code")
    print("")
    print("Purpose:")
    print(
        "VEGA helps with local project work, code assistance, document reading, "
        "document analysis, and project diagnostics."
    )
    print("")
    print("Main commands:")
    print("  /help")
    print("  /status")
    print("  /doctor")
    print("  /model")
    print("  /docs")
    print("  /workspace")
    print("  /task")
    print("  /exit")


def handle_doctor_command(root: Path, command: str = "/doctor") -> None:
    from core.execution_trace import format_trace_summary, load_latest_trace
    from core.runtime_diagnostics import (
        DiagnosticsError,
        DiagnosticsPolicy,
        build_runtime_diagnostics,
        export_diagnostics_report,
        format_diagnostics_summary,
        format_trace_aggregate,
        format_trace_status,
        get_trace_store_status,
        load_diagnostics_policy,
    )
    from core.state_integrity import (
        format_state_repair,
        format_state_status,
        inspect_local_state,
        repair_local_state,
    )

    usage = "\n".join(
        (
            "Doctor commands:",
            "  /doctor",
            "  /doctor help",
            "  /doctor trace status",
            "  /doctor trace latest",
            "  /doctor trace summary",
            "  /doctor state status",
            "  /doctor state repair",
            "  /doctor export",
        )
    )
    raw_command = command.strip()
    normalized = " ".join(raw_command.lower().split())
    exact_state_commands = {"/doctor state status", "/doctor state repair"}
    if normalized.startswith("/doctor state") and raw_command not in exact_state_commands:
        print("Unknown doctor command.")
        print(usage)
        return
    if normalized == "/doctor help":
        print(usage)
        return
    known = {
        "/doctor",
        "/doctor trace status",
        "/doctor trace latest",
        "/doctor trace summary",
        "/doctor state status",
        "/doctor state repair",
        "/doctor export",
    }
    if normalized not in known:
        print("Unknown doctor command.")
        print(usage)
        return

    try:
        policy = load_diagnostics_policy(root)
    except DiagnosticsError:
        if not (root / "config" / "diagnostics_policy.json").exists() and normalized.startswith("/doctor trace "):
            # Preserve the v2.10 trace-read contract for older project roots.
            policy = DiagnosticsPolicy.defaults(root)
        else:
            print("Diagnostics unavailable: diagnostics_policy_error.")
            return

    if normalized == "/doctor trace latest":
        status = get_trace_store_status(root, policy)
        if not status.enabled:
            print("Execution tracing is disabled.")
            return
        latest_trace = load_latest_trace(root, policy)
        if latest_trace is not None:
            print(format_trace_summary(latest_trace))
        elif status.active_exists or status.backup_count:
            print("Latest trace record is invalid.")
        else:
            print("No execution trace is available.")
        return

    if normalized == "/doctor trace status":
        print(format_trace_status(get_trace_store_status(root, policy)))
        return

    if normalized == "/doctor trace summary":
        status = get_trace_store_status(root, policy)
        if not status.enabled:
            print("Execution tracing is disabled.")
            return
        print(format_trace_aggregate(status.aggregate))
        return

    if raw_command == "/doctor state status":
        try:
            print(format_state_status(inspect_local_state(root, policy)))
        except Exception:
            print("Local state integrity unavailable: state_lock_operation_failed.")
        return

    if raw_command == "/doctor state repair":
        print(format_state_repair(repair_local_state(root, policy)))
        return

    if normalized == "/doctor export":
        try:
            result = export_diagnostics_report(root, policy=policy)
        except DiagnosticsError:
            print("Diagnostics export failed: diagnostics_export_failed.")
            return
        print(f"Diagnostics report exported: {result.relative_path}")
        return

    try:
        print(format_diagnostics_summary(build_runtime_diagnostics(root, policy=policy)))
    except DiagnosticsError:
        print("Diagnostics unavailable: diagnostics_build_failed.")


UNKNOWN_COMMAND_HINTS = {
    "/tsk": "/task",
    "/tasknew": "/task new <title>",
    "/plan": "/task plan",
    "/done": "/task done <number>",
    "/review": "/task review",
    "/work": "/workspace",
    "/helo": "/help",
    "/stats": "/status",
    "/doc": "/docs",
    "/quit": "/exit",
    "/cmds": "/help",
    "/q": "/exit",
}


def print_unknown_command(command: str) -> None:
    lower = command.lower()
    print(f"Unknown command: {command}")
    suggestion = UNKNOWN_COMMAND_HINTS.get(lower)
    if suggestion:
        print(f"Did you mean: {suggestion}?")
        print("")
    print_available_commands()


def handle_workspace_command(root: Path, log_file: Path, model: str) -> None:
    from core.task_manager import get_workspace_state
    from ui.task_views import render_workspace

    workspace = get_workspace_state(
        project_root=root,
        version=VERSION,
        model=model,
        internet=INTERNET,
        log_file=log_file,
    )
    print(render_workspace(workspace))


def task_help_text() -> str:
    return "\n".join([
        "Task commands:",
        "  /task new <title>    Create a new current task",
        "  /task status         Show current task, status, plan, and recent notes",
        "  /task plan           Show current task plan",
        "  /task start          Start the current task",
        "  /task review         Run Coordinator Review Gate",
        "  /task done           Mark task done after review",
        "  /journal             Show last 10 project journal records",
        "  /project status      Show project control summary",
    ])


def print_task_status(task: dict | None) -> None:
    if task is None:
        print("No current task. Create one with: /task new <title>")
        return
    print("# Current task")
    print(f"ID: {task.get('id', 'n/a')}")
    print(f"Title: {task.get('title', 'n/a')}")
    print(f"Status: {task.get('status', 'n/a')}")
    print(f"Created: {task.get('created_at', 'n/a')}")
    print(f"Updated: {task.get('updated_at', 'n/a')}")
    print("")
    print("Plan:")
    plan = task.get("plan", [])
    if plan:
        for number, item in enumerate(plan, 1):
            print(f"{number}. {item}")
    else:
        print("Plan has not been created yet.")
    print("")
    print("Recent notes:")
    notes = task.get("notes", [])[-5:]
    if notes:
        for note in notes:
            if isinstance(note, dict):
                print(f"- {note.get('time', 'n/a')}: {note.get('text', '')}")
            else:
                print(f"- {note}")
    else:
        print("No notes yet.")


def print_task_plan(task: dict | None) -> None:
    if task is None:
        print("No current task. Create one with: /task new <title>")
        return
    plan = task.get("plan", [])
    if not plan:
        print("Plan has not been created yet.")
        return
    print(f"# Plan: {task.get('title', 'n/a')}")
    for number, item in enumerate(plan, 1):
        print(f"{number}. {item}")


def print_review_result(review: dict) -> None:
    print("# Coordinator Review Gate")
    print(f"Status: {review.get('status', 'n/a')}")
    for check in review.get("checks", []):
        print(f"- {check.get('name', 'check')}: {check.get('result', 'n/a')} - {check.get('details', '')}")
    print(review.get("summary", ""))


def handle_journal_command(root: Path) -> None:
    from core.task_manager import TaskManager

    manager = TaskManager(root)
    entries = manager.read_journal(limit=10)
    if not entries:
        print("Project journal is empty.")
        return
    print("# Project journal")
    for entry in entries:
        print(
            f"{entry.get('time', 'n/a')} | {entry.get('event', 'n/a')} | "
            f"{entry.get('task_id', 'n/a')} | {entry.get('message', '')}"
        )


def handle_project_status_command(root: Path) -> None:
    from core.task_manager import TaskManager

    manager = TaskManager(root)
    tasks = manager.list_tasks()
    current = manager.get_current_task()
    done = sum(1 for task in tasks if task.get("status") == "done")
    needs_rework = sum(1 for task in tasks if task.get("status") == "needs_rework")
    print("# Project status")
    print(f"Tasks: {len(tasks)}")
    if current:
        print(f"Current task: {current.get('id')} - {current.get('title')} ({current.get('status')})")
    else:
        print("Current task: none")
    print(f"Done: {done}")
    print(f"Needs rework: {needs_rework}")
    print(f"Journal: {manager.journal_path}")


def handle_task_command(command: str, root: Path) -> None:
    from core.task_manager import TaskManager
    from core.review_gate import ReviewGate

    stripped = command.strip()
    lower = stripped.lower()
    manager = TaskManager(root)

    if lower == "/task":
        print(task_help_text())
        return

    if lower == "/task status":
        print_task_status(manager.get_current_task())
        return

    if lower == "/task plan":
        print_task_plan(manager.get_current_task())
        return

    if lower == "/task start":
        task = manager.get_current_task()

        if task is None:
            print(
                "No current task. "
                "Create one with: /task new <title>"
            )
            return

        try:
            task = manager.set_status(
                task["id"],
                "in_progress",
            )
        except ValueError as exc:
            print(str(exc))
            return

        print(
            f"Task started: "
            f"{task.get('id')} - "
            f"{task.get('title')}"
        )
        return

    if lower.startswith("/task new"):
        title = stripped[len("/task new"):].strip()
        try:
            task = manager.create_task(title)
        except ValueError as exc:
            print(str(exc))
            return
        print("Task created and set as current.")
        print(f"ID: {task.get('id')}")
        print(f"Title: {task.get('title')}")
        return

    if lower.startswith("/task note"):
        text = stripped[len("/task note"):].strip()
        task = manager.get_current_task()
        if task is None:
            print("No current task. Create one with: /task new <title>")
            return
        try:
            manager.add_note(task["id"], text)
            print("Task note added.")
        except ValueError as exc:
            print(str(exc))
        return

    if lower == "/task review":
        task = manager.get_current_task()

        if task is None:
            print(
                "No current task. "
                "Create one with: /task new <title>"
            )
            return

        if task.get("status") != "in_progress":
            print(
                "Task must be in progress before review. "
                "Run /task start."
            )
            return

        review = ReviewGate(root).review_task(
            task,
            changed_files=[],
        )
        manager.log_event("review_started", task["id"], review.get("summary", "Review started."))
        new_status = "waiting_review" if review.get("status") == "passed" else "needs_rework"
        manager.set_status(task["id"], new_status)
        print_review_result(review)
        print(f"Task status: {new_status}")
        return

    if lower == "/task done":
        task = manager.get_current_task()
        if task is None:
            print("No current task. Create one with: /task new <title>")
            return
        if task.get("status") != "waiting_review":
            print(
                "Task needs review before done. "
                "Run /task review first."
            )
            return
        task = manager.mark_done(task["id"])
        print(f"Task done: {task.get('id')} - {task.get('title')}")
        return

    if lower in {"/task close", "/task clear"}:
        print("This command is disabled in Project Control Layer. Use /task done after review.")
        return

    print_unknown_command(stripped)


def handle_command(
    command: str,
    root: Path,
    log_file: Path,
    model: str,
    mode_session=None,
    tool_executor: ToolExecutor | None = None,
    tool_confirmation_manager: ToolConfirmationManager | None = None,
    session_grants: SessionGrantStore | None = None,
    production_snapshot: ProductionSnapshot | None = None,
) -> bool:
    command = command.strip()
    lower = command.lower()

    if lower == "/about":
        print_about()
    elif lower == "/help":
        print(help_text())
    elif lower == "/status":
        print_status(root, log_file, model)
    elif lower == "/doctor" or lower.startswith("/doctor "):
        handle_doctor_command(root, command)
    elif lower == "/workspace":
        handle_workspace_command(root, log_file, model)
    elif lower == "/model" or lower.startswith("/model "):
        handle_model_command(command, root)
    elif lower == "/project":
        print(root)
    elif lower == "/project status":
        handle_project_status_command(root)
    elif lower == "/clear":
        os.system("cls" if os.name == "nt" else "clear")
    elif lower == "/log":
        print(log_file)
    elif lower == "/task" or lower.startswith("/task "):
        handle_task_command(command, root)
    elif lower == "/journal":
        handle_journal_command(root)
    elif lower == "/file" or lower.startswith("/file "):
        from core.command_handler import handle_file_command
        print(
            handle_file_command(
                command,
                tool_executor=tool_executor,
            )
        )
    elif lower == "/patch" or lower.startswith("/patch "):
        from core.command_handler import handle_patch_command
        if tool_confirmation_manager is None:
            print(handle_patch_command(command, mode_session))
        else:
            print(handle_patch_command(
                command,
                mode_session,
                tool_executor=tool_executor,
                tool_confirmation_manager=tool_confirmation_manager,
            ))
    elif lower == "/git" or lower.startswith("/git "):
        from core.command_handler import handle_git_command
        print(
            handle_git_command(
                command,
                project_root=root,
                tool_executor=tool_executor,
            )
        )
    elif lower == "/tools list":
        from core.command_handler import tools_list_text
        print(
            tools_list_text(
                tool_executor=tool_executor,
            )
        )
    elif lower == "/memory" or lower.startswith("/memory "):
        from core.command_handler import handle_memory_command
        if tool_confirmation_manager is None:
            print(handle_memory_command(command, root))
        else:
            print(handle_memory_command(command, root, tool_executor, tool_confirmation_manager))
    elif lower == "/run" or lower.startswith("/run "):
        from core.command_handler import handle_terminal_command
        print(handle_terminal_command(
            command,
            root,
            tool_executor=tool_executor,
            tool_confirmation_manager=tool_confirmation_manager,
        ))
    elif lower == "/test" or lower.startswith("/test "):
        from core.command_handler import handle_test_command
        if tool_confirmation_manager is None:
            print(handle_test_command(command, root))
        else:
            print(handle_test_command(command, root, tool_executor, tool_confirmation_manager))
    elif lower == "/internet" or lower.startswith("/internet "):
        from core.command_handler import handle_internet_command
        if tool_confirmation_manager is None:
            print(handle_internet_command(command))
        else:
            print(handle_internet_command(command, tool_executor, tool_confirmation_manager))
    elif lower == "/web" or lower.startswith("/web "):
        from core.command_handler import handle_web_command
        if tool_confirmation_manager is None:
            print(handle_web_command(command, root))
        else:
            print(handle_web_command(command, root, tool_executor, tool_confirmation_manager))
    elif lower == "/mode" or lower.startswith("/mode "):
        from core.command_handler import handle_mode_command

        if mode_session is None:
            print("Mode command error: mode session is unavailable.")
        else:
            print(handle_mode_command(command, mode_session))
    elif lower == "/docgen" or lower.startswith("/docgen "):
        from core.command_handler import handle_docgen_command

        if tool_confirmation_manager is None:
            print(handle_docgen_command(command, root))
        else:
            print(handle_docgen_command(command, root, tool_executor, tool_confirmation_manager))
    elif lower == "/release" or lower.startswith("/release "):
        from core.command_handler import handle_release_command

        if tool_confirmation_manager is None:
            print(handle_release_command(command, root))
        else:
            print(handle_release_command(command, root, tool_executor, tool_confirmation_manager))
    elif lower == "/workflow" or lower.startswith("/workflow "):
        from core.command_handler import handle_workflow_command

        print(handle_workflow_command(command, root))
    elif lower == "/plan" or lower.startswith("/plan "):
        from core.plan_command import handle_plan_command

        print(
            handle_plan_command(
                command,
                root,
                tool_executor=tool_executor,
                production_snapshot=production_snapshot,
            )
        )
    elif lower == "/permissions" or lower.startswith("/permissions "):
        from core.command_handler import handle_permissions_command
        if session_grants is None:
            print("Permissions command error: session grants are unavailable.")
        else:
            print(handle_permissions_command(command, session_grants))
    elif lower in {"/exit", "/bye", "/q"}:
        print("Bye.")
        append_log(log_file, "SYSTEM", "Session closed by user.")
        return False
    else:
        print_unknown_command(command)
    append_log(log_file, "COMMAND", command)
    return True


def dispatch_docs_command(
    command: str,
    root: Path,
) -> None:
    """Execute the existing local documents command."""
    from rag.commands import (
        handle_docs_command,
    )

    handle_docs_command(
        command,
        root,
    )


def build_orchestrator(
    root: Path,
    model: str,
    log_file: Path,
    system_prompt: str,
    mode_session,
) -> AgentOrchestrator:
    """Create the orchestration layer for one CLI session."""
    context = ExecutionContext(
        project_root=root,
        model=model,
        log_file=log_file,
        system_prompt=system_prompt,
        mode_session=mode_session,
    )

    from workflows import WorkflowEngine, default_registry
    from workflows.project_context import ProjectContextAdapter, TaskSystemAdapter
    from review.code_reviewer import OllamaReviewProvider

    workflow_engine = WorkflowEngine(
        root,
        default_registry(),
        confirmation_manager=context.confirmation_manager,
        project_context=ProjectContextAdapter(root, context),
        task_adapter=TaskSystemAdapter(root),
        review_provider=OllamaReviewProvider(context.model),
    )

    return AgentOrchestrator(
        context,
        workflow_engine=workflow_engine,
    )


def build_command_executor(
    context: ExecutionContext,
    *,
    tool_executor: ToolExecutor | None = None,
    tool_confirmation_manager: ToolConfirmationManager | None = None,
    session_grants: SessionGrantStore | None = None,
    production_snapshot: ProductionSnapshot | None = None,
) -> CommandExecutor:
    """Create compatibility handlers for routed runtime commands."""
    if not isinstance(context, ExecutionContext):
        raise TypeError(
            "context must be an ExecutionContext instance."
        )

    if tool_executor is None:
        tool_executor = build_production_tool_executor()
    elif not isinstance(tool_executor, ToolExecutor):
        raise TypeError(
            "tool_executor must be a ToolExecutor instance."
        )

    def legacy_adapter(
        request: CommandExecutionRequest,
    ) -> bool:
        arguments = {"tool_executor": tool_executor}
        if tool_confirmation_manager is not None:
            arguments["tool_confirmation_manager"] = tool_confirmation_manager
        if session_grants is not None:
            arguments["session_grants"] = session_grants
        if production_snapshot is not None:
            arguments["production_snapshot"] = production_snapshot
        return handle_command(
            request.route.normalized_command,
            context.project_root,
            context.log_file,
            context.model,
            context.mode_session,
            **arguments,
        )

    def docs_adapter(
        request: CommandExecutionRequest,
    ) -> None:
        dispatch_docs_command(
            request.route.normalized_command,
            context.project_root,
        )
        append_log(
            context.log_file,
            "COMMAND",
            request.route.normalized_command,
        )

    def workflow_adapter(
        request: CommandExecutionRequest,
    ) -> None:
        from core.command_handler import handle_workflow_command

        print(
            handle_workflow_command(
                request.route.normalized_command,
                context.project_root,
                confirmation_manager=context.confirmation_manager,
                execution_context=context,
            )
        )
        append_log(
            context.log_file,
            "COMMAND",
            request.route.normalized_command,
        )

    registry = {
        target: legacy_adapter
        for target in CommandTarget
        if target not in {
            CommandTarget.DOCS,
            CommandTarget.UNKNOWN,
        }
    }
    registry[CommandTarget.DOCS] = docs_adapter
    registry[CommandTarget.WORKFLOW] = workflow_adapter

    return CommandExecutor(registry)


def main() -> int:
    configure_output()

    root = project_root()

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    production_runtime = build_production_runtime(root)
    model = load_model_name(root)
    system_prompt = load_system_prompt(root)
    log_file = create_log(root, model)

    from core.agent_modes import (
        ModeRegistry,
        ModeSession,
    )

    mode_registry = ModeRegistry(
        root / "config" / "modes.json"
    )
    mode_session = ModeSession(
        mode_registry
    )

    orchestrator = build_orchestrator(
        root=root,
        model=model,
        log_file=log_file,
        system_prompt=system_prompt,
        mode_session=mode_session,
    )
    context = orchestrator.context
    session_grants = production_runtime.session_grants
    tool_executor = production_runtime.tool_executor
    tool_confirmation_manager = ToolConfirmationManager(input)
    command_executor = build_command_executor(
        context,
        tool_executor=tool_executor,
        tool_confirmation_manager=tool_confirmation_manager,
        session_grants=session_grants,
        production_snapshot=production_runtime.snapshot,
    )

    from ui.startup_screen import (
        render_startup_screen,
    )

    render_startup_screen(
        version=VERSION,
        model=context.model,
        internet_status=INTERNET,
        status=production_runtime.status,
        log_path=context.log_file,
    )
    print(
        "Production policy: "
        f"{production_runtime.snapshot.consistency_report.summary}"
    )
    print(
        "Tool execution: "
        f"{'ENABLED' if production_runtime.can_execute_tools else 'BLOCKED'}"
    )

    ready, details = check_ollama_ready(
        context.model
    )

    if not ready:
        print(details)
        print("")
        print(
            "VEGA will stay in CLI mode. "
            "Commands like /docs, /model, "
            "/status, /doctor, /help, and "
            "/exit are available."
        )
        append_log(
            context.log_file,
            "WARNING",
            details,
        )

    while True:
        try:
            raw_input = input("VEGA> ")
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            append_log(
                context.log_file,
                "SYSTEM",
                "Session interrupted.",
            )
            return 0

        result = orchestrator.process(
            raw_input
        )

        if result.kind is OrchestrationKind.EMPTY:
            continue

        if result.kind is OrchestrationKind.WORKFLOW_DRAFT:
            print(result.message)
            append_log(log_file, "WORKFLOW", result.message)
            continue

        append_log(
            context.log_file,
            "USER",
            result.intent.normalized_text,
        )

        if (
            result.kind
            is OrchestrationKind.COMMAND
        ):
            route = result.command_route

            if route is None:
                raise RuntimeError(
                    "Command result has no route."
                )

            execution_result = command_executor.execute(
                CommandExecutionRequest(route=route)
            )

            if (
                execution_result.status
                is not CommandExecutionStatus.SUCCESS
            ):
                print(execution_result.error)
                append_log(
                    context.log_file,
                    "COMMAND_ERROR",
                    execution_result.error,
                )
                continue

            if not execution_result.keep_running:
                return 0

            continue

        if (
            result.kind
            is OrchestrationKind.WAITING_CONFIRMATION
        ):
            print(result.message)
            append_log(
                context.log_file,
                "WARNING",
                result.message,
            )
            continue

        if (
            result.kind
            is OrchestrationKind.CONFIRMATION
        ):
            confirmation = (
                result.confirmation_result
            )

            if confirmation is None:
                raise RuntimeError(
                    "Confirmation result is missing."
                )

            if confirmation.confirmed:
                message = (
                    "Action confirmed: "
                    f"{confirmation.request.action_name}"
                )
            else:
                message = (
                    "Action cancelled: "
                    f"{confirmation.request.action_name}"
                )

            print(message)
            append_log(
                context.log_file,
                "CONFIRMATION",
                message,
            )
            continue

        if result.kind is not OrchestrationKind.CHAT:
            raise RuntimeError(
                "Unsupported orchestration result: "
                f"{result.kind!r}."
            )

        if result.message:
            print(result.message)

        if not result.message:
            from core.contextual_runtime import (
                try_execute_contextual_request,
            )
            from core.execution_trace import append_trace

            contextual_result = (
                try_execute_contextual_request(
                    result.intent.normalized_text,
                    context.project_root,
                    tool_executor,
                    chat_callable=call_ollama_chat,
                    production_snapshot=production_runtime.snapshot,
                    trace_callback=(
                        lambda trace: append_trace(
                            context.project_root,
                            trace,
                        )
                    ),
                )
            )

            if contextual_result.handled:
                print(contextual_result.message)
                append_log(
                    context.log_file,
                    "CONTEXTUAL",
                    contextual_result.message,
                )
                if contextual_result.synthesis_result is not None:
                    context.append_message(
                        "user",
                        result.intent.normalized_text,
                    )
                    context.append_message(
                        "assistant",
                        contextual_result.message,
                    )
                    if not contextual_result.synthesis_result.ok:
                        append_log(
                            context.log_file,
                            "CONTEXTUAL_SYNTHESIS_FALLBACK",
                            contextual_result.synthesis_result.reason,
                        )
                continue

        model = load_model_name(
            context.project_root
        )
        context.set_model(model)

        try:
            from core.model_router import (
                get_model_status,
            )

            model_status = get_model_status(
                context.project_root
            )
        except Exception:
            model_status = {
                "model_installed": True,
                "current_model": context.model,
            }

        if not model_status.get(
            "model_installed",
            True,
        ):
            response = model_unavailable_chat_message(
                str(
                    model_status.get(
                        "current_model",
                        context.model,
                    )
                )
            )
            print(response)
            append_log(
                context.log_file,
                "ERROR",
                response,
            )
            continue

        context.append_message(
            "user",
            result.intent.normalized_text,
        )

        request_messages = (
            context.copy_messages()
        )

        try:
            from memory.project_memory import (
                build_memory_context,
            )

            memory_result = build_memory_context(
                context.project_root
            )
        except Exception:
            memory_result = {
                "ok": False,
                "error": "Project Memory is unavailable.",
                "data": None,
            }

        if (
            memory_result["ok"]
            and memory_result["data"]["context"]
        ):
            request_messages[0]["content"] = (
                context.system_prompt
                + "\n\n"
                + memory_result["data"]["context"]
            )
        elif not memory_result["ok"]:
            error = str(
                memory_result.get("error")
                or (
                    "Unknown Project Memory "
                    "error."
                )
            )

            if (
                error
                not in context.memory_warning_errors
            ):
                warning = (
                    f"Project Memory warning: "
                    f"{error} "
                    "Chat will continue without "
                    "memory."
                )
                print(warning)
                append_log(
                    context.log_file,
                    "WARNING",
                    warning,
                )
                context.memory_warning_errors.add(
                    error
                )

        request_messages[0]["content"] += (
            "\n\n"
            + context.mode_session.active_mode
            .build_instruction()
        )

        ok, response = call_ollama_chat(
            context.model,
            request_messages,
        )

        label = "VEGA" if ok else "ERROR"

        print(response)
        append_log(
            context.log_file,
            label,
            response,
        )

        if ok:
            context.append_message(
                "assistant",
                response,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
