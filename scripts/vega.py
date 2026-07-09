#!/usr/bin/env python3
"""VEGA CLI shell over the Ollama HTTP chat API."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from version import APP_NAME, APP_SUBTITLE, VERSION
except ImportError:
    VERSION = "v1.0.0"
    APP_NAME = "VEGA"
    APP_SUBTITLE = "Local Project Coding-Agent"

DEFAULT_MODEL = "vega-core"
INTERNET = "OFF"
API_URL = "http://localhost:11434/api/chat"


def configure_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

FALLBACK_SYSTEM_PROMPT = """Ты — VEGA, локальный проектный coding-agent v1.0.0.
Твоя задача — помогать пользователю проектировать архитектуру, писать код, проверять код, находить ошибки, давать patch plan и работать как проектный агент, а не как обычный чат-бот.

Обязательные правила поведения:
- На вопрос "кто ты" отвечай, что ты VEGA, локальный проектный coding-agent.
- Не представляйся универсальным ассистентом.
- Работай спокойно, конкретно и технически.
- При задачах по коду сначала анализируй, затем предлагай patch plan.
- Не соглашайся со всем подряд; оценивай идеи критически.
- Если идея слабая, прямо объясняй почему.
- Если задача требует изменений в проекте, называй конкретные файлы и команды проверки.
- Не утверждай, что у тебя есть прямой доступ к файлам, терминалу или интернету, если пользователь не дал такую информацию.
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
    return text or FALLBACK_SYSTEM_PROMPT


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
        return render(status_cls(model=model, internet=False, version=VERSION))
    except Exception:
        return fallback_banner(model)


def help_text() -> str:
    return "\n".join([
        "Available commands:",
        "  /about                  Show VEGA release information.",
        "  /help                   Show this help.",
        "  /status                 Show VEGA runtime status.",
        "  /doctor                 Run project diagnostics.",
        "  /model                  Show current model profile.",
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
        "",
        "Task Console:",
        "/workspace              Show workspace state",
        "/task                   Show task command help",
        "/exit                   Exit VEGA",
        "",
        "More:",
        "  /model fast | /model code | /model docs | /model deep",
        "  /project | /project status | /log | /clear",
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
            f"Internet: {INTERNET}",
            "Context: active session memory enabled",
            "",
        ]),
        encoding="utf-8",
    )
    return log_file


def api_error_message() -> str:
    return "\n".join([
        "Ollama API is unavailable.",
        "Check that Ollama is running.",
        "Then try:",
        "ollama list",
    ])


def missing_model_message(model: str) -> str:
    return f"Model may not be installed. Run: ollama pull {model}"


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


def call_ollama_chat(model: str, messages: list[dict[str, str]]) -> tuple[bool, str]:
    payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404 or "not found" in body.lower() or "model" in body.lower():
            return False, f"Model `{model}` was not found.\n{missing_model_message(model)}"
        return False, body.strip() or f"Ollama API returned HTTP {exc.code}."
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, api_error_message()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, raw.strip() or "Ollama API returned an unreadable response."

    if data.get("error"):
        error = str(data["error"])
        if "not found" in error.lower() or "model" in error.lower():
            return False, f"Model `{model}` was not found.\n{missing_model_message(model)}"
        return False, error

    message = data.get("message", {})
    content = message.get("content", "") if isinstance(message, dict) else ""
    return True, content.strip()


def check_ollama_ready(model: str) -> tuple[bool, str]:
    messages = [
        {"role": "system", "content": "Reply with exactly: OK"},
        {"role": "user", "content": "health check"},
    ]
    ok, response = call_ollama_chat(model, messages)
    if ok:
        return True, response
    return False, response


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

    print("# VEGA status")
    print("")
    print(f"Version: {VERSION}")
    print(f"Model profile: {model_profile}")
    print(f"Model: {model}")
    print(f"Model installed: {model_installed}")
    print(f"Internet: {INTERNET}")
    print("Task console: enabled")
    print(f"Current task: {task_status}")
    print(f"Task title: {task_title}")
    print(f"Documents folder: {documents_folder}")
    print(f"Index path: {index_path}")
    print(f"Index exists: {'YES' if index_file.exists() else 'NO'}")
    print(f"Documents indexed: {documents_indexed}")
    print(f"Index chunks: {chunks_indexed}")
    print(f"Log file: {log_file if log_file else 'n/a'}")


def print_model_info(root: Path) -> None:
    from core.model_router import get_current_profile, get_model_profiles

    current = get_current_profile(root)
    profiles = get_model_profiles()

    print(f"Current model profile: {current['name']}")
    print(f"Current model: {current['model']}")
    print("Available profiles:")
    for name, profile in profiles.items():
        print(f"  {name}  - {profile['purpose']} ({profile['model']})")


def print_model_status(root: Path) -> None:
    from core.model_router import get_model_status

    status = get_model_status(root)
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
    from core.model_router import get_model_profiles, get_model_status, set_current_profile

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

    profiles = get_model_profiles()
    if profile_name not in profiles:
        print(f"Unknown model profile: {profile_name}")
        print("Available profiles: fast, code, docs, deep")
        return

    profile = set_current_profile(root, profile_name)
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
    print("/exit")


def print_about() -> None:
    print("VEGA Local Agent")
    print(f"Version: {VERSION}")
    print("Type: Local Project Coding-Agent")
    print("Runtime: CLI")
    print(f"Internet: {INTERNET}")
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


def handle_doctor_command(root: Path) -> None:
    from core.model_router import get_model_status
    from rag.document_index import load_documents_index

    documents_dir = root / "data" / "documents"
    index_path = root / "data" / "index" / "documents_index.json"
    smoke_test = root / "scripts" / "smoke_test.py"
    model_status = get_model_status(root)
    index = load_documents_index(root) if index_path.exists() else None
    documents_count = index.get("documents_count", 0) if index else 0
    chunks_count = index.get("chunks_count", 0) if index else 0
    fixes: list[str] = []

    if not model_status["model_installed"]:
        fixes.append(f"Run: {model_status['install_command']}")
    if not index_path.exists():
        fixes.append("Run: /docs index")
    if not documents_dir.exists():
        fixes.append("Create folder: data\\documents")

    print("VEGA Doctor")
    print(f"Version: {VERSION}")
    print(f"Project root: {root}")
    print(f"Ollama available: {'YES' if model_status['ollama_available'] else 'NO'}")
    print(f"Current profile: {model_status['current_profile']}")
    print(f"Current model: {model_status['current_model']}")
    print(f"Model installed: {'YES' if model_status['model_installed'] else 'NO'}")
    print(f"Documents folder: {'OK' if documents_dir.exists() else 'MISSING'}")
    print(f"Index file: {'OK' if index_path.exists() else 'MISSING'}")
    print(f"Documents indexed: {documents_count}")
    print(f"Chunks indexed: {chunks_count}")
    smoke_status = "available at scripts\\smoke_test.py" if smoke_test.exists() else "MISSING"
    print(f"Smoke test: {smoke_status}")

    if fixes:
        print("")
        print("Recommended fixes:")
        for fix in fixes:
            print(f"- {fix}")


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
            print("No current task. Create one with: /task new <title>")
            return
        review = ReviewGate(root).review_task(task, changed_files=[])
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
        if task.get("status") not in {"waiting_review", "done"}:
            print("Task needs review before done. Run /task review first.")
            return
        task = manager.mark_done(task["id"])
        print(f"Task done: {task.get('id')} - {task.get('title')}")
        return

    if lower in {"/task close", "/task clear"}:
        print("This command is disabled in Project Control Layer. Use /task done after review.")
        return

    print_unknown_command(stripped)


def handle_command(command: str, root: Path, log_file: Path, model: str) -> bool:
    command = command.strip()
    lower = command.lower()

    if lower == "/about":
        print_about()
    elif lower == "/help":
        print(help_text())
    elif lower == "/status":
        print_status(root, log_file, model)
    elif lower == "/doctor":
        handle_doctor_command(root)
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
    elif lower in {"/exit", "/bye", "/q"}:
        print("Bye.")
        append_log(log_file, "SYSTEM", "Session closed by user.")
        return False
    else:
        print_unknown_command(command)
    append_log(log_file, "COMMAND", command)
    return True


def main() -> int:
    configure_output()
    root = project_root()
    model = load_model_name(root)
    system_prompt = load_system_prompt(root)
    log_file = create_log(root, model)
    messages = [{"role": "system", "content": system_prompt}]

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from ui.startup_screen import render_startup_screen

    render_startup_screen(
        version=VERSION,
        model=model,
        internet_status=INTERNET,
        status="Ready",
        log_path=log_file,
    )

    ready, details = check_ollama_ready(model)
    if not ready:
        print(details)
        print("")
        print("VEGA will stay in CLI mode. Commands like /docs, /model, /status, /doctor, /help, and /exit are available.")
        append_log(log_file, "WARNING", details)

    while True:
        try:
            user_input = input("VEGA> ").strip()
            # [VEGA_DOCS_COMMANDS_CALL_START]
            _vega_input = str(user_input).strip()
            _vega_input_lower = _vega_input.lower()
            if _vega_input_lower == '/docs' or _vega_input_lower.startswith('/docs '):
                try:
                    import sys as _vega_sys
                    from pathlib import Path as _VegaPath
                    _vega_project_root = _VegaPath(__file__).resolve().parents[1]
                    if str(_vega_project_root) not in _vega_sys.path:
                        _vega_sys.path.insert(0, str(_vega_project_root))
                    from rag.commands import handle_docs_command as _vega_handle_docs_command
                    _vega_handle_docs_command(str(user_input), _vega_project_root)
                except Exception as _vega_docs_error:
                    print(f'VEGA docs command error: {_vega_docs_error}')
                continue
            # [VEGA_DOCS_COMMANDS_CALL_END]
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            append_log(log_file, "SYSTEM", "Session interrupted.")
            return 0

        if not user_input:
            continue

        append_log(log_file, "USER", user_input)

        if user_input.startswith("/"):
            if not handle_command(user_input, root, log_file, model):
                return 0
            continue

        model = load_model_name(root)
        try:
            from core.model_router import get_model_status

            model_status = get_model_status(root)
        except Exception:
            model_status = {"model_installed": True, "current_model": model}

        if not model_status.get("model_installed", True):
            response = model_unavailable_chat_message(str(model_status.get("current_model", model)))
            print(response)
            append_log(log_file, "ERROR", response)
            continue

        messages.append({"role": "user", "content": user_input})
        ok, response = call_ollama_chat(model, messages)
        label = "VEGA" if ok else "ERROR"
        print(response)
        append_log(log_file, label, response)
        if ok:
            messages.append({"role": "assistant", "content": response})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


