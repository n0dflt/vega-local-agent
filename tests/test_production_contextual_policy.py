from pathlib import Path

from core.contextual_router import (
    load_tool_routing_policy,
    route_contextual_request,
)
from tools.registry import TOOL_REGISTRY


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = (
    ROOT / "config" / "tool_routing_policy.json"
)
CAPABILITIES_PATH = (
    ROOT / "config" / "tool_capabilities.json"
)

SEARCH_REQUEST = (
    "\u041d\u0430\u0439\u0434\u0438 "
    '"legacy_client" '
    "\u0432 "
    "\u043f\u0440\u043e\u0435\u043a\u0442\u0435"
)


def test_production_contextual_routing_is_enabled() -> None:
    policy = load_tool_routing_policy(
        POLICY_PATH
    )

    assert policy.enabled is True
    assert policy.allow_explicit_execution is True
    assert set(policy.automatic_permissions) == {
        "READ",
        "DRAFT",
    }


def test_dangerous_permissions_are_not_automatic() -> None:
    policy = load_tool_routing_policy(
        POLICY_PATH
    )

    dangerous = {
        "WRITE",
        "EXECUTE",
        "SEND",
        "DELETE",
        "ADMIN",
    }

    assert dangerous.isdisjoint(
        policy.automatic_permissions
    )
    assert dangerous.issubset(
        policy.confirmation_permissions
    )


def test_unsafe_generation_options_stay_disabled() -> None:
    policy = load_tool_routing_policy(
        POLICY_PATH
    )

    assert policy.allow_arbitrary_tool_names is False
    assert policy.allow_shell_generation is False
    assert policy.fail_closed is True


def test_production_search_request_builds_safe_plan() -> None:
    result = route_contextual_request(
        SEARCH_REQUEST,
        TOOL_REGISTRY,
        CAPABILITIES_PATH,
        POLICY_PATH,
        workspace=ROOT,
    )

    assert result.policy.enabled is True
    assert result.requires_confirmation is False
    assert result.can_auto_execute is True

    assert len(result.plan.steps) == 1

    step = result.plan.steps[0]

    assert step.tool_name == "search_in_files"
    assert step.required_permission == "READ"
    assert step.arguments == {
        "query": "legacy_client",
        "path": ".",
    }
