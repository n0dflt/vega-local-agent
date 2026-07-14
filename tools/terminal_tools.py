"""Safe execution of predefined VEGA validation commands."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TerminalPolicyError(ValueError):
    """Controlled Terminal Tools policy error."""


COMMAND_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_EXECUTABLES = {"python", "py"}
SUPPORTED_SCHEMA_VERSION = 1
MAX_TIMEOUT_SECONDS = 300
TRUNCATION_MARKER = "\n[output truncated]"


def _result(data: Any = None, error: str | None = None) -> dict:
    return {"ok": error is None, "error": error, "data": data if error is None else None}


def _project_root(project_root: Path | str | None) -> Path:
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise TerminalPolicyError("Project root does not exist.") from exc
    if not root.is_dir():
        raise TerminalPolicyError("Project root is not a directory.")
    return root


def _positive_integer(value: Any, field: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TerminalPolicyError(f"{field} must be a positive integer.")
    if maximum is not None and value > maximum:
        raise TerminalPolicyError(f"{field} must not exceed {maximum}.")
    return value


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_policy_path(path: Path, root: Path) -> None:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise TerminalPolicyError("Terminal policy file was not found.") from exc
    if not resolved.is_file() or not _is_within(resolved, root):
        raise TerminalPolicyError("Terminal policy must be a file inside the project root.")


def _looks_like_project_path(argument: str, root: Path) -> bool:
    return (
        "/" in argument
        or "\\" in argument
        or argument.lower().endswith(".py")
        or (not argument.startswith("-") and (root / argument).exists())
    )


def _validate_argv_paths(argv: tuple[str, ...], root: Path) -> None:
    for argument in argv[1:]:
        candidate = Path(argument)
        if argument == ".." or ".." in candidate.parts:
            raise TerminalPolicyError("Terminal command path escapes the project root.")
        if not _looks_like_project_path(argument, root):
            continue
        if candidate.is_absolute() or argument.startswith("\\\\"):
            raise TerminalPolicyError("Terminal command paths must be project-relative.")
        resolved = (root / candidate).resolve(strict=False)
        if not _is_within(resolved, root):
            raise TerminalPolicyError("Terminal command path escapes the project root.")


def _load_policy(root: Path) -> tuple[list[dict], int]:
    policy_path = root / "config" / "allowed_commands.json"
    _validate_policy_path(policy_path, root)
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise TerminalPolicyError("Terminal policy JSON is invalid.") from exc
    except OSError as exc:
        raise TerminalPolicyError("Terminal policy could not be read.") from exc

    if not isinstance(policy, dict):
        raise TerminalPolicyError("Terminal policy root must be an object.")
    if policy.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise TerminalPolicyError("Terminal policy schema_version is not supported.")
    max_output_chars = _positive_integer(policy.get("max_output_chars"), "max_output_chars")
    default_timeout = _positive_integer(
        policy.get("default_timeout_seconds", 60),
        "default_timeout_seconds",
        MAX_TIMEOUT_SECONDS,
    )
    commands = policy.get("commands")
    if not isinstance(commands, list):
        raise TerminalPolicyError("Terminal policy commands must be a list.")

    validated = []
    command_ids: set[str] = set()
    for command in commands:
        if not isinstance(command, dict):
            raise TerminalPolicyError("Each terminal command must be an object.")
        command_id = command.get("id")
        if not isinstance(command_id, str) or not COMMAND_ID_PATTERN.fullmatch(command_id):
            raise TerminalPolicyError("Terminal command id must use lowercase-kebab-case.")
        if command_id in command_ids:
            raise TerminalPolicyError(f"Duplicate terminal command id: {command_id}")
        command_ids.add(command_id)

        description = command.get("description")
        argv = command.get("argv")
        enabled = command.get("enabled")
        if not isinstance(description, str):
            raise TerminalPolicyError(f"Description for {command_id} must be a string.")
        if not isinstance(argv, list) or not argv or not all(
            isinstance(item, str) and item for item in argv
        ):
            raise TerminalPolicyError(f"argv for {command_id} must be a non-empty list of strings.")
        executable = argv[0].lower()
        if executable not in ALLOWED_EXECUTABLES or Path(argv[0]).name.lower() != executable:
            raise TerminalPolicyError("Terminal executable is not allowed.")
        if not isinstance(enabled, bool):
            raise TerminalPolicyError(f"enabled for {command_id} must be boolean.")
        timeout_seconds = _positive_integer(
            command.get("timeout_seconds", default_timeout),
            "timeout_seconds",
            MAX_TIMEOUT_SECONDS,
        )
        fixed_argv = tuple(argv)
        _validate_argv_paths(fixed_argv, root)
        validated.append({
            "id": command_id,
            "description": description,
            "argv": fixed_argv,
            "timeout_seconds": timeout_seconds,
            "enabled": enabled,
        })
    return validated, max_output_chars


def _normalize_command_id(command_id: str) -> str:
    normalized = command_id.strip().lower() if isinstance(command_id, str) else ""
    if not COMMAND_ID_PATTERN.fullmatch(normalized):
        raise TerminalPolicyError("Invalid terminal command id.")
    return normalized


def list_allowed_commands(project_root: Path | str | None = None) -> dict:
    try:
        commands, _ = _load_policy(_project_root(project_root))
        return _result(commands)
    except (TerminalPolicyError, OSError) as exc:
        return _result(error=str(exc))


def get_allowed_command(command_id: str, project_root: Path | str | None = None) -> dict:
    try:
        normalized = _normalize_command_id(command_id)
        commands, _ = _load_policy(_project_root(project_root))
        command = next((item for item in commands if item["id"] == normalized), None)
        if command is None:
            raise TerminalPolicyError(f"Unknown command id: {normalized}")
        if not command["enabled"]:
            raise TerminalPolicyError("Terminal command is disabled.")
        return _result(command)
    except (TerminalPolicyError, OSError) as exc:
        return _result(error=str(exc))


def _truncate_output(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit] + TRUNCATION_MARKER, True


def _write_audit(root: Path, record: dict) -> str | None:
    try:
        audit_path = root / "logs" / "terminal" / "terminal_commands.jsonl"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return None
    except OSError as exc:
        return f"Terminal audit warning: {exc}"


def run_allowed_command(command_id: str, project_root: Path | str | None = None) -> dict:
    try:
        root = _project_root(project_root)
        normalized = _normalize_command_id(command_id)
        commands, max_output_chars = _load_policy(root)
        command = next((item for item in commands if item["id"] == normalized), None)
        if command is None:
            raise TerminalPolicyError(f"Unknown command id: {normalized}")
        if not command["enabled"]:
            raise TerminalPolicyError("Terminal command is disabled.")

        argv = command["argv"]
        executable = argv[0].lower()
        if executable not in ALLOWED_EXECUTABLES or Path(argv[0]).name.lower() != executable:
            raise TerminalPolicyError("Terminal executable is not allowed.")

        # Python commands remain allowlisted by their configured argv.  At
        # execution time they use the interpreter that is already running
        # VEGA, so a launcher-selected runtime does not depend on PATH.
        effective_argv = (
            (sys.executable, *argv[1:])
            if executable in {"python", "python.exe"}
            else argv
        )

        environment = os.environ.copy()
        for variable in ("PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONPATH", "PYTHONHOME"):
            environment.pop(variable, None)
        environment["PYTHONNOUSERSITE"] = "1"

        started = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(
                list(effective_argv),
                cwd=root,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=command["timeout_seconds"],
                check=False,
                env=environment,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = -1
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            timeout_message = f"Command timed out after {command['timeout_seconds']} seconds."
            stderr = f"{stderr.rstrip()}\n{timeout_message}" if stderr else timeout_message
        except OSError as exc:
            return _result(error=f"Terminal command could not be started: {exc}")

        duration_ms = int((time.monotonic() - started) * 1000)
        stdout, stdout_truncated = _truncate_output(stdout, max_output_chars)
        stderr, stderr_truncated = _truncate_output(stderr, max_output_chars)
        truncated = stdout_truncated or stderr_truncated
        ok = returncode == 0 and not timed_out
        data = {
            "command_id": normalized,
            "argv": effective_argv,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "timed_out": timed_out,
            "truncated": truncated,
            "duration_ms": duration_ms,
            "warning": None,
        }
        data["warning"] = _write_audit(root, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command_id": normalized,
            "argv": effective_argv,
            "returncode": returncode,
            "ok": ok,
            "timed_out": timed_out,
            "truncated": truncated,
            "duration_ms": duration_ms,
        })
        return {"ok": ok, "error": None, "data": data}
    except (TerminalPolicyError, OSError) as exc:
        return _result(error=str(exc))
