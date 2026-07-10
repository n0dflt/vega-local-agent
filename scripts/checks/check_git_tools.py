"""Standalone checks for VEGA safe Git tools."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.git_tools import (  # noqa: E402
    git_branch,
    git_diff,
    git_diff_cached,
    git_log,
    git_status,
)


def run_command(
    arguments: list[str],
    workspace: Path,
) -> subprocess.CompletedProcess[str]:
    """Run a setup command only inside the temporary test repository."""

    return subprocess.run(
        arguments,
        cwd=workspace,
        shell=False,
        timeout=10,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def require(condition: bool, message: str) -> None:
    """Fail the check with a readable message."""

    if not condition:
        raise AssertionError(message)

    print(f"PASS: {message}")


def require_command(
    arguments: list[str],
    workspace: Path,
) -> None:
    """Run a temporary-repository setup command and require success."""

    result = run_command(arguments, workspace)

    require(
        result.returncode == 0,
        (
            f"command succeeded: {' '.join(arguments)}"
            if result.returncode == 0
            else (
                f"command failed: {' '.join(arguments)}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
        ),
    )


def main() -> int:
    """Run all checks."""

    if shutil.which("git") is None:
        print("FAIL: Git executable was not found.")
        return 1

    with tempfile.TemporaryDirectory(prefix="vega_git_tools_") as temp_dir:
        temp_root = Path(temp_dir)
        repository = temp_root / "repository"
        repository.mkdir()

        require_command(["git", "init"], repository)
        require_command(
            ["git", "config", "user.name", "VEGA Test"],
            repository,
        )
        require_command(
            ["git", "config", "user.email", "vega-test@example.invalid"],
            repository,
        )

        test_file = repository / "sample.txt"
        test_file.write_text("alpha\n", encoding="utf-8")

        require_command(["git", "add", "sample.txt"], repository)
        require_command(
            ["git", "commit", "-m", "initial test commit"],
            repository,
        )

        status_clean = git_status(repository)
        require(status_clean.ok, "git_status succeeds in a repository")
        require(
            status_clean.stdout.strip() == "",
            "git_status reports a clean repository",
        )

        test_file.write_text("alpha\nbeta\n", encoding="utf-8")

        status_modified = git_status(repository)
        require(status_modified.ok, "git_status succeeds after modification")
        require(
            "sample.txt" in status_modified.stdout,
            "git_status reports the modified file",
        )

        unstaged_diff = git_diff(repository)
        require(unstaged_diff.ok, "git_diff succeeds")
        require(
            "+beta" in unstaged_diff.stdout,
            "git_diff contains the unstaged change",
        )

        require_command(["git", "add", "sample.txt"], repository)

        cached_diff = git_diff_cached(repository)
        require(cached_diff.ok, "git_diff_cached succeeds")
        require(
            "+beta" in cached_diff.stdout,
            "git_diff_cached contains the staged change",
        )

        history_default = git_log(repository)
        require(history_default.ok, "git_log succeeds with default limit")
        require(
            "initial test commit" in history_default.stdout,
            "git_log contains the test commit",
        )

        history_one = git_log(repository, 1)
        require(history_one.ok, "git_log accepts limit 1")

        invalid_limits = [0, -1, 101, "10", None, True, False]

        for invalid_limit in invalid_limits:
            invalid_result = git_log(repository, invalid_limit)  # type: ignore[arg-type]
            require(
                not invalid_result.ok,
                f"git_log rejects invalid limit {invalid_limit!r}",
            )

        branch = git_branch(repository)
        require(branch.ok, "git_branch succeeds")
        require(
            bool(branch.stdout.strip()),
            "git_branch returns the current branch name",
        )

        non_repository = temp_root / "not_a_repository"
        non_repository.mkdir()

        non_repo_status = git_status(non_repository)
        require(
            not non_repo_status.ok,
            "git_status rejects a directory outside a Git repository",
        )

        missing_workspace = temp_root / "missing"

        missing_status = git_status(missing_workspace)
        require(
            not missing_status.ok,
            "git_status rejects a missing workspace",
        )

        import tools.git_tools as git_tools_module

        dangerous_names = (
            "git_add",
            "git_commit",
            "git_tag",
            "git_push",
            "git_pull",
            "git_fetch",
            "git_checkout",
            "git_switch",
            "git_reset",
            "git_restore",
            "git_clean",
            "git_merge",
            "git_rebase",
            "git_config",
            "run_git_command",
        )

        for name in dangerous_names:
            require(
                not hasattr(git_tools_module, name),
                f"dangerous function is unavailable: {name}",
            )

    print("PASS: all safe Git Tools checks completed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(1)
    except Exception as exc:
        print(f"FAIL: unexpected error: {exc}")
        raise SystemExit(1)
