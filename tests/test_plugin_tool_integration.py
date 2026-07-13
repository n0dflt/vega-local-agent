from core.tool_executor import ToolExecutor
from permissions import (
    PermissionCapability, PermissionEffect, PermissionEvaluator, PermissionPolicy,
    PermissionRisk, PermissionRule,
)
from tools.registry import BUILTIN_TOOL_REGISTRY, TOOL_REGISTRY, build_tool_registry


def plugin_handler(value="ok"):
    return value


def evaluator(rules=()):
    return PermissionEvaluator(
        PermissionPolicy(1, PermissionEffect.DENY, "CONFIRM", 4, tuple(rules))
    )


def test_combined_registry_executor_and_permissions_remain_fail_closed():
    original = dict(TOOL_REGISTRY)
    combined = build_tool_registry({"plugin_echo": plugin_handler})
    assert set(BUILTIN_TOOL_REGISTRY) <= set(combined)
    assert combined["plugin_echo"] is plugin_handler
    denied = ToolExecutor(combined, evaluator()).execute_named("plugin_echo")
    assert denied.error_code == "permission_policy_error"
    rule = PermissionRule("plugin_echo", (PermissionCapability.PROJECT_READ,),
                          PermissionRisk.LOW, PermissionEffect.ALLOW, False,
                          "Explicit test-only rule.")
    allowed = ToolExecutor(combined, evaluator((rule,))).execute_named(
        "plugin_echo", value="done"
    )
    assert allowed.ok and allowed.data == "done"
    assert TOOL_REGISTRY == original


def test_combined_registry_rejects_noncallable_and_collision():
    import pytest
    with pytest.raises(TypeError):
        build_tool_registry({"plugin_bad": None})
    with pytest.raises(ValueError):
        build_tool_registry({"read_file": plugin_handler})


def test_builtin_registry_is_not_the_compatibility_registry():
    assert BUILTIN_TOOL_REGISTRY is not TOOL_REGISTRY
    assert build_tool_registry({}) == dict(BUILTIN_TOOL_REGISTRY)
