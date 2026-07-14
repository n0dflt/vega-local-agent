"""Safe test-group runner for VEGA."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.terminal_tools import (
    list_allowed_commands,
    run_allowed_command,
)


TEST_GROUP_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

TEST_GROUPS: dict[str, dict[str, str]] = {
    "workflow": {
        "command_id": "tests-workflow",
        "description": "Run the focused controlled-workflow safety suite.",
    },
    "all": {
        "command_id": "tests",
        "description": "Run all VEGA tests.",
    },
    "terminal": {
        "command_id": "tests-terminal",
        "description": "Run all Terminal Tools tests.",
    },
    "terminal-tools": {
        "command_id": "tests-terminal-tools",
        "description": "Run Terminal Tools unit tests.",
    },
    "terminal-commands": {
        "command_id": "tests-terminal-commands",
        "description": "Run Terminal command handler tests.",
    },
    "web": {
        "command_id": "tests-web",
        "description": "Run all Controlled Internet Layer tests.",
    },
    "web-tools": {
        "command_id": "tests-web-tools",
        "description": "Run web safety and Web Tools unit tests.",
    },
    "web-commands": {
        "command_id": "tests-web-commands",
        "description": "Run internet and web command handler tests.",
    },
    "web-cli": {
        "command_id": "tests-web-cli",
        "description": "Run Controlled Internet Layer CLI routing tests.",
    },
    "docs": {
        "command_id": "tests-docs",
        "description": "Run all Documentation Builder tests.",
    },
}


class RunnerPolicyError(ValueError):
    """Controlled Test Runner error."""


def _result(
    data: Any = None,
    error: str | None = None,
    *,
    reason_code: str = "",
    diagnostics: Mapping[str, Any] | None = None,
) -> dict:
    return {
        "ok": error is None,
        "error": error,
        "data": data if error is None else None,
        "reason_code": reason_code,
        "diagnostics": dict(diagnostics) if diagnostics is not None else None,
    }


def _normalize_test_group(group_id: str) -> str:
    normalized = (
        group_id.strip().lower()
        if isinstance(group_id, str)
        else ""
    )

    if not TEST_GROUP_PATTERN.fullmatch(normalized):
        raise RunnerPolicyError("Invalid test group id.")

    return normalized


def list_test_groups(
    project_root: Path | str | None = None,
) -> dict:
    """Return configured VEGA test groups and their availability."""

    allowed_result = list_allowed_commands(project_root)

    if not allowed_result["ok"]:
        return _result(
            error=(
                "Test command policy could not be loaded: "
                f"{allowed_result['error']}"
            )
        )

    allowed_commands = {
        item["id"]: item
        for item in allowed_result["data"]
    }

    groups = []

    for group_id, definition in TEST_GROUPS.items():
        command_id = definition["command_id"]
        command = allowed_commands.get(command_id)

        groups.append(
            {
                "id": group_id,
                "description": definition["description"],
                "command_id": command_id,
                "available": command is not None,
                "enabled": bool(
                    command
                    and command["enabled"]
                ),
            }
        )

    return _result(groups)


def run_test_group(
    group_id: str = "all",
    project_root: Path | str | None = None,
) -> dict:
    """Run one predefined test group through Terminal Tools."""

    try:
        normalized = _normalize_test_group(group_id)
    except RunnerPolicyError as exc:
        return _result(error=str(exc))

    definition = TEST_GROUPS.get(normalized)

    if definition is None:
        available = ", ".join(sorted(TEST_GROUPS))

        return _result(
            error=(
                f"Unknown test group: {normalized}. "
                f"Available groups: {available}"
            )
        )

    command_result = run_allowed_command(
        definition["command_id"],
        project_root,
    )

    if command_result["data"] is None:
        reason_code = command_result.get("reason_code", "")
        diagnostics = command_result.get("diagnostics")
        if reason_code == "runtime_unavailable":
            error = "Test runner could not start the configured Python runtime."
        else:
            error = command_result["error"] or "Test command could not be started."
        return _result(
            error=error,
            reason_code=reason_code,
            diagnostics=diagnostics if isinstance(diagnostics, Mapping) else None,
        )

    if not isinstance(command_result["data"], Mapping):
        return _result(
            error="Test result could not be parsed.",
            reason_code="result_parse_error",
        )

    data = dict(command_result["data"])
    returncode = data.get("returncode")
    timed_out = data.get("timed_out")
    if (
        isinstance(returncode, bool)
        or not isinstance(returncode, int)
        or not isinstance(timed_out, bool)
    ):
        return _result(
            error="Test result could not be parsed.",
            reason_code="result_parse_error",
        )

    if timed_out:
        reason_code = "timeout"
    elif command_result["ok"] and returncode == 0:
        reason_code = ""
    elif not command_result["ok"] and returncode != 0:
        reason_code = "test_failure"
    else:
        return _result(
            error="Test result could not be parsed.",
            reason_code="result_parse_error",
        )

    data["group_id"] = normalized
    data["description"] = definition["description"]
    data["reason_code"] = reason_code
    diagnostics = data.get("diagnostics")
    if isinstance(diagnostics, Mapping):
        diagnostics = dict(diagnostics)
        diagnostics["tool"] = "test_run"
        diagnostics["group_id"] = normalized
        diagnostics["reason_code"] = reason_code
        data["diagnostics"] = diagnostics
    else:
        diagnostics = None

    return {
        "ok": command_result["ok"],
        "error": command_result["error"],
        "data": data,
        "reason_code": reason_code,
        "diagnostics": diagnostics,
    }
