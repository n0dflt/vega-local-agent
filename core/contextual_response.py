from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from core.plan_executor import (
    PlanExecutionResult,
    PlanExecutionStatus,
    StepExecutionResult,
)


DEFAULT_RESPONSE_LIMIT = 8_000
DEFAULT_VALUE_LIMIT = 6_000
SEARCH_SNIPPET_LIMIT = 240


def _trim(
    value: str,
    limit: int,
) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False

    return value[:limit].rstrip() + "\n...[truncated]", True


def _read_value(
    value: Any,
    name: str,
    default: Any = None,
) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)

    try:
        return getattr(value, name, default)
    except Exception:
        return default


def _unwrap_tool_data(
    value: Any,
) -> tuple[Any, str]:
    if not isinstance(value, Mapping):
        return value, ""

    if "ok" not in value or "data" not in value:
        return value, ""

    if value.get("ok") is False:
        error = value.get("error")
        return None, str(
            error or "tool reported an unsuccessful result"
        )

    return value.get("data"), ""


def _json_text(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
    except (TypeError, ValueError):
        return repr(value)


def _format_search_results(value: Any) -> str:
    data, envelope_error = _unwrap_tool_data(value)

    if envelope_error:
        return f"Search failed: {envelope_error}"

    if isinstance(data, Mapping):
        results = data.get("results")

        if results is None:
            return _format_generic(data)

        data = results

    if not isinstance(data, Sequence) or isinstance(
        data,
        (str, bytes, bytearray),
    ):
        return _format_generic(data)

    if not data:
        return "No matches found."

    lines = [f"Found {len(data)} matches."]

    for item in data:
        if not isinstance(item, Mapping):
            lines.append(f"- {_json_text(item)}")
            continue

        path = str(item.get("path", "unknown"))
        line_number = item.get("line")
        text = str(item.get("text", "")).strip()

        text, _ = _trim(
            text,
            SEARCH_SNIPPET_LIMIT,
        )

        location = path

        if line_number is not None:
            location += f":{line_number}"

        if text:
            lines.append(f"- {location} - {text}")
        else:
            lines.append(f"- {location}")

    return "\n".join(lines)


def _format_file_summary(value: Any) -> str:
    data, envelope_error = _unwrap_tool_data(value)

    if envelope_error:
        return f"File analysis failed: {envelope_error}"

    if not isinstance(data, Mapping):
        return _format_generic(data)

    path = str(data.get("path", "unknown"))
    size = data.get("size")
    line_count = data.get("lines")
    truncated = bool(data.get("truncated", False))

    lines = [f"File summary: {path}"]

    if size is not None:
        lines.append(f"Size: {size} bytes")

    if line_count is not None:
        lines.append(f"Lines: {line_count}")

    lines.append(
        "Source truncated: "
        + ("yes" if truncated else "no")
    )

    meaningful = data.get("first_meaningful_lines", ())

    if (
        isinstance(meaningful, Sequence)
        and not isinstance(
            meaningful,
            (str, bytes, bytearray),
        )
        and meaningful
    ):
        lines.extend(["", "Key lines:"])

        for item in meaningful:
            text, _ = _trim(
                str(item).strip(),
                SEARCH_SNIPPET_LIMIT,
            )

            if text:
                lines.append(f"- {text}")

    symbols = data.get("python_symbols", ())

    if (
        isinstance(symbols, Sequence)
        and not isinstance(
            symbols,
            (str, bytes, bytearray),
        )
        and symbols
    ):
        lines.extend(["", "Python symbols:"])

        for symbol in symbols:
            if isinstance(symbol, Mapping):
                symbol_type = str(
                    symbol.get("type", "symbol")
                )
                symbol_name = str(
                    symbol.get("name", "unknown")
                )
                lines.append(
                    f"- {symbol_type} {symbol_name}"
                )
            else:
                lines.append(f"- {symbol}")

    return "\n".join(lines)


def _format_read_file(value: Any) -> str:
    data, envelope_error = _unwrap_tool_data(value)

    if envelope_error:
        return f"File read failed: {envelope_error}"

    if not isinstance(data, Mapping):
        return _format_generic(data)

    path = str(data.get("path", "unknown"))
    size = data.get("size")
    truncated = bool(data.get("truncated", False))
    text = str(data.get("text", ""))

    lines = [f"File: {path}"]

    if size is not None:
        lines.append(f"Size: {size} bytes")

    lines.append(
        "Content truncated: "
        + ("yes" if truncated else "no")
    )

    if text:
        text, _ = _trim(
            text,
            DEFAULT_VALUE_LIMIT,
        )
        lines.extend(["", text])

    return "\n".join(lines)


def _format_git_result(
    tool_name: str,
    value: Any,
) -> str:
    data, envelope_error = _unwrap_tool_data(value)

    if envelope_error:
        return f"Git operation failed: {envelope_error}"

    stdout = _read_value(data, "stdout", "")
    stderr = _read_value(data, "stderr", "")
    returncode = _read_value(data, "returncode")

    stdout = str(stdout or "").rstrip()
    stderr = str(stderr or "").rstrip()

    if not stdout:
        if tool_name == "git_status":
            return "Git working tree is clean."

        if tool_name == "git_diff":
            return "No unstaged changes."

        if tool_name == "git_diff_cached":
            return "No staged changes."

        if stderr:
            return f"Git output:\n{stderr}"

        return "Git operation completed without output."

    stdout, truncated = _trim(
        stdout,
        DEFAULT_VALUE_LIMIT,
    )

    lines = ["Git changes:", "", stdout]

    if returncode not in (None, 0):
        lines.insert(
            1,
            f"Exit code: {returncode}",
        )

    if stderr:
        stderr, _ = _trim(
            stderr,
            DEFAULT_VALUE_LIMIT // 2,
        )
        lines.extend(["", "Git warnings:", stderr])

    if truncated:
        lines.append("")
        lines.append("Output was truncated.")

    return "\n".join(lines)


def _format_status_mapping(
    title: str,
    value: Any,
) -> str:
    data, envelope_error = _unwrap_tool_data(value)

    if envelope_error:
        return f"{title} failed: {envelope_error}"

    if not isinstance(data, Mapping):
        return _format_generic(data)

    lines = [title]

    priority_keys = (
        "status",
        "ready",
        "passed",
        "version",
        "branch",
        "clean",
        "summary",
        "errors",
        "warnings",
        "missing",
        "checks",
    )

    rendered: set[str] = set()

    for key in priority_keys:
        if key not in data:
            continue

        rendered.add(key)
        label = key.replace("_", " ").capitalize()
        item = data[key]

        if isinstance(item, (Mapping, list, tuple)):
            item_text = _json_text(item)
            lines.extend(
                [
                    f"{label}:",
                    item_text,
                ]
            )
        else:
            lines.append(f"{label}: {item}")

    for key, item in data.items():
        if key in rendered:
            continue

        label = str(key).replace(
            "_",
            " ",
        ).capitalize()

        if isinstance(item, (Mapping, list, tuple)):
            item_text = _json_text(item)
            lines.extend(
                [
                    f"{label}:",
                    item_text,
                ]
            )
        else:
            lines.append(f"{label}: {item}")

    return "\n".join(lines)


def _format_generic(value: Any) -> str:
    data, envelope_error = _unwrap_tool_data(value)

    if envelope_error:
        return f"Tool failed: {envelope_error}"

    if data is None:
        return "Task completed without output."

    stdout = _read_value(data, "stdout")

    if stdout is not None:
        text = str(stdout).rstrip()

        if text:
            text, _ = _trim(
                text,
                DEFAULT_VALUE_LIMIT,
            )
            return text

    if isinstance(data, str):
        text, _ = _trim(
            data,
            DEFAULT_VALUE_LIMIT,
        )
        return text or "Task completed without output."

    text = _json_text(data)
    text, _ = _trim(
        text,
        DEFAULT_VALUE_LIMIT,
    )
    return text


def _format_process_summary(title: str, value: Any) -> str:
    data, envelope_error = _unwrap_tool_data(value)
    if envelope_error:
        return f"{title}\nTool failed: {envelope_error}"
    diagnostics = _read_value(data, "diagnostics")
    if not isinstance(diagnostics, Mapping):
        return f"{title}\n{_format_generic(value)}"

    returncode = diagnostics.get("returncode")
    timed_out = diagnostics.get("timed_out") is True
    reason_code = diagnostics.get("reason_code")
    status = "passed" if returncode == 0 and not timed_out and not reason_code else "failed"
    lines = [title, f"Status: {status}"]
    if isinstance(returncode, int) and not isinstance(returncode, bool):
        lines.append(f"Exit code: {returncode}")
    duration_ms = diagnostics.get("duration_ms")
    if isinstance(duration_ms, int) and duration_ms >= 0:
        lines.append(f"Duration: {duration_ms / 1000:.2f} seconds")
    stdout_summary = diagnostics.get("stdout_summary")
    if isinstance(stdout_summary, Mapping):
        counts = stdout_summary.get("pytest_counts")
        if isinstance(counts, Mapping) and counts:
            ordered_labels = (
                "passed",
                "failed",
                "skipped",
                "errors",
                "warnings",
                "xfailed",
                "xpassed",
                "deselected",
            )
            count_parts = [
                f"{counts[label]} {label}"
                for label in ordered_labels
                if isinstance(counts.get(label), int)
            ]
            if count_parts:
                lines.append("Result: " + ", ".join(count_parts))
        if stdout_summary.get("truncated") is True:
            lines.append("Output: truncated in the structured tool result")
    warning = diagnostics.get("warning")
    if isinstance(warning, str) and warning:
        lines.append(f"Warning: {warning}")
    return "\n".join(lines)


def format_step_result(
    step: StepExecutionResult,
) -> str:
    if not isinstance(step, StepExecutionResult):
        raise TypeError(
            "step must be a StepExecutionResult instance"
        )

    if not step.ok:
        detail = (
            step.error
            or step.status.value
        )
        return f"Tool failed: {detail}"

    if step.tool_name == "search_in_files":
        return _format_search_results(step.data)

    if step.tool_name == "summarize_file":
        return _format_file_summary(step.data)

    if step.tool_name == "read_file":
        return _format_read_file(step.data)

    if step.tool_name in {
        "git_status",
        "git_diff",
        "git_diff_cached",
    }:
        return _format_git_result(
            step.tool_name,
            step.data,
        )

    if step.tool_name == "test_run":
        return _format_process_summary("Test suite", step.data)

    if step.tool_name == "terminal_run":
        return _format_process_summary("Compile check", step.data)

    if step.tool_name == "release_status":
        return _format_status_mapping(
            "Release status",
            step.data,
        )

    if step.tool_name == "documentation_status":
        return _format_status_mapping(
            "Documentation status",
            step.data,
        )

    return _format_generic(step.data)


def format_plan_execution_response(
    result: PlanExecutionResult,
    *,
    intent: str = "",
    show_tools: bool = False,
    max_chars: int = DEFAULT_RESPONSE_LIMIT,
) -> str:
    """Create a bounded user-facing response for a plan result."""

    if not isinstance(result, PlanExecutionResult):
        raise TypeError(
            "result must be a PlanExecutionResult instance"
        )

    if not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError(
            "max_chars must be a positive integer"
        )

    if result.status is PlanExecutionStatus.BLOCKED:
        detail = result.error or "blocked by policy"
        return f"Request blocked.\nReason: {detail}"

    if result.status is PlanExecutionStatus.FAILED:
        detail = result.error or "execution failed"
        return (
            "The task could not be completed."
            f"\nReason: {detail}"
        )

    if not result.steps:
        return "Task completed."

    sections: list[str] = []

    for step in result.steps:
        body = format_step_result(step)

        if show_tools:
            body = (
                f"Tool: {step.tool_name}"
                f"\n{body}"
            )

        sections.append(body)

    response = "\n\n".join(sections)

    if intent and show_tools:
        response = (
            f"Intent: {intent}"
            f"\n{response}"
        )

    response, _ = _trim(
        response,
        max_chars,
    )

    return response


__all__ = [
    "format_plan_execution_response",
    "format_step_result",
]
