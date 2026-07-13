import pytest

from plugins.models import PluginManifest, PluginTool
from plugins.registry import PluginRegistry, PluginRegistryError


def manifest(plugin_name, tool_name):
    def handler():
        return plugin_name
    return PluginManifest(plugin_name, "1.0.0", "Test plugin.", ("coding",),
                          (PluginTool(tool_name, handler, "coding", "READ",
                                      ("project.read",), "Test tool."),))


def test_registry_is_sorted_immutable_and_does_not_execute():
    registry = PluginRegistry()
    registry.register(manifest("zeta", "zeta_tool"))
    registry.register(manifest("alpha", "alpha_tool"))
    assert tuple(item.name for item in registry.list_plugins()) == ("alpha", "zeta")
    assert tuple(item.name for item in registry.list_tools()) == ("alpha_tool", "zeta_tool")
    assert registry.get("alpha") is registry.require("alpha")
    assert registry.tool_mapping()["alpha_tool"]() == "alpha"
    with pytest.raises(TypeError):
        registry.snapshot()["new"] = manifest("new", "new_tool")


def test_plugin_cross_plugin_and_builtin_collisions_are_atomic():
    registry = PluginRegistry(builtin_tools={"read_file": lambda: None})
    registry.register(manifest("alpha", "alpha_tool"))
    with pytest.raises(PluginRegistryError):
        registry.register(manifest("alpha", "other_tool"))
    with pytest.raises(PluginRegistryError):
        registry.register(manifest("beta", "alpha_tool"))
    with pytest.raises(PluginRegistryError):
        registry.register(manifest("beta", "read_file"))
    assert tuple(item.name for item in registry.list_plugins()) == ("alpha",)
