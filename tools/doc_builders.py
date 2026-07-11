"""Safe documentation generation and patch proposal tools for VEGA."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from core.safety import get_project_root
from tools.doc_tools import (
    get_documentation_status,
    load_documentation_policy,
)
from tools.patch_tools import (
    list_patches,
    propose_patch,
)


GENERATED_START_TEMPLATE = (
    "<!-- VEGA DOCGEN START: {document_id} -->"
)
GENERATED_END_TEMPLATE = (
    "<!-- VEGA DOCGEN END: {document_id} -->"
)

BLOCKED_INVENTORY_DIRECTORIES = frozenset(
    {
        ".git",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)


class DocumentationBuildError(ValueError):
    """Controlled Documentation Builder error."""


def _result(
    data: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": error is None,
        "error": error,
        "data": data if error is None else None,
    }


def _resolve_active_root(
    project_root: Path | str | None,
) -> Path:
    active_root = get_project_root().resolve()

    if project_root is None:
        return active_root

    requested_root = Path(project_root).resolve()

    if requested_root != active_root:
        raise DocumentationBuildError(
            "Documentation build is allowed only for the "
            "active VEGA project root."
        )

    return requested_root


def _read_utf8_document(
    path: Path,
    *,
    max_chars: int,
) -> str:
    if not path.is_file():
        raise DocumentationBuildError(
            f"Managed documentation file is missing: {path.name}"
        )

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentationBuildError(
            f"Managed documentation is not valid UTF-8: {path.name}"
        ) from exc
    except OSError as exc:
        raise DocumentationBuildError(
            f"Managed documentation could not be read: {path.name}"
        ) from exc

    if len(text) > max_chars:
        raise DocumentationBuildError(
            f"Managed documentation exceeds the configured "
            f"limit: {path.name}"
        )

    return text


def _generated_markers(
    document_id: str,
) -> tuple[str, str]:
    return (
        GENERATED_START_TEMPLATE.format(
            document_id=document_id
        ),
        GENERATED_END_TEMPLATE.format(
            document_id=document_id
        ),
    )


def _merge_generated_block(
    existing_text: str,
    document_id: str,
    generated_body: str,
) -> str:
    start_marker, end_marker = _generated_markers(
        document_id
    )

    start_count = existing_text.count(start_marker)
    end_count = existing_text.count(end_marker)

    generated_block = (
        f"{start_marker}\n"
        f"{generated_body.rstrip()}\n"
        f"{end_marker}"
    )

    if start_count == 0 and end_count == 0:
        base = existing_text.rstrip()

        if base:
            return f"{base}\n\n{generated_block}\n"

        return f"{generated_block}\n"

    if start_count != 1 or end_count != 1:
        raise DocumentationBuildError(
            f"Invalid generated block markers in "
            f"document: {document_id}"
        )

    start_index = existing_text.index(start_marker)
    end_index = existing_text.index(end_marker)

    if end_index < start_index:
        raise DocumentationBuildError(
            f"Generated block markers are out of order "
            f"in document: {document_id}"
        )

    end_index += len(end_marker)

    prefix = existing_text[:start_index].rstrip()
    suffix = existing_text[end_index:].strip()

    parts = []

    if prefix:
        parts.append(prefix)

    parts.append(generated_block)

    if suffix:
        parts.append(suffix)

    return "\n\n".join(parts).rstrip() + "\n"


def _list_python_modules(
    directory: Path,
) -> list[str]:
    if not directory.is_dir():
        return []

    return sorted(
        path.name
        for path in directory.glob("*.py")
        if path.is_file()
        and path.name != "__init__.py"
    )


def _list_top_level_directories(
    root: Path,
) -> list[str]:
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir()
        and path.name not in BLOCKED_INVENTORY_DIRECTORIES
        and not path.name.startswith(".")
    )


def _extract_function_source(
    source: str,
    function_name: str,
) -> str:
    pattern = re.compile(
        rf"^def {re.escape(function_name)}\("
        rf".*?(?=^def |\Z)",
        re.MULTILINE | re.DOTALL,
    )

    match = pattern.search(source)

    if match is None:
        return ""

    return match.group(0)


def _discover_cli_commands(
    root: Path,
) -> tuple[list[str], list[str]]:
    cli_path = root / "scripts" / "vega.py"

    if not cli_path.is_file():
        return [], []

    try:
        source = cli_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], []

    available_source = _extract_function_source(
        source,
        "print_available_commands",
    )
    help_source = _extract_function_source(
        source,
        "help_text",
    )

    available_entries: list[str] = []

    for match in re.finditer(
        r'print\("(/[^"]+)"\)',
        available_source,
    ):
        entry = match.group(1).strip()

        if entry not in available_entries:
            available_entries.append(entry)

    help_entries: list[str] = []

    for line in help_source.splitlines():
        candidate = line.strip().rstrip(",")

        if not (
            candidate.startswith('"')
            and candidate.endswith('"')
        ):
            continue

        try:
            value = ast.literal_eval(candidate)
        except (SyntaxError, ValueError):
            continue

        if (
            isinstance(value, str)
            and value.lstrip().startswith("/")
        ):
            normalized = value.strip()

            if normalized not in help_entries:
                help_entries.append(normalized)

    command_roots: list[str] = []

    for entry in available_entries + help_entries:
        for match in re.finditer(
            r"(?<!\S)(/[A-Za-z0-9_-]+)",
            entry,
        ):
            root_command = match.group(1)

            if root_command not in command_roots:
                command_roots.append(root_command)

    return command_roots, help_entries


def _render_architecture_block(
    root: Path,
    version: str,
) -> str:
    top_level = _list_top_level_directories(root)
    core_modules = _list_python_modules(root / "core")
    tool_modules = _list_python_modules(root / "tools")

    lines = [
        "## Generated project snapshot",
        "",
        f"Project version: `{version}`",
        "",
        "This section is generated from the current project tree.",
        "",
        "### Top-level directories",
        "",
    ]

    if top_level:
        lines.extend(
            f"- `{name}/`"
            for name in top_level
        )
    else:
        lines.append("- No project directories detected.")

    lines.extend(
        [
            "",
            "### Core modules",
            "",
        ]
    )

    if core_modules:
        lines.extend(
            f"- `core/{name}`"
            for name in core_modules
        )
    else:
        lines.append("- No core modules detected.")

    lines.extend(
        [
            "",
            "### Tool modules",
            "",
        ]
    )

    if tool_modules:
        lines.extend(
            f"- `tools/{name}`"
            for name in tool_modules
        )
    else:
        lines.append("- No tool modules detected.")

    lines.extend(
        [
            "",
            "### Dependency direction",
            "",
            "```text",
            "scripts -> core -> tools -> policies and project data",
            "```",
            "",
            "Generated documentation changes are proposed through "
            "Patch Tools and are not applied automatically.",
        ]
    )

    return "\n".join(lines)


def _render_commands_block(
    root: Path,
    version: str,
) -> str:
    command_roots, help_entries = _discover_cli_commands(
        root
    )

    lines = [
        "## Generated command reference",
        "",
        f"Project version: `{version}`",
        "",
        "This section is generated from `scripts/vega.py`.",
        "",
        "### Available command roots",
        "",
        "```text",
    ]

    if command_roots:
        lines.extend(command_roots)
    else:
        lines.append("No commands detected.")

    lines.extend(
        [
            "```",
            "",
            "### CLI help entries",
            "",
            "```text",
        ]
    )

    if help_entries:
        lines.extend(help_entries)
    else:
        lines.append("No help entries detected.")

    lines.append("```")

    return "\n".join(lines)


def _render_security_block(
    version: str,
    policy: dict[str, Any],
) -> str:
    build_policy = policy["build_policy"]
    limits = policy["limits"]

    lines = [
        "## Generated security snapshot",
        "",
        f"Project version: `{version}`",
        "",
        "### Documentation Builder policy",
        "",
        (
            "- Create missing files automatically: "
            f"`{str(build_policy['create_missing_files']).lower()}`"
        ),
        (
            "- Use Patch Tools: "
            f"`{str(build_policy['use_patch_tools']).lower()}`"
        ),
        (
            "- Apply patches automatically: "
            f"`{str(build_policy['apply_automatically']).lower()}`"
        ),
        (
            "- Require confirmation token: "
            f"`{str(build_policy['require_confirm_token']).lower()}`"
        ),
        "",
        "### Limits",
        "",
        (
            "- Maximum document characters: "
            f"`{limits['max_document_chars']}`"
        ),
        (
            "- Maximum generated documents: "
            f"`{limits['max_generated_documents']}`"
        ),
        "",
        "### Active policy files",
        "",
        "- `config/allowed_commands.json`",
        "- `config/internet_policy.json`",
        "- `config/documentation_policy.json`",
        "",
        "### Enforcement principles",
        "",
        "1. Documentation targets must remain inside the project root.",
        "2. Missing managed files are not created automatically.",
        "3. Generated changes become pending patches.",
        "4. Pending patches are never applied by `/docgen build`.",
        "5. Patch application requires a separate explicit command.",
    ]

    return "\n".join(lines)


def _render_generated_body(
    generator: str,
    root: Path,
    version: str,
    policy: dict[str, Any],
) -> str:
    if generator == "architecture":
        return _render_architecture_block(
            root,
            version,
        )

    if generator == "commands":
        return _render_commands_block(
            root,
            version,
        )

    if generator == "security":
        return _render_security_block(
            version,
            policy,
        )

    raise DocumentationBuildError(
        f"Unknown documentation generator: {generator}"
    )


def build_documentation(
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Create pending patches for managed documentation."""

    try:
        root = _resolve_active_root(project_root)

        policy_result = load_documentation_policy(root)

        if not policy_result["ok"]:
            raise DocumentationBuildError(
                policy_result["error"]
            )

        status_result = get_documentation_status(root)

        if not status_result["ok"]:
            raise DocumentationBuildError(
                status_result["error"]
            )

        policy = policy_result["data"]["policy"]
        status = status_result["data"]
        version = status["version"]
        max_chars = policy["limits"]["max_document_chars"]

        pending_result = list_patches("pending")

        if not pending_result["ok"]:
            raise DocumentationBuildError(
                pending_result["error"]
            )

        pending_targets = {
            item["target_path"]
            for item in pending_result["data"]
            if item.get("target_path")
        }

        documents_by_id = {
            document["id"]: document
            for document in status["documents"]
        }

        prepared = []
        skipped = []
        errors = []

        for definition in policy["managed_documents"]:
            document_id = definition["id"]
            relative_path = definition["path"]
            generator = definition["generator"]
            status_item = documents_by_id[document_id]

            if not status_item["exists"]:
                errors.append(
                    {
                        "document_id": document_id,
                        "path": relative_path,
                        "message": (
                            "Managed documentation file is missing."
                        ),
                    }
                )
                continue

            target_path = root / relative_path

            try:
                existing_text = _read_utf8_document(
                    target_path,
                    max_chars=max_chars,
                )

                generated_body = _render_generated_body(
                    generator,
                    root,
                    version,
                    policy,
                )

                proposed_text = _merge_generated_block(
                    existing_text,
                    document_id,
                    generated_body,
                )
            except DocumentationBuildError as exc:
                errors.append(
                    {
                        "document_id": document_id,
                        "path": relative_path,
                        "message": str(exc),
                    }
                )
                continue

            if len(proposed_text) > max_chars:
                errors.append(
                    {
                        "document_id": document_id,
                        "path": relative_path,
                        "message": (
                            "Generated document exceeds the "
                            "configured character limit."
                        ),
                    }
                )
                continue

            if proposed_text == existing_text:
                skipped.append(
                    {
                        "document_id": document_id,
                        "path": relative_path,
                        "reason": "up_to_date",
                    }
                )
                continue

            if relative_path in pending_targets:
                skipped.append(
                    {
                        "document_id": document_id,
                        "path": relative_path,
                        "reason": "pending_patch_exists",
                    }
                )
                continue

            prepared.append(
                {
                    "document_id": document_id,
                    "path": relative_path,
                    "generator": generator,
                    "content": proposed_text,
                }
            )

        created = []

        if not errors:
            for item in prepared:
                patch_result = propose_patch(
                    target_path=item["path"],
                    new_content=item["content"],
                    reason=(
                        "Documentation Builder update for "
                        f"{item['document_id']}"
                    ),
                )

                if not patch_result["ok"]:
                    errors.append(
                        {
                            "document_id": item["document_id"],
                            "path": item["path"],
                            "message": patch_result["error"],
                        }
                    )
                    continue

                created.append(
                    {
                        "document_id": item["document_id"],
                        "path": item["path"],
                        "patch_id": (
                            patch_result["data"]["patch_id"]
                        ),
                        "status": "pending",
                    }
                )

        return _result(
            {
                "passed": not errors,
                "version": version,
                "created_count": len(created),
                "skipped_count": len(skipped),
                "error_count": len(errors),
                "created": created,
                "skipped": skipped,
                "errors": errors,
                "applied_automatically": False,
            }
        )

    except (
        DocumentationBuildError,
        OSError,
        ValueError,
    ) as exc:
        return _result(error=str(exc))
