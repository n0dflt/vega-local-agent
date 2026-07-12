import json
import unittest
from pathlib import Path

from core.command_handler import (
    FILE_HELP,
    GIT_HELP,
    _resolve_tool_executor,
    handle_file_command,
    handle_git_command,
    tools_list_text,
)
from core.tool_executor import ToolExecutor
from tools.git_tools import GitCommandResult


def file_success(value=None):
    return {
        "ok": True,
        "error": None,
        "data": value if value is not None else {"result": "ok"},
    }


def git_result(
    *,
    ok: bool = True,
    stdout: str = "output\n",
    stderr: str = "",
) -> GitCommandResult:
    return GitCommandResult(
        ok=ok,
        command=("git", "test"),
        stdout=stdout,
        stderr=stderr,
        returncode=0 if ok else 1,
    )


class CommandHandlerToolExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = []
        self.workspace = Path("test-workspace")

        def list_dir(*, path):
            self.calls.append(("list_dir", {"path": path}))
            return file_success()

        def read_file(*, path):
            self.calls.append(("read_file", {"path": path}))
            return file_success()

        def find_file(*, name):
            self.calls.append(("find_file", {"name": name}))
            return file_success()

        def search_in_files(*, query):
            self.calls.append(("search_in_files", {"query": query}))
            return file_success()

        def summarize_file(*, path):
            self.calls.append(("summarize_file", {"path": path}))
            return file_success()

        def git_status(*, workspace):
            self.calls.append(("git_status", {"workspace": workspace}))
            return git_result()

        def git_diff(*, workspace):
            self.calls.append(("git_diff", {"workspace": workspace}))
            return git_result()

        def git_diff_cached(*, workspace):
            self.calls.append(("git_diff_cached", {"workspace": workspace}))
            return git_result()

        def git_log(*, workspace, limit):
            self.calls.append(
                ("git_log", {"workspace": workspace, "limit": limit})
            )
            return git_result()

        def git_branch(*, workspace):
            self.calls.append(("git_branch", {"workspace": workspace}))
            return git_result()

        self.registry = {
            "list_dir": list_dir,
            "read_file": read_file,
            "find_file": find_file,
            "search_in_files": search_in_files,
            "summarize_file": summarize_file,
            "git_status": git_status,
            "git_diff": git_diff,
            "git_diff_cached": git_diff_cached,
            "git_log": git_log,
            "git_branch": git_branch,
        }
        self.executor = ToolExecutor(self.registry)

    def test_file_list_passes_path(self) -> None:
        handle_file_command("/file list src", self.executor)
        self.assertEqual(self.calls, [("list_dir", {"path": "src"})])

    def test_file_list_defaults_to_current_path(self) -> None:
        handle_file_command("/file list", self.executor)
        self.assertEqual(self.calls, [("list_dir", {"path": "."})])

    def test_file_read_passes_path(self) -> None:
        handle_file_command("/file read README.md", self.executor)
        self.assertEqual(self.calls, [("read_file", {"path": "README.md"})])

    def test_file_find_passes_name(self) -> None:
        handle_file_command("/file find agent.py", self.executor)
        self.assertEqual(self.calls, [("find_file", {"name": "agent.py"})])

    def test_file_search_passes_query(self) -> None:
        handle_file_command("/file search executor", self.executor)
        self.assertEqual(
            self.calls,
            [("search_in_files", {"query": "executor"})],
        )

    def test_file_summary_passes_path(self) -> None:
        handle_file_command("/file summary core", self.executor)
        self.assertEqual(self.calls, [("summarize_file", {"path": "core"})])

    def test_file_summarize_uses_summary_tool(self) -> None:
        handle_file_command("/file summarize core", self.executor)
        self.assertEqual(self.calls, [("summarize_file", {"path": "core"})])

    def test_unknown_file_action_does_not_execute(self) -> None:
        output = handle_file_command("/file delete x", self.executor)
        self.assertEqual(output, FILE_HELP)
        self.assertEqual(self.calls, [])

    def test_file_executor_error_is_formatted(self) -> None:
        output = handle_file_command("/file list", ToolExecutor({}))
        self.assertTrue(output.startswith("File command error:"))

    def test_file_tool_error_is_preserved(self) -> None:
        executor = ToolExecutor(
            {
                "list_dir": lambda *, path: {
                    "ok": False,
                    "error": "blocked",
                    "data": None,
                }
            }
        )
        self.assertEqual(
            handle_file_command("/file list", executor),
            "File command error: blocked",
        )

    def test_file_success_keeps_json_format(self) -> None:
        data = {"items": ["one", "two"]}
        executor = ToolExecutor(
            {"list_dir": lambda *, path: file_success(data)}
        )
        output = handle_file_command("/file list", executor)
        self.assertEqual(output, json.dumps(data, ensure_ascii=False, indent=2))

    def test_git_status_passes_workspace(self) -> None:
        handle_git_command("/git status", self.workspace, self.executor)
        self.assertEqual(
            self.calls,
            [("git_status", {"workspace": self.workspace})],
        )

    def test_git_diff_passes_workspace(self) -> None:
        handle_git_command("/git diff", self.workspace, self.executor)
        self.assertEqual(
            self.calls,
            [("git_diff", {"workspace": self.workspace})],
        )

    def test_git_diff_cached_uses_fixed_tool(self) -> None:
        handle_git_command("/git diff --cached", self.workspace, self.executor)
        self.assertEqual(
            self.calls,
            [("git_diff_cached", {"workspace": self.workspace})],
        )

    def test_git_log_defaults_to_ten(self) -> None:
        handle_git_command("/git log", self.workspace, self.executor)
        self.assertEqual(
            self.calls,
            [("git_log", {"workspace": self.workspace, "limit": 10})],
        )

    def test_git_log_passes_explicit_limit(self) -> None:
        handle_git_command("/git log 25", self.workspace, self.executor)
        self.assertEqual(
            self.calls,
            [("git_log", {"workspace": self.workspace, "limit": 25})],
        )

    def test_git_branch_passes_workspace(self) -> None:
        handle_git_command("/git branch", self.workspace, self.executor)
        self.assertEqual(
            self.calls,
            [("git_branch", {"workspace": self.workspace})],
        )

    def test_invalid_log_limit_does_not_execute(self) -> None:
        output = handle_git_command(
            "/git log invalid",
            self.workspace,
            self.executor,
        )
        self.assertIn("limit must be an integer", output)
        self.assertEqual(self.calls, [])

    def test_unknown_git_action_returns_help(self) -> None:
        output = handle_git_command("/git push", self.workspace, self.executor)
        self.assertEqual(output, GIT_HELP)
        self.assertEqual(self.calls, [])

    def test_git_executor_error_is_formatted(self) -> None:
        output = handle_git_command(
            "/git status",
            self.workspace,
            ToolExecutor({}),
        )
        self.assertTrue(output.startswith("Git command error:"))

    def test_git_tool_error_is_preserved(self) -> None:
        executor = ToolExecutor(
            {
                "git_status": lambda *, workspace: git_result(
                    ok=False,
                    stdout="",
                    stderr="denied",
                )
            }
        )
        self.assertEqual(
            handle_git_command("/git status", self.workspace, executor),
            "Git command error: denied",
        )

    def test_empty_git_status_reports_clean_tree(self) -> None:
        executor = ToolExecutor(
            {"git_status": lambda *, workspace: git_result(stdout="")}
        )
        self.assertEqual(
            handle_git_command("/git status", self.workspace, executor),
            "Git working tree is clean.",
        )

    def test_empty_git_diff_keeps_message(self) -> None:
        executor = ToolExecutor(
            {"git_diff": lambda *, workspace: git_result(stdout="")}
        )
        self.assertEqual(
            handle_git_command("/git diff", self.workspace, executor),
            "No unstaged changes.",
        )

    def test_empty_git_branch_reports_detached_head(self) -> None:
        executor = ToolExecutor(
            {"git_branch": lambda *, workspace: git_result(stdout="")}
        )
        self.assertEqual(
            handle_git_command("/git branch", self.workspace, executor),
            "Git repository is in detached HEAD state.",
        )

    def test_tools_list_uses_executor_names(self) -> None:
        output = tools_list_text(ToolExecutor({"alpha": lambda: None}))
        self.assertEqual(output, "Available tools:\n  alpha")

    def test_tools_list_is_sorted(self) -> None:
        output = tools_list_text(
            ToolExecutor({"zeta": lambda: None, "alpha": lambda: None})
        )
        self.assertEqual(output.splitlines()[1:], ["  alpha", "  zeta"])

    def test_tools_list_does_not_execute_tools(self) -> None:
        calls = []
        tools_list_text(ToolExecutor({"tool": lambda: calls.append(True)}))
        self.assertEqual(calls, [])

    def test_tools_run_command_is_not_advertised(self) -> None:
        output = tools_list_text(ToolExecutor({"tool": lambda: None}))
        self.assertNotIn("/tools run", output)

    def test_invalid_executor_type_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            handle_file_command("/file list", object())

    def test_resolver_reuses_injected_executor(self) -> None:
        self.assertIs(_resolve_tool_executor(self.executor), self.executor)


if __name__ == "__main__":
    unittest.main()
