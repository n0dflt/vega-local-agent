"""Built-in coding domain metadata."""

from __future__ import annotations

from domains.models import DomainDefinition


def create_coding_domain() -> DomainDefinition:
    return DomainDefinition(
        name="coding",
        description="Project coding, review, testing, documentation, and release workflows.",
        intents=(
            "project_search",
            "bug_fix",
            "test_run",
            "code_review",
            "documentation_update",
            "release_check",
        ),
        capabilities=(
            "project.read",
            "project.write",
            "project.search",
            "git.read",
            "git.diff",
            "patch.manage",
            "patch.propose",
            "test.run",
            "documentation.manage",
            "documentation.status",
            "release.check",
            "release.status",
        ),
        tool_names=(
            "list_dir", "read_file", "find_file", "search_in_files", "summarize_file",
            "propose_patch", "propose_patch_from_file", "list_patches", "show_patch",
            "apply_patch", "rollback_patch", "git_status", "git_diff", "git_diff_cached",
            "git_log", "git_branch", "terminal_list", "terminal_run", "test_list",
            "test_run", "documentation_build", "documentation_policy_load",
            "documentation_status", "documentation_check", "release_policy_load",
            "release_status", "release_check", "release_notes",
        ),
    )


__all__ = ["create_coding_domain"]
