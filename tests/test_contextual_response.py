from dataclasses import dataclass

from core.contextual_response import (
    format_plan_execution_response,
)
from core.plan_executor import (
    PlanExecutionResult,
    PlanExecutionStatus,
    StepExecutionResult,
)
from core.tool_executor import ToolExecutionStatus


def _success_result(
    tool_name: str,
    data: object,
) -> PlanExecutionResult:
    return PlanExecutionResult(
        status=PlanExecutionStatus.COMPLETED,
        goal="Test response formatting",
        steps=(
            StepExecutionResult(
                step_id=1,
                tool_name=tool_name,
                status=ToolExecutionStatus.SUCCESS,
                data=data,
            ),
        ),
    )


def test_search_results_are_user_facing() -> None:
    result = _success_result(
        "search_in_files",
        {
            "ok": True,
            "error": None,
            "data": [
                {
                    "path": "core/runtime.py",
                    "line": 42,
                    "text": "class Runtime:",
                },
            ],
        },
    )

    output = format_plan_execution_response(
        result
    )

    assert "Found 1 matches." in output
    assert "core/runtime.py:42" in output
    assert "class Runtime:" in output
    assert '"ok": true' not in output


def test_empty_search_has_clear_message() -> None:
    result = _success_result(
        "search_in_files",
        {
            "ok": True,
            "error": None,
            "data": [],
        },
    )

    output = format_plan_execution_response(
        result
    )

    assert output == "No matches found."



def test_search_mapping_payload_is_supported() -> None:
    result = _success_result(
        "search_in_files",
        {
            "ok": True,
            "error": None,
            "data": {
                "results": [],
            },
        },
    )

    output = format_plan_execution_response(
        result
    )

    assert output == "No matches found."

def test_file_summary_is_formatted() -> None:
    result = _success_result(
        "summarize_file",
        {
            "ok": True,
            "error": None,
            "data": {
                "path": "README.md",
                "size": 1500,
                "lines": 70,
                "truncated": False,
                "first_meaningful_lines": [
                    "# VEGA",
                    "Local coding agent",
                ],
                "python_symbols": [],
            },
        },
    )

    output = format_plan_execution_response(
        result
    )

    assert "File summary: README.md" in output
    assert "Size: 1500 bytes" in output
    assert "Lines: 70" in output
    assert "# VEGA" in output


@dataclass
class FakeGitResult:
    ok: bool = True
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def test_empty_git_diff_is_clear() -> None:
    result = _success_result(
        "git_diff",
        FakeGitResult(),
    )

    output = format_plan_execution_response(
        result
    )

    assert output == "No unstaged changes."


def test_git_diff_content_is_preserved() -> None:
    result = _success_result(
        "git_diff_cached",
        FakeGitResult(
            stdout=(
                "diff --git a/core/a.py b/core/a.py\n"
                "+new line"
            )
        ),
    )

    output = format_plan_execution_response(
        result
    )

    assert "Git changes:" in output
    assert "diff --git" in output
    assert "+new line" in output


def test_blocked_plan_has_user_facing_error() -> None:
    result = PlanExecutionResult(
        status=PlanExecutionStatus.BLOCKED,
        goal="Unsafe request",
        error="WRITE permission is not automatic",
        blocked_step_id=1,
        blocked_tool_name="write_file",
    )

    output = format_plan_execution_response(
        result
    )

    assert output.startswith("Request blocked.")
    assert "WRITE permission" in output


def test_explicit_mode_shows_tool_name() -> None:
    result = _success_result(
        "search_in_files",
        {
            "ok": True,
            "error": None,
            "data": [],
        },
    )

    output = format_plan_execution_response(
        result,
        intent="project_search",
        show_tools=True,
    )

    assert "Intent: project_search" in output
    assert "Tool: search_in_files" in output
    assert "No matches found." in output


def test_test_run_uses_bounded_diagnostic_summary() -> None:
    result = _success_result(
        "test_run",
        {
            "ok": True,
            "error": None,
            "data": {
                "stdout": "SECRET-FULL-PYTEST-OUTPUT" * 100,
                "diagnostics": {
                    "returncode": 0,
                    "timed_out": False,
                    "duration_ms": 35123,
                    "reason_code": "",
                    "warning": None,
                    "stdout_summary": {
                        "truncated": False,
                        "pytest_counts": {"passed": 1102, "skipped": 7},
                    },
                },
            },
        },
    )

    output = format_plan_execution_response(result)

    assert "Status: passed" in output
    assert "Exit code: 0" in output
    assert "Result: 1102 passed, 7 skipped" in output
    assert "SECRET-FULL-PYTEST-OUTPUT" not in output


def test_compile_run_uses_bounded_diagnostic_summary() -> None:
    result = _success_result(
        "terminal_run",
        {
            "ok": True,
            "error": None,
            "data": {
                "stdout": "Listing many files" * 100,
                "diagnostics": {
                    "returncode": 0,
                    "timed_out": False,
                    "duration_ms": 125,
                    "reason_code": "",
                    "warning": None,
                    "stdout_summary": {
                        "truncated": False,
                        "pytest_counts": {},
                    },
                },
            },
        },
    )

    output = format_plan_execution_response(result)

    assert "Compile check" in output
    assert "Status: passed" in output
    assert "Listing many files" not in output
