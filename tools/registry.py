"""Registry of tools available to VEGA."""

from __future__ import annotations

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
from tools.terminal_tools import (
    list_allowed_commands,
    run_allowed_command,
)
from tools.test_tools import (
    list_test_groups,
    run_test_group,
)
from tools.web_tools import fetch_url


TOOL_REGISTRY = {
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
}


def get_tool(name: str):
    """Return a registered tool by name."""

    return TOOL_REGISTRY.get(name)


def list_tools() -> list[str]:
    """Return registered tool names in alphabetical order."""

    return sorted(TOOL_REGISTRY)
