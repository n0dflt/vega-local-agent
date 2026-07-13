import pytest

from core.tool_executor import ToolExecutionStatus, ToolExecutor
from permissions import (
    PermissionCapability, PermissionEffect, PermissionEvaluator, PermissionPolicy,
    PermissionRisk, PermissionRule,
)
from plugins.bootstrap import PluginBootstrapResult
from plugins.models import (
    PluginManifest, PluginTool, PluginToolActivation, PluginToolState,
)
from plugins.runtime import build_plugin_tool_executor


def handler(value="ok"):
    return value


def bootstrap_result(*, active=True):
    tool = PluginTool("plugin_echo", handler, "coding", "READ",
                      ("project.read",), "Echo safely.")
    manifest = PluginManifest("sample", "1.0.0", "Sample plugin.",
                              ("coding",), (tool,))
    activation = PluginToolActivation(
        "plugin_echo", "sample", "coding",
        PluginToolState.ACTIVE if active else PluginToolState.INACTIVE,
        () if active else ("permission_denied",),
    )
    mapping = {"plugin_echo": handler} if active else {}
    return PluginBootstrapResult(
        (manifest,), {"sample": manifest}, (activation,), mapping, mapping, (),
    )


def evaluator(effect):
    rule = PermissionRule(
        "plugin_echo", (PermissionCapability.PROJECT_READ,), PermissionRisk.LOW,
        effect, False, "Runtime test rule.",
    )
    return PermissionEvaluator(
        PermissionPolicy(1, PermissionEffect.DENY, "CONFIRM", 4, (rule,))
    )


def test_runtime_factory_requires_typed_result_and_evaluator():
    with pytest.raises(TypeError):
        build_plugin_tool_executor(object(), evaluator(PermissionEffect.ALLOW))
    with pytest.raises(TypeError):
        build_plugin_tool_executor(bootstrap_result(), None)


def test_allow_and_confirm_execution_use_existing_tool_executor():
    allowed = build_plugin_tool_executor(
        bootstrap_result(), evaluator(PermissionEffect.ALLOW)
    )
    assert isinstance(allowed, ToolExecutor)
    assert allowed.execute_named("plugin_echo", value="done").data == "done"

    confirmed = build_plugin_tool_executor(
        bootstrap_result(), evaluator(PermissionEffect.CONFIRM)
    )
    assert confirmed.execute_named("plugin_echo").error_code == "confirmation_required"
    assert confirmed.execute_named(
        "plugin_echo", confirmation_token="CONFIRM"
    ).status is ToolExecutionStatus.SUCCESS


def test_deny_tool_is_absent_and_legacy_direct_executor_remains_possible():
    denied = build_plugin_tool_executor(
        bootstrap_result(active=False), evaluator(PermissionEffect.DENY)
    )
    assert denied.execute_named("plugin_echo").status is ToolExecutionStatus.UNKNOWN_TOOL

    # Python is not sandboxed; only the supported factory mandates an evaluator.
    assert ToolExecutor({"plugin_echo": handler}).execute_named("plugin_echo").ok
