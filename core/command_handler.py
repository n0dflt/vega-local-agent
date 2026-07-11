"""Command handlers shared by the VEGA CLI."""

from __future__ import annotations

import json
import shlex

from tools.file_tools import (
    find_file,
    list_dir,
    read_file,
    search_in_files,
    summarize_file,
)
from tools.git_tools import (
    git_branch,
    git_diff,
    git_diff_cached,
    git_log,
    git_status,
)
from tools.patch_tools import (
    apply_patch,
    list_patches,
    propose_patch_from_file,
    rollback_patch,
    show_patch,
)


FILE_HELP = """File commands (safe read-only access):
  /file list <path>       List a project directory
  /file read <path>       Read a UTF-8 text file
  /file find <name>       Find files by name
  /file search <query>    Search text in project files
  /file summary <path>    Show a deterministic file summary"""


PATCH_HELP = """Patch commands (confirmed safe writes):
  /patch list                         List all saved patches
  /patch list pending                 List pending patches
  /patch list applied                 List applied patches
  /patch list rolled_back             List rolled-back patches
  /patch show <patch_id>              Show patch metadata and diff
  /patch propose <target> <proposal>  Propose target content from another file
  /patch apply <patch_id> CONFIRM     Apply a pending patch
  /patch rollback <patch_id> CONFIRM  Roll back an applied patch

Examples:
  /patch propose README.md README.proposal.md "Update documentation"
  /patch show patch-20260710T150136Z-6ba02018
  /patch apply patch-20260710T150136Z-6ba02018 CONFIRM"""


GIT_HELP = """Git commands (safe read-only access):
  /git status          Show short repository status
  /git diff            Show unstaged changes
  /git diff --cached   Show staged changes
  /git log             Show 10 recent commits
  /git log <limit>     Show from 1 to 100 recent commits
  /git branch          Show current branch"""


MEMORY_HELP = """Project Memory commands:
  /memory add <kind> <text>  Save a decision, fact, or constraint
  /memory list [kind]        List saved project memory
  /memory search <query>     Search saved project memory
  /memory stats              Show Project Memory statistics"""


TERMINAL_HELP = """Terminal commands:
  /run list
  /run <command_id>

Only predefined safe validation commands can be executed.
Arbitrary shell commands are not supported."""

TEST_HELP = """Test Runner commands:
  /test                     Run all VEGA tests
  /test list                List available test groups
  /test <group_id>          Run one predefined test group

Examples:
  /test
  /test terminal
  /test terminal-tools
  /test terminal-commands
  /test web
  /test web-tools
  /test web-commands
  /test web-cli

Arbitrary pytest arguments are not supported."""


INTERNET_HELP = """Internet access commands:
  /internet             Show current internet state
  /internet status      Show current internet state
  /internet on          Enable internet for this VEGA process
  /internet off         Disable internet for this VEGA process

Internet access is always OFF when a new VEGA process starts."""


WEB_HELP = """Controlled web commands:
  /web fetch <https-url>  Fetch one bounded text resource

Restrictions:
  HTTPS only
  redirects are blocked
  local and private addresses are blocked
  binary content is blocked"""


DOCGEN_HELP = """Documentation Builder commands:
  /docgen          Show Documentation Builder help
  /docgen status   Show configured documentation status
  /docgen check    Check required documentation and version references
  /docgen build    Create pending patches for managed documentation

Documentation Builder does not apply documentation changes automatically."""

def _clean_cli_token(value: str) -> str:
    return value.strip().strip('"').strip("'")


def handle_file_command(command: str) -> str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"File command error: {exc}"

    if len(parts) == 1:
        return FILE_HELP

    action = _clean_cli_token(parts[1]).lower()
    argument = " ".join(parts[2:]).strip().strip('"')

    if action == "list":
        result = list_dir(argument or ".")
    elif action == "read" and argument:
        result = read_file(argument)
    elif action == "find" and argument:
        result = find_file(argument)
    elif action == "search" and argument:
        result = search_in_files(argument)
    elif action in {"summary", "summarize"} and argument:
        result = summarize_file(argument)
    else:
        return FILE_HELP

    if not result["ok"]:
        return f"File command error: {result['error']}"

    return json.dumps(
        result["data"],
        ensure_ascii=False,
        indent=2,
    )


def handle_patch_command(command: str) -> str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Patch command error: {exc}"

    if len(parts) == 1:
        return PATCH_HELP

    action = _clean_cli_token(parts[1]).lower()

    if action == "list":
        if len(parts) > 3:
            return PATCH_HELP

        status = None
        if len(parts) == 3:
            status = _clean_cli_token(parts[2]).lower()

        result = list_patches(status)

    elif action == "show" and len(parts) == 3:
        patch_id = _clean_cli_token(parts[2])
        result = show_patch(patch_id)

    elif action == "propose" and len(parts) >= 4:
        target_path = _clean_cli_token(parts[2])
        proposal_path = _clean_cli_token(parts[3])

        reason = " ".join(
            _clean_cli_token(part)
            for part in parts[4:]
        ).strip()

        result = propose_patch_from_file(
            target_path,
            proposal_path,
            reason,
        )

    elif action == "apply" and len(parts) in {3, 4}:
        patch_id = _clean_cli_token(parts[2])

        confirmed = (
            len(parts) == 4
            and _clean_cli_token(parts[3]) == "CONFIRM"
        )

        result = apply_patch(
            patch_id,
            confirmed=confirmed,
        )

    elif action == "rollback" and len(parts) in {3, 4}:
        patch_id = _clean_cli_token(parts[2])

        confirmed = (
            len(parts) == 4
            and _clean_cli_token(parts[3]) == "CONFIRM"
        )

        result = rollback_patch(
            patch_id,
            confirmed=confirmed,
        )

    else:
        return PATCH_HELP

    if not result["ok"]:
        return f"Patch command error: {result['error']}"

    return json.dumps(
        result["data"],
        ensure_ascii=False,
        indent=2,
    )


def handle_git_command(command: str) -> str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Git command error: {exc}"

    if len(parts) == 1:
        return GIT_HELP

    action = _clean_cli_token(parts[1]).lower()

    if action == "status" and len(parts) == 2:
        result = git_status(".")

        if result.ok and not result.stdout.strip():
            return "Git working tree is clean."

    elif action == "diff" and len(parts) == 2:
        result = git_diff(".")

        if result.ok and not result.stdout.strip():
            return "No unstaged changes."

    elif (
        action == "diff"
        and len(parts) == 3
        and _clean_cli_token(parts[2]).lower() == "--cached"
    ):
        result = git_diff_cached(".")

        if result.ok and not result.stdout.strip():
            return "No staged changes."

    elif action == "log" and len(parts) in {2, 3}:
        if len(parts) == 2:
            limit = 10
        else:
            try:
                limit = int(_clean_cli_token(parts[2]))
            except ValueError:
                return "Git command error: log limit must be an integer from 1 to 100."

        result = git_log(".", limit)

    elif action == "branch" and len(parts) == 2:
        result = git_branch(".")

        if result.ok and not result.stdout.strip():
            return "Git repository is in detached HEAD state."

    else:
        return GIT_HELP

    if not result.ok:
        error = result.stderr.strip() or "Git command failed."
        return f"Git command error: {error}"

    return result.stdout.rstrip()

def handle_memory_command(command: str, project_root=None) -> str:
    from memory.project_memory import add_memory, get_memory_stats, list_memories, search_memories

    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Memory command error: {exc}"

    parts = [_clean_cli_token(part) for part in parts]
    if len(parts) == 1:
        return MEMORY_HELP

    action = parts[1].lower()
    if action == "add" and len(parts) >= 4:
        result = add_memory(parts[2], " ".join(parts[3:]), project_root)
    elif action == "list" and len(parts) in {2, 3}:
        result = list_memories(parts[2] if len(parts) == 3 else None, project_root)
    elif action == "search" and len(parts) >= 3:
        result = search_memories(" ".join(parts[2:]), project_root)
    elif action == "stats" and len(parts) == 2:
        result = get_memory_stats(project_root)
    else:
        return MEMORY_HELP

    if not result["ok"]:
        return f"Memory command error: {result['error']}"
    return json.dumps(result["data"], ensure_ascii=False, indent=2)


def handle_terminal_command(command: str, project_root=None) -> str:
    from tools.terminal_tools import list_allowed_commands, run_allowed_command

    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Terminal command error: {exc}"

    parts = [_clean_cli_token(part) for part in parts]
    if len(parts) == 1:
        return TERMINAL_HELP
    if len(parts) != 2:
        return (
            "Terminal command error: Exactly one command id is allowed.\n"
            "Run /run list to see allowed commands."
        )

    command_id = parts[1].strip().lower()
    if command_id == "list":
        result = list_allowed_commands(project_root)
        if not result["ok"]:
            return f"Terminal command error: {result['error']}"
        lines = ["Allowed terminal commands:"]
        for item in result["data"]:
            state = "enabled" if item["enabled"] else "disabled"
            lines.append(
                f"  {item['id']:<16} {item['description']} "
                f"(timeout: {item['timeout_seconds']}s, {state})"
            )
        return "\n".join(lines)

    result = run_allowed_command(command_id, project_root)
    if result["data"] is None:
        return (
            f"Terminal command error: {result['error']}\n"
            "Run /run list to see allowed commands."
        )

    data = result["data"]
    lines = [
        f"Command: {data['command_id']}",
        f"Status: {'PASS' if result['ok'] else 'FAIL'}",
        f"Exit code: {data['returncode']}",
        f"Duration: {data['duration_ms']} ms",
    ]
    if data["stdout"]:
        lines.extend(["", data["stdout"].rstrip()])
    if data["stderr"]:
        lines.extend(["", "Errors:", data["stderr"].rstrip()])
    if data.get("warning"):
        lines.extend(["", data["warning"]])
    return "\n".join(lines)


def handle_test_command(command: str, project_root=None) -> str:
    from tools.test_tools import list_test_groups, run_test_group

    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Test command error: {exc}"

    parts = [_clean_cli_token(part) for part in parts]

    if len(parts) == 1:
        group_id = "all"
    elif len(parts) == 2:
        argument = parts[1].strip().lower()

        if argument == "list":
            result = list_test_groups(project_root)

            if not result["ok"]:
                return f"Test command error: {result['error']}"

            lines = ["Available test groups:"]

            for item in result["data"]:
                if not item["available"]:
                    state = "unavailable"
                elif not item["enabled"]:
                    state = "disabled"
                else:
                    state = "enabled"

                lines.append(
                    f"  {item['id']:<20} "
                    f"{item['description']} ({state})"
                )

            return "\n".join(lines)

        group_id = argument
    else:
        return (
            "Test command error: Exactly one test group is allowed.\n"
            "Run /test list to see available groups."
        )

    result = run_test_group(group_id, project_root)

    if result["data"] is None:
        return (
            f"Test command error: {result['error']}\n"
            "Run /test list to see available groups."
        )

    data = result["data"]

    lines = [
        f"Test group: {data['group_id']}",
        f"Description: {data['description']}",
        f"Status: {'PASS' if result['ok'] else 'FAIL'}",
        f"Exit code: {data['returncode']}",
        f"Duration: {data['duration_ms']} ms",
    ]

    if data.get("timed_out"):
        lines.append("Timed out: yes")

    if data["stdout"]:
        lines.extend(["", data["stdout"].rstrip()])

    if data["stderr"]:
        lines.extend(["", "Errors:", data["stderr"].rstrip()])

    if data.get("warning"):
        lines.extend(["", data["warning"]])

    return "\n".join(lines)


def handle_internet_command(command: str) -> str:
    from core.internet_state import (
        is_internet_enabled,
        set_internet_enabled,
    )

    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Internet command error: {exc}"

    parts = [
        _clean_cli_token(part)
        for part in parts
    ]

    if len(parts) == 1:
        enabled = is_internet_enabled()
        return (
            "Internet access: "
            f"{'ON' if enabled else 'OFF'}."
        )

    if len(parts) != 2:
        return INTERNET_HELP

    action = parts[1].lower()

    if action == "status":
        enabled = is_internet_enabled()
        return (
            "Internet access: "
            f"{'ON' if enabled else 'OFF'}."
        )

    if action == "on":
        set_internet_enabled(True)
        return (
            "Internet access enabled for this "
            "VEGA process."
        )

    if action == "off":
        set_internet_enabled(False)
        return (
            "Internet access disabled for this "
            "VEGA process."
        )

    return INTERNET_HELP


def handle_web_command(
    command: str,
    project_root=None,
) -> str:
    from tools.web_tools import fetch_url

    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Web command error: {exc}"

    parts = [
        _clean_cli_token(part)
        for part in parts
    ]

    if (
        len(parts) != 3
        or parts[1].lower() != "fetch"
    ):
        return WEB_HELP

    result = fetch_url(
        parts[2],
        project_root,
    )

    if not result["ok"]:
        return f"Web command error: {result['error']}"

    data = result["data"]

    lines = [
        f"URL: {data['url']}",
        f"Status: {data['status_code']}",
        f"Content-Type: {data['content_type']}",
        f"Bytes read: {data['bytes_read']}",
        (
            "Truncated: "
            f"{'yes' if data['truncated'] else 'no'}"
        ),
    ]

    if data.get("warning"):
        lines.extend(
            [
                "",
                data["warning"],
            ]
        )

    lines.extend(
        [
            "",
            data["text"],
        ]
    )

    return "\n".join(lines)

def handle_docgen_command(
    command: str,
    project_root=None,
) -> str:
    """Handle safe Documentation Builder commands."""

    from tools.doc_builders import build_documentation
    from tools.doc_tools import (
        check_documentation,
        get_documentation_status,
    )

    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Documentation command error: {exc}"

    parts = [
        _clean_cli_token(part)
        for part in parts
    ]

    if len(parts) == 1:
        return DOCGEN_HELP

    if len(parts) != 2:
        return DOCGEN_HELP

    action = parts[1].strip().lower()

    if action == "status":
        result = get_documentation_status(project_root)

        if not result["ok"]:
            return (
                "Documentation command error: "
                f"{result['error']}"
            )

        data = result["data"]

        lines = [
            "Documentation Builder status",
            f"Policy: {data['policy_path']}",
            f"Project version: {data['version']}",
            f"Managed documents: {data['managed_count']}",
            f"Manual documents: {data['manual_count']}",
            "",
            "Documents:",
        ]

        for document in data["documents"]:
            state = (
                "OK"
                if document["exists"]
                else "MISSING"
            )

            if document["version_current"] is True:
                version_state = "current"
            elif document["version_current"] is False:
                version_state = "stale"
            else:
                version_state = "not checked"

            lines.append(
                f"  [{state}] {document['id']}: "
                f"{document['path']} "
                f"({document['kind']}, "
                f"version: {version_state})"
            )

        return "\n".join(lines)

    if action == "check":
        result = check_documentation(project_root)

        if not result["ok"]:
            return (
                "Documentation command error: "
                f"{result['error']}"
            )

        data = result["data"]

        lines = [
            "Documentation check",
            (
                "Status: PASS"
                if data["passed"]
                else "Status: FAIL"
            ),
            f"Project version: {data['version']}",
            f"Errors: {data['error_count']}",
        ]

        if not data["issues"]:
            lines.extend(
                [
                    "",
                    "No documentation issues found.",
                ]
            )
        else:
            lines.extend(["", "Issues:"])

            for issue in data["issues"]:
                lines.append(
                    f"  [{issue['severity'].upper()}] "
                    f"{issue['path']}: "
                    f"{issue['message']}"
                )

        return "\n".join(lines)

    if action == "build":
        result = build_documentation(project_root)

        if not result["ok"]:
            return (
                "Documentation command error: "
                f"{result['error']}"
            )

        data = result["data"]

        lines = [
            "Documentation build",
            (
                "Status: PASS"
                if data["passed"]
                else "Status: FAIL"
            ),
            f"Project version: {data['version']}",
            (
                "Pending patches created: "
                f"{data['created_count']}"
            ),
            (
                "Skipped documents: "
                f"{data['skipped_count']}"
            ),
            f"Errors: {data['error_count']}",
            "Automatic apply: NO",
        ]

        if data["created"]:
            lines.extend(["", "Created patches:"])

            for item in data["created"]:
                lines.append(
                    f"  [PENDING] "
                    f"{item['document_id']}: "
                    f"{item['path']} -> "
                    f"{item['patch_id']}"
                )

        if data["skipped"]:
            lines.extend(["", "Skipped documents:"])

            for item in data["skipped"]:
                lines.append(
                    f"  [SKIPPED] "
                    f"{item['document_id']}: "
                    f"{item['path']} "
                    f"({item['reason']})"
                )

        if data["errors"]:
            lines.extend(["", "Build errors:"])

            for item in data["errors"]:
                lines.append(
                    f"  [ERROR] "
                    f"{item['document_id']}: "
                    f"{item['path']}: "
                    f"{item['message']}"
                )

        return "\n".join(lines)

    return DOCGEN_HELP


def tools_list_text() -> str:
    from tools.registry import list_tools

    return "Available tools:\n" + "\n".join(
        f"  {name}"
        for name in list_tools()
    )
