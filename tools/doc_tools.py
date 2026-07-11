"""Safe project documentation inspection tools for VEGA."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.safety import get_project_root


POLICY_RELATIVE_PATH = Path("config/documentation_policy.json")
VERSION_PATTERN = re.compile(
    r'^\s*VERSION\s*=\s*["\']([^"\']+)["\']\s*$',
    re.MULTILINE,
)
DOCUMENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")

BLOCKED_PATH_PARTS = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".venv",
        "venv",
        "node_modules",
    }
)


class DocumentationPolicyError(ValueError):
    """User-facing Documentation Builder policy error."""


def _result(
    data: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": error is None,
        "error": error,
        "data": data if error is None else None,
    }


def _resolve_root(
    project_root: Path | str | None = None,
) -> Path:
    if project_root is None:
        return get_project_root().resolve()

    return Path(project_root).resolve()


def _resolve_policy_path(
    root: Path,
    raw_path: str,
) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise DocumentationPolicyError(
            "Documentation path must be a non-empty string."
        )

    relative = Path(raw_path.strip())

    if relative.is_absolute():
        raise DocumentationPolicyError(
            f"Absolute documentation paths are not allowed: {raw_path}"
        )

    if ".." in relative.parts:
        raise DocumentationPolicyError(
            f"Parent-directory traversal is not allowed: {raw_path}"
        )

    if any(
        part.lower() in BLOCKED_PATH_PARTS
        for part in relative.parts
    ):
        raise DocumentationPolicyError(
            f"Blocked directory in documentation path: {raw_path}"
        )

    resolved = (root / relative).resolve(strict=False)

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DocumentationPolicyError(
            f"Documentation path escapes the project root: {raw_path}"
        ) from exc

    return relative.as_posix(), resolved


def _require_boolean(
    value: Any,
    field_name: str,
) -> bool:
    if not isinstance(value, bool):
        raise DocumentationPolicyError(
            f"{field_name} must be true or false."
        )

    return value


def _require_positive_integer(
    value: Any,
    field_name: str,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
    ):
        raise DocumentationPolicyError(
            f"{field_name} must be a positive integer."
        )

    return value


def _normalize_document(
    root: Path,
    item: Any,
    *,
    kind: str,
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise DocumentationPolicyError(
            f"Every {kind} document entry must be an object."
        )

    document_id = item.get("id")

    if (
        not isinstance(document_id, str)
        or not DOCUMENT_ID_PATTERN.fullmatch(document_id)
    ):
        raise DocumentationPolicyError(
            f"Invalid documentation id: {document_id!r}"
        )

    relative_path, _ = _resolve_policy_path(
        root,
        item.get("path", ""),
    )

    required = _require_boolean(
        item.get("required"),
        f"{document_id}.required",
    )

    normalized: dict[str, Any] = {
        "id": document_id,
        "path": relative_path,
        "kind": kind,
        "required": required,
    }

    if kind == "managed":
        generator = item.get("generator")

        if (
            not isinstance(generator, str)
            or not DOCUMENT_ID_PATTERN.fullmatch(generator)
        ):
            raise DocumentationPolicyError(
                f"Invalid generator for document: {document_id}"
            )

        normalized["generator"] = generator
        normalized["check_version"] = False
    else:
        normalized["generator"] = None
        normalized["check_version"] = _require_boolean(
            item.get("check_version"),
            f"{document_id}.check_version",
        )

    return normalized


def _validate_policy(
    root: Path,
    policy: Any,
) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise DocumentationPolicyError(
            "Documentation policy must be a JSON object."
        )

    if policy.get("schema_version") != 1:
        raise DocumentationPolicyError(
            "Unsupported documentation policy schema version."
        )

    managed_raw = policy.get("managed_documents")
    manual_raw = policy.get("manual_documents")
    build_policy = policy.get("build_policy")
    limits = policy.get("limits")

    if not isinstance(managed_raw, list):
        raise DocumentationPolicyError(
            "managed_documents must be a list."
        )

    if not isinstance(manual_raw, list):
        raise DocumentationPolicyError(
            "manual_documents must be a list."
        )

    if not isinstance(build_policy, dict):
        raise DocumentationPolicyError(
            "build_policy must be an object."
        )

    if not isinstance(limits, dict):
        raise DocumentationPolicyError(
            "limits must be an object."
        )

    normalized_managed = [
        _normalize_document(root, item, kind="managed")
        for item in managed_raw
    ]
    normalized_manual = [
        _normalize_document(root, item, kind="manual")
        for item in manual_raw
    ]

    all_documents = normalized_managed + normalized_manual
    ids = [item["id"] for item in all_documents]
    paths = [item["path"].lower() for item in all_documents]

    if len(ids) != len(set(ids)):
        raise DocumentationPolicyError(
            "Documentation ids must be unique."
        )

    if len(paths) != len(set(paths)):
        raise DocumentationPolicyError(
            "Documentation paths must be unique."
        )

    normalized_build_policy = {
        "create_missing_files": _require_boolean(
            build_policy.get("create_missing_files"),
            "build_policy.create_missing_files",
        ),
        "use_patch_tools": _require_boolean(
            build_policy.get("use_patch_tools"),
            "build_policy.use_patch_tools",
        ),
        "apply_automatically": _require_boolean(
            build_policy.get("apply_automatically"),
            "build_policy.apply_automatically",
        ),
        "require_confirm_token": _require_boolean(
            build_policy.get("require_confirm_token"),
            "build_policy.require_confirm_token",
        ),
    }

    if normalized_build_policy["create_missing_files"]:
        raise DocumentationPolicyError(
            "Documentation Builder cannot create missing files automatically."
        )

    if not normalized_build_policy["use_patch_tools"]:
        raise DocumentationPolicyError(
            "Documentation Builder must use Patch Tools."
        )

    if normalized_build_policy["apply_automatically"]:
        raise DocumentationPolicyError(
            "Automatic documentation patch application is forbidden."
        )

    if not normalized_build_policy["require_confirm_token"]:
        raise DocumentationPolicyError(
            "Documentation changes must require confirmation."
        )

    normalized_limits = {
        "max_document_chars": _require_positive_integer(
            limits.get("max_document_chars"),
            "limits.max_document_chars",
        ),
        "max_generated_documents": _require_positive_integer(
            limits.get("max_generated_documents"),
            "limits.max_generated_documents",
        ),
    }

    if (
        len(normalized_managed)
        > normalized_limits["max_generated_documents"]
    ):
        raise DocumentationPolicyError(
            "Managed document count exceeds the configured limit."
        )

    return {
        "schema_version": 1,
        "managed_documents": normalized_managed,
        "manual_documents": normalized_manual,
        "build_policy": normalized_build_policy,
        "limits": normalized_limits,
    }


def _load_policy(root: Path) -> dict[str, Any]:
    policy_path = root / POLICY_RELATIVE_PATH

    if not policy_path.is_file():
        raise DocumentationPolicyError(
            "Documentation policy does not exist: "
            f"{POLICY_RELATIVE_PATH.as_posix()}"
        )

    try:
        raw_text = policy_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DocumentationPolicyError(
            "Documentation policy could not be read."
        ) from exc

    try:
        raw_policy = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise DocumentationPolicyError(
            f"Documentation policy contains invalid JSON: {exc}"
        ) from exc

    return _validate_policy(root, raw_policy)


def _read_project_version(root: Path) -> str:
    version_path = root / "scripts" / "version.py"

    if not version_path.is_file():
        raise DocumentationPolicyError(
            "Version file does not exist: scripts/version.py"
        )

    try:
        content = version_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DocumentationPolicyError(
            "Version file could not be read."
        ) from exc

    match = VERSION_PATTERN.search(content)

    if match is None:
        raise DocumentationPolicyError(
            "VERSION could not be found in scripts/version.py."
        )

    return match.group(1)


def load_documentation_policy(
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Load and validate the Documentation Builder policy."""

    try:
        root = _resolve_root(project_root)
        policy = _load_policy(root)

        return _result(
            {
                "path": POLICY_RELATIVE_PATH.as_posix(),
                "policy": policy,
            }
        )
    except (
        DocumentationPolicyError,
        OSError,
        ValueError,
    ) as exc:
        return _result(error=str(exc))


def get_documentation_status(
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Return configured project documentation status."""

    try:
        root = _resolve_root(project_root)
        policy = _load_policy(root)
        version = _read_project_version(root)

        documents: list[dict[str, Any]] = []

        configured_documents = (
            policy["managed_documents"]
            + policy["manual_documents"]
        )

        for definition in configured_documents:
            relative_path, resolved_path = _resolve_policy_path(
                root,
                definition["path"],
            )

            exists = resolved_path.is_file()
            size_bytes = resolved_path.stat().st_size if exists else 0
            version_current: bool | None = None

            if exists and definition["check_version"]:
                try:
                    text = resolved_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    version_current = False
                else:
                    version_current = version in text

            documents.append(
                {
                    **definition,
                    "path": relative_path,
                    "exists": exists,
                    "size_bytes": size_bytes,
                    "version_current": version_current,
                }
            )

        return _result(
            {
                "policy_path": POLICY_RELATIVE_PATH.as_posix(),
                "version": version,
                "documents": documents,
                "managed_count": len(
                    policy["managed_documents"]
                ),
                "manual_count": len(
                    policy["manual_documents"]
                ),
            }
        )
    except (
        DocumentationPolicyError,
        OSError,
        ValueError,
    ) as exc:
        return _result(error=str(exc))


def check_documentation(
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Check required files and version references."""

    status_result = get_documentation_status(project_root)

    if not status_result["ok"]:
        return status_result

    data = status_result["data"]
    issues: list[dict[str, str]] = []

    for document in data["documents"]:
        if document["required"] and not document["exists"]:
            issues.append(
                {
                    "severity": "error",
                    "document_id": document["id"],
                    "path": document["path"],
                    "message": "Required documentation file is missing.",
                }
            )
            continue

        if (
            document["exists"]
            and document["check_version"]
            and document["version_current"] is False
        ):
            issues.append(
                {
                    "severity": "error",
                    "document_id": document["id"],
                    "path": document["path"],
                    "message": (
                        "Document does not reference the current "
                        f"version {data['version']}."
                    ),
                }
            )

    error_count = sum(
        1
        for issue in issues
        if issue["severity"] == "error"
    )

    return _result(
        {
            **data,
            "passed": error_count == 0,
            "error_count": error_count,
            "issues": issues,
        }
    )