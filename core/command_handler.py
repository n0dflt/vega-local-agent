"""Command handlers shared by the VEGA CLI."""

from __future__ import annotations

import json
import shlex

from core.tool_confirmation import (
    ToolConfirmationManager,
    execute_tool_with_confirmation,
)
from core.tool_executor import ToolExecutor, ToolRequest
from core.tool_executor_factory import build_production_tool_executor
from permissions.session_grants import SessionGrantStore
from tools.patch_tools import (
    apply_patch,
    list_patches,
    propose_patch_from_file,
    rollback_patch,
    show_patch,
)

from tools.release_tools import (
    build_release_notes,
    get_release_status,
    load_release_policy,
    run_release_check,
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
  /patch apply <patch_id>             Apply a pending patch after approval
  /patch rollback <patch_id>          Roll back an applied patch after approval

Examples:
  /patch propose README.md README.proposal.md "Update documentation"
  /patch show patch-20260710T150136Z-6ba02018
  /patch apply patch-20260710T150136Z-6ba02018"""


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

RELEASE_HELP = """Release Manager commands:
  /release          Show Release Manager help
  /release status   Show release readiness without running commands
  /release check    Run configured release validation commands
  /release notes    Build an in-memory release notes draft

Release Manager is read-only.
It cannot commit, tag, push, or publish a GitHub release."""

WORKFLOW_HELP = """Coding Workflow commands:
  /workflow list
  /workflow types
  /workflow start bug-fix <task>
  /workflow start test <allowlisted-group>
  /workflow start review <unstaged|staged>
  /workflow start feature <task>
  /workflow start refactor <task>
  /workflow attach-patch <pending_patch_id> [test-group]
  /workflow approve patch <workflow_id>
  /workflow approve tests <workflow_id>
  /workflow status [workflow_id]
  /workflow show <workflow_id>
  /workflow resume [workflow_id]
  /workflow cancel [workflow_id]
  /workflow rollback <workflow_id>
  /workflow history
  /workflow review
  /workflow recovery-status [workflow_id]
  /workflow checkpoints [workflow_id]
  /workflow recover <checkpoint_id> CONFIRM"""

PERMISSIONS_HELP = """Permission session grants:
  /permissions grants
  /permissions revoke <tool_name>
  /permissions clear"""


def handle_permissions_command(command: str, session_grants: SessionGrantStore) -> str:
    if not isinstance(session_grants, SessionGrantStore):
        raise TypeError("session_grants must be a SessionGrantStore instance")
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Permissions command error: {exc}"
    parts = [_clean_cli_token(part) for part in parts]
    if len(parts) == 1:
        return PERMISSIONS_HELP
    action = parts[1]
    if action == "grants" and len(parts) == 2:
        grants = session_grants.list_grants()
        if not grants:
            return "Active session grants: none."
        return "Active session grants:\n" + "\n".join(f"  {item.tool_name}" for item in grants)
    if action == "revoke" and len(parts) == 3:
        name = parts[2]
        try:
            revoked = session_grants.revoke(name)
        except Exception as exc:
            return f"Permissions command error: {exc}"
        return (f"Session grant revoked: {name}." if revoked else f"Session grant was not active: {name}.")
    if action == "clear" and len(parts) == 2:
        count = session_grants.clear()
        return f"Cleared {count} session grant(s)."
    return PERMISSIONS_HELP


def handle_workflow_command(
    command: str,
    project_root=None,
    *,
    confirmation_manager=None,
    engine=None,
    execution_context=None,
    recovery_manager=None,
) -> str:
    """Execute one deterministic coding-workflow command."""
    from pathlib import Path

    from workflows import WorkflowEngine, WorkflowRecoveryManager, default_registry
    from workflows.checkpoint_store import CheckpointStorageError
    from workflows.models import WorkflowError
    from workflows.models import validate_workflow_id
    from workflows.project_context import ProjectContextAdapter
    from workflows.recovery_manager import (
        RecoveryConflictError,
        RecoveryConfirmationError,
        RecoveryError,
        RecoveryNotAvailableError,
        RecoveryStorageError,
    )
    from workflows.recovery_models import RecoveryValidationError

    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Workflow command error: {exc}"
    if len(parts) == 1:
        return WORKFLOW_HELP
    parts = [_clean_cli_token(part) for part in parts]
    action = parts[1]

    if action in {"recovery-status", "checkpoints", "recover"}:
        root = Path(project_root) if project_root is not None else Path.cwd()
        try:
            manager = recovery_manager or WorkflowRecoveryManager(root)
            if action == "recovery-status":
                if len(parts) not in {2, 3}:
                    return "Workflow command error: Usage: /workflow recovery-status [workflow_id]"
                workflow_id = parts[2] if len(parts) == 3 else None
                if workflow_id is not None:
                    validate_workflow_id(workflow_id)
                return _recovery_diagnosis_text(manager.diagnose(workflow_id))
            if action == "checkpoints":
                if len(parts) not in {2, 3}:
                    return "Workflow command error: Usage: /workflow checkpoints [workflow_id]"
                workflow_id = parts[2] if len(parts) == 3 else None
                if workflow_id is not None:
                    validate_workflow_id(workflow_id)
                checkpoints = manager._active_checkpoints()
                if workflow_id is not None:
                    checkpoints = [item for item in checkpoints if item.workflow_id == workflow_id]
                return _active_checkpoints_text(checkpoints)
            if len(parts) != 4:
                return "Workflow command error: Usage: /workflow recover <checkpoint_id> CONFIRM"
            if parts[3] != "CONFIRM":
                return "Workflow confirmation error: The exact confirmation token CONFIRM is required."
            return _recovery_result_text(manager.recover(parts[2], parts[3]))
        except RecoveryNotAvailableError as exc:
            return f"Workflow recovery unavailable: {exc}"
        except RecoveryConflictError as exc:
            return f"Workflow recovery conflict: {exc}"
        except RecoveryConfirmationError as exc:
            return f"Workflow confirmation error: {exc}"
        except (RecoveryStorageError, CheckpointStorageError) as exc:
            return f"Workflow recovery storage error: {exc}"
        except RecoveryValidationError as exc:
            return f"Workflow recovery validation error: {exc}"
        except RecoveryError as exc:
            return f"Workflow recovery error: {exc}"
        except ValueError as exc:
            return f"Workflow recovery validation error: {exc}"
        except Exception:
            return "Workflow internal error: recovery command failed safely."

    if engine is None:
        engine = WorkflowEngine(
            Path(project_root) if project_root is not None else Path.cwd(),
            default_registry(),
            confirmation_manager=confirmation_manager,
            project_context=ProjectContextAdapter(
                Path(project_root) if project_root is not None else Path.cwd(),
                execution_context,
            ),
        )
    try:
        if action == "types" and len(parts) == 2:
            return "Available workflows:\n" + "\n".join(f"  {name}" for name in engine.list_workflows())
        if action == "list" and len(parts) == 2:
            active = engine.status()
            history = engine.history()
            records = ([] if active is None else [active]) + history
            if not records:
                return "Workflow list is empty.\nAvailable workflows: " + ", ".join(engine.list_workflows())
            return "Workflow list:\n" + "\n".join(
                f"  {run.workflow_id} {run.workflow_type} {run.status.value}"
                for run in records
            ) + "\nAvailable workflows: " + ", ".join(engine.list_workflows())
        if action == "start":
            if len(parts) < 4:
                return "Usage: /workflow start <bug-fix|test|review|feature|refactor> <task-or-scope>"
            workflow_type = parts[2]
            patch_id = None
            task_start = 3
            if parts[3] == "--patch":
                if len(parts) < 6:
                    return "Usage: /workflow start <type> --patch <pending_patch_id> <task>"
                patch_id = parts[4].strip().strip('"')
                task_start = 5
            task = " ".join(parts[task_start:]).strip().strip('"')
            run = engine.start(workflow_type, task, patch_id=patch_id)
            return _workflow_text(run)
        if action == "attach-patch" and len(parts) in {3, 4}:
            group = parts[3] if len(parts) == 4 else "workflow"
            return _workflow_text(
                engine.attach_patch(parts[2].strip().strip('"'), test_group=group)
            )
        if action == "approve" and len(parts) == 4:
            if parts[2] == "patch":
                return _workflow_text(engine.approve_patch(parts[3]))
            if parts[2] == "tests":
                return _workflow_text(engine.approve_tests(parts[3]))
            return WORKFLOW_HELP
        if action == "status" and len(parts) in {2, 3}:
            run = engine.status(parts[2] if len(parts) == 3 else None)
            return "No active workflow." if run is None else _workflow_text(run)
        if action == "show" and len(parts) == 3:
            return _workflow_text(engine.show(parts[2]))
        if action == "resume" and len(parts) in {2, 3}:
            return _workflow_text(
                engine.resume(parts[2]) if len(parts) == 3 else engine.resume()
            )
        if action == "confirm" and len(parts) == 2:
            return _workflow_text(engine.confirm())
        if action == "cancel" and len(parts) in {2, 3}:
            return _workflow_text(
                engine.cancel(parts[2]) if len(parts) == 3 else engine.cancel()
            )
        if action == "rollback" and len(parts) == 3:
            return _workflow_text(engine.rollback(parts[2]))
        if action == "history" and len(parts) == 2:
            history = engine.history()
            if not history:
                return "Workflow history is empty."
            return "Workflow history:\n" + "\n".join(
                f"  {run.workflow_id} {run.workflow_type} {run.status.value}"
                for run in history
            )
        if action == "review" and len(parts) == 2:
            candidates = []
            current = engine.status()
            if current is not None:
                candidates.append(current)
            if hasattr(engine, "history"):
                candidates.extend(engine.history())
            reports = next(
                (run.review_results for run in candidates if getattr(run, "review_results", [])),
                [],
            )
            if not reports:
                return "No review result is available."
            report = reports[-1]
            findings = report.get("findings", []) if isinstance(report, dict) else []
            if "passed" in report:
                passed = report.get("passed") is True
                severity = report.get("highest_severity", "info")
                files = report.get("reviewed_files", [])
            else:
                blockers = [
                    item for item in findings
                    if isinstance(item, dict) and item.get("severity") in {"critical", "high"}
                ]
                passed = not blockers
                severity_order = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
                severity = max(
                    (item.get("severity", "info") for item in findings if isinstance(item, dict)),
                    key=lambda value: severity_order.get(value, 0),
                    default="info",
                )
                files = report.get("files", [])
            return "\n".join(
                (
                    f"Review status: {'passed' if passed else 'blocked'}",
                    f"Highest severity: {severity}",
                    f"Reviewed files: {len(files) if isinstance(files, list) else 0}",
                    f"Findings: {len(findings) if isinstance(findings, list) else 0}",
                )
            )
    except (WorkflowError, TypeError, ValueError) as exc:
        return f"Workflow error: {exc}"
    return WORKFLOW_HELP


def _recovery_diagnosis_text(diagnosis) -> str:
    value = lambda item: "none" if item is None else item.value if hasattr(item, "value") else str(item)
    lines = [
        "Workflow recovery diagnosis:",
        f"  State: {value(diagnosis.state)}",
        f"  Workflow ID: {value(diagnosis.workflow_id)}",
        f"  Active-state filename: {value(diagnosis.active_state_filename)}",
        f"  Active state valid: {str(diagnosis.active_state_valid).lower()}",
        f"  Recovery available: {str(diagnosis.recoverable).lower()}",
        f"  Checkpoint ID: {value(diagnosis.checkpoint_id)}",
        f"  Checkpoint sequence: {value(diagnosis.checkpoint_sequence)}",
        f"  Checkpoint reason: {value(diagnosis.checkpoint_reason)}",
        f"  Checkpoint status: {value(diagnosis.checkpoint_status)}",
        f"  Explicit confirmation required: {str(diagnosis.requires_confirmation).lower()}",
    ]
    lines.extend(f"  Warning: {warning}" for warning in diagnosis.warnings)
    if diagnosis.recoverable and diagnosis.checkpoint_id:
        lines.append(f"Run /workflow recover {diagnosis.checkpoint_id} CONFIRM")
    elif value(diagnosis.state) == "healthy":
        lines.append("Recovery is not required.")
    elif value(diagnosis.state) in {"multiple_active_states", "multiple_checkpoint_workflows"}:
        lines.append("Automatic selection was refused because the recovery state is ambiguous.")
    return "\n".join(lines)


def _active_checkpoints_text(checkpoints) -> str:
    ordered = sorted(checkpoints, key=lambda item: (item.workflow_id, item.sequence, item.checkpoint_id))
    if not ordered:
        return "No active workflow checkpoints."
    lines = ["Active workflow checkpoints:"]
    current = None
    for checkpoint in ordered:
        if checkpoint.workflow_id != current:
            current = checkpoint.workflow_id
            lines.append(f"Workflow {current}:")
        patch_ids = ", ".join(checkpoint.patch_ids) if checkpoint.patch_ids else "none"
        lines.append(
            f"  {checkpoint.checkpoint_id} | sequence {checkpoint.sequence} | "
            f"reason {checkpoint.reason.value} | status {checkpoint.workflow_status.value} | "
            f"created {checkpoint.created_at} | patch IDs {patch_ids}"
        )
    return "\n".join(lines)


def _recovery_result_text(result) -> str:
    lines = [
        "Workflow state recovery:",
        f"  Workflow ID: {result.workflow_id}",
        f"  Checkpoint ID: {result.checkpoint_id}",
        f"  Restored status: {result.restored_status.value}",
        f"  Active-state filename: {result.active_state_filename}",
        f"  Quarantine filename: {result.quarantine_filename or 'none'}",
        f"  Recovered: {str(result.recovered).lower()}",
        f"  Already recovered: {str(result.already_recovered).lower()}",
        f"  Resume required: {str(result.requires_resume).lower()}",
    ]
    lines.extend(f"  Warning: {warning}" for warning in result.warnings)
    lines.extend([
        "State restoration is complete. Workflow execution has not resumed.",
        f"Run /workflow resume separately after reviewing the restored state (workflow {result.workflow_id}).",
    ])
    return "\n".join(lines)


def _workflow_text(run) -> str:
    if not hasattr(run, "test_results"):
        return "\n".join(
            [
                f"Workflow: {run.workflow_type}",
                f"ID: {run.workflow_id}",
                f"Stage: {run.status.value}",
            ]
        )
    last_verification = run.test_results[-1].passed if run.test_results else None
    lines = [
        f"Workflow: {run.workflow_type}",
        f"ID: {run.workflow_id}",
        f"Stage: {run.status.value}",
        f"Revision: {run.revision}",
        f"Patch iterations: {run.iteration_count}/{run.max_iterations}",
        f"Last verification: {('passed' if last_verification is True else 'failed' if last_verification is False else 'none')}",
        f"Confirmation required: {('none' if run.confirmation is None else run.confirmation.action)}",
        f"Test group: {run.test_group or 'none'}",
        f"Workspace drift: {str(run.workspace_drift).lower()}",
        f"Rollback available: {str(run.rollback_available).lower()}",
        f"Next actions: {', '.join(run.next_actions) or 'none'}",
    ]
    if run.status.value == "waiting_patch":
        lines.append("Attach a pending Patch Tools artifact: /workflow attach-patch <pending_patch_id>")
    if run.review is not None:
        lines.extend(
            [
                f"Review scope: {run.review.scope}",
                f"Review files: {len(run.review.files)}",
                f"Review findings: {len(run.review.findings)}",
                f"Review evidence digest: {run.review.diff_sha256}",
            ]
        )
    if run.error_codes:
        lines.append(f"Safe error codes: {', '.join(run.error_codes)}")
    return "\n".join(lines)


MODE_HELP = """Agent Mode commands:
  /mode                  Show the active mode
  /mode list             List available modes
  /mode set <name>       Activate a mode
  /mode reset            Restore the default mode

Available modes:
  architect
  coder
  reviewer
  debugger
  teacher
  release_manager"""


def _clean_cli_token(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _resolve_tool_executor(
    tool_executor: ToolExecutor | None,
) -> ToolExecutor:
    if tool_executor is None:
        return build_production_tool_executor()

    if not isinstance(tool_executor, ToolExecutor):
        raise TypeError(
            "tool_executor must be a ToolExecutor instance."
        )

    return tool_executor


def handle_file_command(
    command: str,
    tool_executor: ToolExecutor | None = None,
) -> str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"File command error: {exc}"

    if len(parts) == 1:
        return FILE_HELP

    action = _clean_cli_token(parts[1]).lower()
    argument = " ".join(parts[2:]).strip().strip('"')

    if action == "list":
        tool_name = "list_dir"
        arguments = {"path": argument or "."}
    elif action == "read" and argument:
        tool_name = "read_file"
        arguments = {"path": argument}
    elif action == "find" and argument:
        tool_name = "find_file"
        arguments = {"name": argument}
    elif action == "search" and argument:
        tool_name = "search_in_files"
        arguments = {"query": argument}
    elif action in {"summary", "summarize"} and argument:
        tool_name = "summarize_file"
        arguments = {"path": argument}
    else:
        return FILE_HELP

    execution_result = _resolve_tool_executor(
        tool_executor
    ).execute_named(
        tool_name,
        **arguments,
    )

    if not execution_result.ok:
        return f"File command error: {execution_result.error}"

    result = execution_result.data

    if not result["ok"]:
        return f"File command error: {result['error']}"

    return json.dumps(
        result["data"],
        ensure_ascii=False,
        indent=2,
    )


def handle_patch_command(
    command: str,
    mode_session=None,
    tool_executor: ToolExecutor | None = None,
    tool_confirmation_manager: ToolConfirmationManager | None = None,
) -> str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Patch command error: {exc}"

    if len(parts) == 1:
        return PATCH_HELP

    action = _clean_cli_token(parts[1]).lower()

    if (
        action in {"apply", "rollback"}
        and mode_session is not None
        and not mode_session.active_mode.allow_code_changes
    ):
        return (
            "Patch command blocked: "
            f"agent mode '{mode_session.active_mode_name}' "
            "does not allow code changes."
        )

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

        if tool_executor is None:
            result = propose_patch_from_file(
                target_path, proposal_path, reason
            )
        else:
            execution = execute_tool_with_confirmation(
                tool_executor,
                ToolRequest("propose_patch_from_file", {
                    "target_path": target_path,
                    "proposal_path": proposal_path,
                    "reason": reason,
                }),
                tool_confirmation_manager,
            )
            if not execution.ok:
                return f"Patch command error: {execution.error}"
            result = execution.data

    elif action == "apply" and len(parts) in {3, 4}:
        patch_id = _clean_cli_token(parts[2])
        if tool_executor is None:
            confirmed = len(parts) == 4 and _clean_cli_token(parts[3]) == "CONFIRM"
            result = apply_patch(patch_id, confirmed=confirmed)
        elif len(parts) != 3:
            return PATCH_HELP
        else:
            execution = execute_tool_with_confirmation(
                tool_executor,
                ToolRequest("apply_patch", {
                    "patch_id": patch_id,
                    "confirmed": True,
                }),
                tool_confirmation_manager,
            )
            if not execution.ok:
                return f"Patch command error: {execution.error}"
            result = execution.data

    elif action == "rollback" and len(parts) in {3, 4}:
        patch_id = _clean_cli_token(parts[2])

        if tool_executor is None:
            confirmed = len(parts) == 4 and _clean_cli_token(parts[3]) == "CONFIRM"
            result = rollback_patch(patch_id, confirmed=confirmed)
        elif len(parts) != 3:
            return PATCH_HELP
        else:
            execution = execute_tool_with_confirmation(
                tool_executor,
                ToolRequest("rollback_patch", {
                    "patch_id": patch_id,
                    "confirmed": True,
                }),
                tool_confirmation_manager,
            )
            if not execution.ok:
                return f"Patch command error: {execution.error}"
            result = execution.data

    else:
        return PATCH_HELP

    if not result["ok"]:
        return f"Patch command error: {result['error']}"

    return json.dumps(
        result["data"],
        ensure_ascii=False,
        indent=2,
    )


def handle_git_command(
    command: str,
    project_root=None,
    tool_executor: ToolExecutor | None = None,
) -> str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Git command error: {exc}"

    if len(parts) == 1:
        return GIT_HELP

    action = _clean_cli_token(parts[1]).lower()
    workspace = "." if project_root is None else project_root

    if action == "status" and len(parts) == 2:
        tool_name = "git_status"
        arguments = {"workspace": workspace}

    elif action == "diff" and len(parts) == 2:
        tool_name = "git_diff"
        arguments = {"workspace": workspace}

    elif (
        action == "diff"
        and len(parts) == 3
        and _clean_cli_token(parts[2]).lower() == "--cached"
    ):
        tool_name = "git_diff_cached"
        arguments = {"workspace": workspace}

    elif action == "log" and len(parts) in {2, 3}:
        if len(parts) == 2:
            limit = 10
        else:
            try:
                limit = int(_clean_cli_token(parts[2]))
            except ValueError:
                return "Git command error: log limit must be an integer from 1 to 100."

        tool_name = "git_log"
        arguments = {
            "workspace": workspace,
            "limit": limit,
        }

    elif action == "branch" and len(parts) == 2:
        tool_name = "git_branch"
        arguments = {"workspace": workspace}

    else:
        return GIT_HELP

    execution_result = _resolve_tool_executor(
        tool_executor
    ).execute_named(
        tool_name,
        **arguments,
    )

    if not execution_result.ok:
        return f"Git command error: {execution_result.error}"

    result = execution_result.data

    if not result.ok:
        error = result.stderr.strip() or "Git command failed."
        return f"Git command error: {error}"

    if not result.stdout.strip():
        empty_messages = {
            "git_status": "Git working tree is clean.",
            "git_diff": "No unstaged changes.",
            "git_diff_cached": "No staged changes.",
            "git_branch": "Git repository is in detached HEAD state.",
        }
        if tool_name in empty_messages:
            return empty_messages[tool_name]

    return result.stdout.rstrip()

def handle_memory_command(command: str, project_root=None, tool_executor: ToolExecutor | None = None, tool_confirmation_manager: ToolConfirmationManager | None = None) -> str:
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
        arguments = {"kind": parts[2], "text": " ".join(parts[3:]), "project_root": project_root}
        if tool_executor is None:
            result = add_memory(**arguments)
        else:
            execution = execute_tool_with_confirmation(tool_executor, ToolRequest("memory_add", arguments), tool_confirmation_manager)
            if not execution.ok:
                return f"Memory command error: {execution.error}"
            result = execution.data
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


def handle_terminal_command(
    command: str,
    project_root=None,
    tool_executor: ToolExecutor | None = None,
    tool_confirmation_manager: ToolConfirmationManager | None = None,
) -> str:
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

    if tool_executor is None:
        result = run_allowed_command(command_id, project_root)
    else:
        execution_result = execute_tool_with_confirmation(
            tool_executor,
            ToolRequest(
                "terminal_run",
                {
                    "command_id": command_id,
                    "project_root": project_root,
                },
            ),
            tool_confirmation_manager,
        )
        if not execution_result.ok:
            return f"Terminal command error: {execution_result.error}"
        result = execution_result.data
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


def handle_test_command(command: str, project_root=None, tool_executor: ToolExecutor | None = None, tool_confirmation_manager: ToolConfirmationManager | None = None) -> str:
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

    if tool_executor is None:
        result = run_test_group(group_id, project_root)
    else:
        execution = execute_tool_with_confirmation(tool_executor, ToolRequest("test_run", {"group_id": group_id, "project_root": project_root}), tool_confirmation_manager)
        if not execution.ok:
            return f"Test command error: {execution.error}"
        result = execution.data

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


def handle_internet_command(command: str, tool_executor: ToolExecutor | None = None, tool_confirmation_manager: ToolConfirmationManager | None = None) -> str:
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
        if tool_executor is None:
            set_internet_enabled(True)
        else:
            execution = execute_tool_with_confirmation(tool_executor, ToolRequest("internet_set", {"enabled": True}), tool_confirmation_manager)
            if not execution.ok:
                return f"Internet command error: {execution.error}"
        return (
            "Internet access enabled for this "
            "VEGA process."
        )

    if action == "off":
        if tool_executor is None:
            set_internet_enabled(False)
        else:
            execution = execute_tool_with_confirmation(tool_executor, ToolRequest("internet_set", {"enabled": False}), tool_confirmation_manager)
            if not execution.ok:
                return f"Internet command error: {execution.error}"
        return (
            "Internet access disabled for this "
            "VEGA process."
        )

    return INTERNET_HELP


def handle_web_command(
    command: str,
    project_root=None,
    tool_executor: ToolExecutor | None = None,
    tool_confirmation_manager: ToolConfirmationManager | None = None,
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

    arguments = {"url": parts[2], "project_root": project_root}
    if tool_executor is None:
        result = fetch_url(parts[2], project_root)
    else:
        execution = execute_tool_with_confirmation(tool_executor, ToolRequest("web_fetch", arguments), tool_confirmation_manager)
        if not execution.ok:
            return f"Web command error: {execution.error}"
        result = execution.data

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
    tool_executor: ToolExecutor | None = None,
    tool_confirmation_manager: ToolConfirmationManager | None = None,
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
        if tool_executor is None:
            result = build_documentation(project_root)
        else:
            execution = execute_tool_with_confirmation(tool_executor, ToolRequest("documentation_build", {"project_root": project_root}), tool_confirmation_manager)
            if not execution.ok:
                return f"Documentation command error: {execution.error}"
            result = execution.data

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



def handle_release_command(
    command: str,
    project_root=None,
    tool_executor: ToolExecutor | None = None,
    tool_confirmation_manager: ToolConfirmationManager | None = None,
) -> str:
    """Handle read-only Release Manager commands."""

    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Release command error: {exc}"

    parts = [_clean_cli_token(part) for part in parts]

    if len(parts) == 1:
        return RELEASE_HELP

    action = parts[1].lower()

    if action == "status" and len(parts) == 2:
        result = get_release_status(project_root)

        if not result["ok"]:
            return f"Release command error: {result['error']}"

        data = result["data"]
        lines = [
            "Release status",
            f"Version: {data['version']}",
            f"Version valid: {'YES' if data['version_valid'] else 'NO'}",
            f"Branch: {data['branch']}",
            f"Branch allowed: {'YES' if data['branch_allowed'] else 'NO'}",
            f"Publish branch: {data['publish_branch']}",
            (
                "Publish branch match: "
                f"{'YES' if data['publish_branch_match'] else 'NO'}"
            ),
            f"Git clean: {'YES' if data['git_clean'] else 'NO'}",
            (
                "Documentation: "
                f"{'PASS' if data['documentation_passed'] else 'FAIL'}"
            ),
            (
                "Preparation ready: "
                f"{'YES' if data['preparation_ready'] else 'NO'}"
            ),
            (
                "Publish ready: "
                f"{'YES' if data['publish_ready'] else 'NO'}"
            ),
        ]

        if data["missing_files"]:
            lines.extend(["", "Missing files:"])
            for item in data["missing_files"]:
                lines.append(f"  - {item}")

        if data["issues"]:
            lines.extend(["", "Issues:"])
            for issue in data["issues"]:
                lines.append(f"  - {issue}")

        return "\n".join(lines)

    if action == "check" and len(parts) == 2:
        if tool_executor is None:
            result = run_release_check(project_root)
        else:
            execution = execute_tool_with_confirmation(tool_executor, ToolRequest("release_check", {"project_root": project_root}), tool_confirmation_manager)
            if not execution.ok:
                return f"Release command error: {execution.error}"
            result = execution.data

        if not result["ok"]:
            return f"Release command error: {result['error']}"

        data = result["data"]
        status = data["status"]

        lines = [
            "Release check",
            f"Version: {status['version']}",
            f"Branch: {status['branch']}",
            f"Commands passed: {'YES' if data['commands_passed'] else 'NO'}",
            f"Release check: {'PASS' if data['passed'] else 'FAIL'}",
            f"Publish ready: {'YES' if data['publish_ready'] else 'NO'}",
            "",
            "Validation commands:",
        ]

        for item in data["commands"]:
            lines.append(
                "  "
                f"[{'PASS' if item['passed'] else 'FAIL'}] "
                f"{item['command_id']} "
                f"(returncode={item['returncode']}, "
                f"duration_ms={item['duration_ms']})"
            )

            if item["error"]:
                lines.append(f"    Error: {item['error']}")

        if status["issues"]:
            lines.extend(["", "Status issues:"])
            for issue in status["issues"]:
                lines.append(f"  - {issue}")

        return "\n".join(lines)

    if action == "notes" and len(parts) == 2:
        result = build_release_notes(project_root)

        if not result["ok"]:
            return f"Release command error: {result['error']}"

        data = result["data"]

        return "\n".join(
            [
                "Release notes draft",
                f"Version: {data['version']}",
                f"Source: {data['source']}",
                f"Suggested path: {data['suggested_path']}",
                "Written: NO",
                "",
                data["draft"],
            ]
        )

    return RELEASE_HELP


def handle_mode_command(command: str, mode_session) -> str:
    """Handle process-local VEGA agent mode commands."""

    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Mode command error: {exc}"

    parts = [
        _clean_cli_token(part)
        for part in parts
    ]

    if len(parts) == 1:
        mode = mode_session.active_mode
        return "\n".join(
            [
                f"Active mode: {mode.name}",
                f"Description: {mode.description}",
                (
                    "Code changes: "
                    f"{'allowed' if mode.allow_code_changes else 'blocked'}"
                ),
                (
                    "Review required: "
                    f"{'yes' if mode.review_required else 'no'}"
                ),
            ]
        )

    action = parts[1].lower()

    if action == "list" and len(parts) == 2:
        lines = ["Available agent modes:"]

        for mode in mode_session.registry.list_modes():
            marker = "*" if mode.name == mode_session.active_mode_name else " "
            lines.append(
                f" {marker} {mode.name:<18} {mode.description}"
            )

        return "\n".join(lines)

    if action == "reset" and len(parts) == 2:
        mode = mode_session.reset()
        return f"Agent mode reset to: {mode.name}"

    if action == "set" and len(parts) == 3:
        requested_mode = parts[2].lower()

        try:
            mode = mode_session.set_mode(requested_mode)
        except KeyError as exc:
            return f"Mode command error: {exc.args[0]}"

        return "\n".join(
            [
                f"Agent mode activated: {mode.name}",
                f"Description: {mode.description}",
            ]
        )

    return MODE_HELP


def tools_list_text(
    tool_executor: ToolExecutor | None = None,
) -> str:
    executor = _resolve_tool_executor(tool_executor)
    return "Available tools:\n" + "\n".join(
        f"  {name}"
        for name in executor.registered_tools()
    )
