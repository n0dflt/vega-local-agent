import pytest

from plugins.models import (
    PluginManifest, PluginTool, PluginToolActivation, PluginToolState,
    PluginValidationError,
)


def handler():
    return "ok"


def tool(**changes):
    values = dict(name="plugin_echo", handler=handler, domain="coding",
                  permission="READ", capabilities=["project.read"],
                  description="Echo safely.")
    values.update(changes)
    return PluginTool(**values)


def manifest(**changes):
    values = dict(name="sample", version="1.2.3", description="Sample plugin.",
                  domains=["coding"], tools=[tool()], api_version=1)
    values.update(changes)
    return PluginManifest(**values)


def test_valid_models_normalize_collections():
    assert tool().capabilities == ("project.read",)
    assert manifest().domains == ("coding",)
    assert isinstance(manifest().tools, tuple)


@pytest.mark.parametrize(
    "changes",
    [dict(handler=None), dict(name="bad-name"), dict(permission="ALLOW"),
     dict(capabilities=[])],
)
def test_invalid_tool_metadata(changes):
    with pytest.raises(PluginValidationError):
        tool(**changes)


def test_invalid_manifest_version_api_and_duplicates():
    with pytest.raises(PluginValidationError):
        manifest(version="1.0")
    with pytest.raises(PluginValidationError):
        manifest(api_version=2)
    duplicate = tool()
    with pytest.raises(PluginValidationError):
        manifest(tools=[duplicate, duplicate])


def test_activation_is_immutable_and_serializes_without_handler():
    activation = PluginToolActivation(
        "plugin_echo", "sample", "coding", PluginToolState.INACTIVE,
        ["missing_permission_rule"],
    )
    assert activation.reasons == ("missing_permission_rule",)
    assert activation.to_dict() == {
        "tool_name": "plugin_echo", "plugin_name": "sample", "domain": "coding",
        "state": "inactive", "reasons": ["missing_permission_rule"],
    }
    with pytest.raises(PluginValidationError):
        PluginToolActivation(
            "plugin_echo", "sample", "coding", PluginToolState.ACTIVE, ["reason"]
        )
