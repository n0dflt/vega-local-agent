import pytest

from plugins.bootstrap import PluginBootstrapResult
from plugins.models import (
    PluginManifest, PluginTool, PluginToolActivation, PluginToolState,
)
from tools.registry import BUILTIN_TOOL_REGISTRY, TOOL_REGISTRY


def handler():
    return "ok"


def result():
    tool = PluginTool("plugin_echo", handler, "coding", "READ",
                      ["project.read"], "Echo safely.")
    manifest = PluginManifest("sample", "1.0.0", "Sample plugin.",
                              ["coding"], [tool])
    activation = PluginToolActivation(
        "plugin_echo", "sample", "coding", PluginToolState.ACTIVE,
    )
    return PluginBootstrapResult(
        [manifest], {"sample": manifest}, [activation],
        {"plugin_echo": handler}, {"plugin_echo": handler}, [],
    )


def test_builtin_registry_is_read_only_and_tool_registry_is_independent():
    assert BUILTIN_TOOL_REGISTRY is not TOOL_REGISTRY
    with pytest.raises(TypeError):
        BUILTIN_TOOL_REGISTRY["evil"] = handler
    TOOL_REGISTRY["temporary_test_tool"] = handler
    try:
        assert "temporary_test_tool" not in BUILTIN_TOOL_REGISTRY
    finally:
        TOOL_REGISTRY.pop("temporary_test_tool")


def test_bootstrap_result_contains_only_immutable_public_collections():
    value = result()
    assert isinstance(value.manifests, tuple)
    assert isinstance(value.activations, tuple)
    assert isinstance(value.manifests[0].tools, tuple)
    assert isinstance(value.manifests[0].tools[0].capabilities, tuple)
    assert not hasattr(value, "plugin_registry")
    for mapping in (
        value.plugin_snapshot,
        value.active_tool_mapping,
        value.combined_tool_mapping,
    ):
        with pytest.raises(TypeError):
            mapping["evil"] = handler
