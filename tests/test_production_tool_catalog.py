from pathlib import Path

from core.tool_catalog import build_tool_catalog
from permissions.policy import load_permission_policy
from tools.registry import TOOL_REGISTRY


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "tool_capabilities.json"


def test_production_catalog_uses_registered_tools() -> None:
    catalog = build_tool_catalog(
        TOOL_REGISTRY,
        CONFIG_PATH,
    )

    assert catalog

    registered_names = set(TOOL_REGISTRY)

    assert all(
        tool.name in registered_names
        for tool in catalog
    )


def test_production_catalog_contains_initial_safe_routes() -> None:
    catalog = build_tool_catalog(
        TOOL_REGISTRY,
        CONFIG_PATH,
    )

    names = {
        tool.name
        for tool in catalog
    }

    assert {
        "read_file",
        "summarize_file",
        "search_in_files",
        "git_diff",
        "release_status",
    }.issubset(names)


def test_contextual_catalog_contains_only_allowed_tools() -> None:
    catalog = build_tool_catalog(
        TOOL_REGISTRY,
        CONFIG_PATH,
    )

    policy = load_permission_policy(
        ROOT,
        registered_tools=TOOL_REGISTRY,
    )

    rules = {
        rule.tool_name: rule
        for rule in policy.rules
    }

    unsafe_tools = [
        tool.name
        for tool in catalog
        if rules[tool.name].effect.value != "allow"
    ]

    assert unsafe_tools == []


def test_confirmed_tools_are_not_automatically_routable() -> None:
    catalog = build_tool_catalog(
        TOOL_REGISTRY,
        CONFIG_PATH,
    )

    names = {
        tool.name
        for tool in catalog
    }

    assert {
        "apply_patch",
        "documentation_build",
        "internet_set",
        "memory_add",
        "propose_patch",
        "propose_patch_from_file",
        "release_check",
        "rollback_patch",
        "terminal_run",
        "test_run",
        "web_fetch",
    }.isdisjoint(names)
