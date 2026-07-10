"""Safe read-only Git tools for VEGA."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Final


_GIT_TIMEOUT_SECONDS: Final[int] = 10
_MAX_OUTPUT_CHARS: Final[int] = 100_000
_MIN_LOG_LIMIT: Final[int] = 1
_MAX_LOG_LIMIT: Final[int] = 100
_TRUNCATED_MARKER: Final[str] = "`n[output truncated]"


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    """Result returned by a safe Git command."""

    ok: bool
    command: tuple[str, ...]
    stdout: str
    stderr: str
    returncode: int


def _truncate_output(value: str | None) -> str:
    """Limit command output to a safe size."""

    text = value or ""
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text

    available = _MAX_OUTPUT_CHARS - len(_TRUNCATED_MARKER)
    return text[:available] + _TRUNCATED_MARKER


def _error_result(
    command: tuple[str, ...],
    message: str,
    returncode: int = -1,
) -> GitCommandResult:
    """Create a controlled error result."""

    return GitCommandResult(
        ok=False,
        command=command,
        stdout="",
        stderr=message,
        returncode=returncode,
    )


def _resolve_workspace(
    workspace: str | Path,
    command: tuple[str, ...],
) -> tuple[Path | None, GitCommandResult | None]:
    """Validate and resolve the requested workspace."""

    if not isinstance(workspace, (str, Path)):
        return None, _error_result(
            command,
            "Workspace must be a string or pathlib.Path.",
        )

    try:
        path = Path(workspace).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return None, _error_result(
            command,
            f"Unable to resolve workspace: {exc}",
        )

    if not path.exists():
        return None, _error_result(
            command,
            f"Workspace does not exist: {path}",
        )

    if not path.is_dir():
        return None, _error_result(
            command,
            f"Workspace is not a directory: {path}",
        )

    return path, None


def _run_git(
    workspace: str | Path,
    arguments: tuple[str, ...],
) -> GitCommandResult:
    """Run one predefined read-only Git command."""

    command = ("git", *arguments)
    resolved_workspace, validation_error = _resolve_workspace(
        workspace,
        command,
    )

    if validation_error is not None:
        return validation_error

    assert resolved_workspace is not None

    try:
        completed = subprocess.run(
            list(command),
            cwd=resolved_workspace,
            shell=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError:
        return _error_result(
            command,
            "Git executable was not found.",
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""

        timeout_message = (
            f"Git command timed out after {_GIT_TIMEOUT_SECONDS} seconds."
        )
        if stderr:
            timeout_message = f"{timeout_message}\n{stderr}"

        return GitCommandResult(
            ok=False,
            command=command,
            stdout=_truncate_output(stdout),
            stderr=_truncate_output(timeout_message),
            returncode=-1,
        )
    except PermissionError as exc:
        return _error_result(
            command,
            f"Permission denied while running Git: {exc}",
        )
    except OSError as exc:
        return _error_result(
            command,
            f"Unable to run Git: {exc}",
        )

    return GitCommandResult(
        ok=completed.returncode == 0,
        command=command,
        stdout=_truncate_output(completed.stdout),
        stderr=_truncate_output(completed.stderr),
        returncode=completed.returncode,
    )


def git_status(workspace: str | Path) -> GitCommandResult:
    """Return the short status of the Git working tree."""

    return _run_git(
        workspace,
        ("status", "--short"),
    )


def git_diff(workspace: str | Path) -> GitCommandResult:
    """Return unstaged changes without external diff tools."""

    return _run_git(
        workspace,
        ("diff", "--no-ext-diff"),
    )


def git_diff_cached(workspace: str | Path) -> GitCommandResult:
    """Return staged changes without external diff tools."""

    return _run_git(
        workspace,
        ("diff", "--cached", "--no-ext-diff"),
    )


def git_log(
    workspace: str | Path,
    limit: int = 10,
) -> GitCommandResult:
    """Return a limited one-line Git history."""

    placeholder_command = (
        "git",
        "log",
        "--oneline",
        "-n",
        str(limit),
    )

    if isinstance(limit, bool) or not isinstance(limit, int):
        return _error_result(
            placeholder_command,
            "Git log limit must be an integer from 1 to 100.",
        )

    if not _MIN_LOG_LIMIT <= limit <= _MAX_LOG_LIMIT:
        return _error_result(
            placeholder_command,
            "Git log limit must be between 1 and 100.",
        )

    return _run_git(
        workspace,
        ("log", "--oneline", "-n", str(limit)),
    )


def git_branch(workspace: str | Path) -> GitCommandResult:
    """Return the current Git branch."""

    return _run_git(
        workspace,
        ("branch", "--show-current"),
    )


__all__ = [
    "GitCommandResult",
    "git_status",
    "git_diff",
    "git_diff_cached",
    "git_log",
    "git_branch",
]
