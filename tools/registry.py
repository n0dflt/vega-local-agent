"""Registry of built-in tools and safe construction of combined registries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from permissions.models import PermissionValidationError, validate_tool_name

from core.internet_state import (
    is_internet_enabled,
    set_internet_enabled,
)
from memory.project_memory import (
    add_memory,
    get_memory_stats,
    list_memories,
    search_memories,
)
from tools.doc_builders import build_documentation
from tools.doc_tools import (
    check_documentation,
    get_documentation_status,
    load_documentation_policy,
)
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
    propose_patch,
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
from tools.terminal_tools import (
    list_allowed_commands,
    run_allowed_command,
)
from tools.test_tools import (
    list_test_groups,
    run_test_group,
)
from tools.web_tools import fetch_url


_BUILTIN_TOOL_REGISTRY = {
    # Safe File Tools
    "list_dir": list_dir,
    "read_file": read_file,
    "find_file": find_file,
    "search_in_files": search_in_files,
    "summarize_file": summarize_file,

    # Confirmed Patch Tools
    "propose_patch": propose_patch,
    "propose_patch_from_file": propose_patch_from_file,
    "list_patches": list_patches,
    "show_patch": show_patch,
    "apply_patch": apply_patch,
    "rollback_patch": rollback_patch,

    # Safe Git Tools
    "git_status": git_status,
    "git_diff": git_diff,
    "git_diff_cached": git_diff_cached,
    "git_log": git_log,
    "git_branch": git_branch,

    # Project Memory
    "memory_add": add_memory,
    "memory_list": list_memories,
    "memory_search": search_memories,
    "memory_stats": get_memory_stats,

    # Safe Terminal Tools
    "terminal_list": list_allowed_commands,
    "terminal_run": run_allowed_command,

    # Safe Test Runner
    "test_list": list_test_groups,
    "test_run": run_test_group,

    # Controlled Internet Layer
    "internet_status": is_internet_enabled,
    "internet_set": set_internet_enabled,
    "web_fetch": fetch_url,

    # Documentation Builder
    "documentation_build": build_documentation,
    "documentation_policy_load": load_documentation_policy,
    "documentation_status": get_documentation_status,
    "documentation_check": check_documentation,

    # Release Manager
    "release_policy_load": load_release_policy,
    "release_status": get_release_status,
    "release_check": run_release_check,
    "release_notes": build_release_notes,
}

BUILTIN_TOOL_REGISTRY = MappingProxyType(_BUILTIN_TOOL_REGISTRY)

# Compatibility registry used by all existing v2.7 imports. Plugin bootstrap
# never mutates this object.
TOOL_REGISTRY = dict(_BUILTIN_TOOL_REGISTRY)


def build_tool_registry(
    plugin_tools: Mapping[str, Callable[..., Any]] | None = None,
) -> dict[str, Callable[..., Any]]:
    """Return a new built-in-plus-plugin mapping without mutating globals."""

    combined = dict(_BUILTIN_TOOL_REGISTRY)
    if plugin_tools is None:
        return combined
    if not isinstance(plugin_tools, Mapping):
        raise TypeError("plugin_tools must implement the Mapping interface")
    for name, handler in plugin_tools.items():
        try:
            normalized_name = validate_tool_name(name)
        except PermissionValidationError as exc:
            raise ValueError(f"Invalid plugin tool name: {exc}") from exc
        if not callable(handler):
            raise TypeError(f"Plugin tool {normalized_name!r} must be callable")
        if normalized_name in combined:
            raise ValueError(f"Tool name collision: {normalized_name!r}")
        combined[normalized_name] = handler
    return combined


def list_builtin_tools() -> tuple[str, ...]:
    """Return immutable, sorted names from the private built-in source."""

    return tuple(sorted(_BUILTIN_TOOL_REGISTRY))


def get_tool(name: str):
    """Return a registered tool by name."""

    return TOOL_REGISTRY.get(name)


def list_tools() -> list[str]:
    """Return registered tool names in alphabetical order."""

    return sorted(TOOL_REGISTRY)
