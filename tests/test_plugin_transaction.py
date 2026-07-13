from types import ModuleType
from unittest.mock import patch

import pytest

import plugins.bootstrap as bootstrap_module

from domains.builtin import build_builtin_domain_registry
from permissions import PermissionEffect, PermissionPolicy
from plugins.bootstrap import PluginBootstrapError, bootstrap_plugins
from plugins.models import PluginManifest, PluginTool
from tools.registry import BUILTIN_TOOL_REGISTRY


MODULES = ("trusted.plugins.first", "trusted.plugins.second")


def policy():
    return dict(
        schema_version=1, enabled=True, fail_closed=True,
        allowed_modules=list(MODULES), allowed_plugins=["first", "second", "same"],
        allowed_package_prefixes=["trusted.plugins"], trusted_roots=["trusted"],
        allow_file_paths=False, allow_entry_points=False, max_plugins=4,
    )


def manifest(plugin_name, tool_name):
    return PluginManifest(
        plugin_name, "1.0.0", "Transactional test plugin.", ("coding",),
        (PluginTool(tool_name, lambda: plugin_name, "coding", "READ",
                    ("project.read",), "Transactional test tool."),),
    )


def modules(tmp_path, factories):
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    loaded = {}
    for module_name, factory in zip(MODULES, factories):
        origin = trusted / (module_name.rsplit(".", 1)[-1] + ".py")
        origin.write_text("# controlled transaction module\n", encoding="utf-8")
        module = ModuleType(module_name)
        module.get_plugin_manifest = factory
        loaded[module_name] = module
    return loaded


def run(tmp_path, factories, registry_created):
    loaded = modules(tmp_path, factories)
    permissions = PermissionPolicy(1, PermissionEffect.DENY, "CONFIRM", 4, ())
    def forbidden_registry(*args, **kwargs):
        registry_created.append(True)
        raise AssertionError("final registry must not be created before phase-one success")

    with (
        patch.object(bootstrap_module, "PluginRegistry", side_effect=forbidden_registry),
        patch("plugins.loader.resolve_module", side_effect=lambda name, **kwargs: loaded[name]),
    ):
        return bootstrap_plugins(
            policy(), build_builtin_domain_registry(), project_root=tmp_path,
            builtin_tools=BUILTIN_TOOL_REGISTRY, capability_config={},
            permission_policy=permissions,
        )


def test_second_factory_failure_returns_no_result_but_side_effects_remain(tmp_path):
    side_effects = []

    def first():
        side_effects.append("first")
        return manifest("first", "first_tool")

    def second():
        side_effects.append("second")
        raise RuntimeError("second failed")

    registry_created = []
    with pytest.raises(PluginBootstrapError, match="RuntimeError"):
        run(tmp_path, (first, second), registry_created)
    assert side_effects == ["first", "second"]
    assert registry_created == []


@pytest.mark.parametrize(
    "factories",
    [
        (lambda: manifest("same", "first_tool"),
         lambda: manifest("same", "second_tool")),
        (lambda: manifest("first", "same_tool"),
         lambda: manifest("second", "same_tool")),
        (lambda: manifest("first", "first_tool"),
         lambda: manifest("second", "read_file")),
    ],
)
def test_set_collisions_fail_before_final_registry_is_created(tmp_path, factories):
    registry_created = []
    with pytest.raises(PluginBootstrapError):
        run(tmp_path, factories, registry_created)
    assert registry_created == []
