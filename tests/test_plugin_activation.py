import json
from types import ModuleType
from unittest.mock import patch

import pytest

from domains.builtin import build_builtin_domain_registry
from domains.models import DomainDefinition
from domains.registry import DomainRegistry
from permissions import (
    PermissionCapability, PermissionEffect, PermissionPolicy, PermissionRisk,
    PermissionRule,
)
from plugins.bootstrap import PluginBootstrapError, bootstrap_plugins
from plugins.models import PluginManifest, PluginTool, PluginToolState
from tools.registry import BUILTIN_TOOL_REGISTRY


MODULE = "trusted.plugins.sample"
_DEFAULT_SOURCE = object()


def plugin_policy(**changes):
    data = dict(
        schema_version=1, enabled=True, fail_closed=True,
        allowed_modules=[MODULE], allowed_plugins=["sample"],
        allowed_package_prefixes=["trusted.plugins"], trusted_roots=["trusted"],
        allow_file_paths=False, allow_entry_points=False, max_plugins=4,
    )
    data.update(changes)
    return data


def manifest(domain="coding"):
    return PluginManifest(
        "sample", "1.0.0", "Sample plugin.", (domain,),
        (PluginTool("plugin_echo", lambda value="ok": value, domain, "READ",
                    ("project.read",), "Echo safely."),),
    )


def permission_policy(effect=None):
    rules = ()
    if effect is not None:
        rules = (
            PermissionRule(
                "plugin_echo", (PermissionCapability.PROJECT_READ,),
                PermissionRisk.LOW, effect, False, "Test plugin rule.",
            ),
        )
    return PermissionPolicy(1, PermissionEffect.DENY, "CONFIRM", 4, rules)


def capabilities(**changes):
    metadata = dict(permission="READ", capabilities=["project.read"],
                    description="Routing metadata.")
    metadata.update(changes)
    return {"plugin_echo": metadata}


def run_bootstrap(
    tmp_path,
    *,
    effect=PermissionEffect.ALLOW,
    capability_config=None,
    domain_registry=None,
    plugin_manifest=None,
    permission_source=_DEFAULT_SOURCE,
):
    trusted = tmp_path / "trusted"
    trusted.mkdir(exist_ok=True)
    origin = trusted / "sample.py"
    origin.write_text("# controlled module\n", encoding="utf-8")
    module = ModuleType(MODULE)
    module.get_plugin_manifest = lambda: plugin_manifest or manifest()
    with patch("plugins.loader.resolve_module", return_value=module):
        return bootstrap_plugins(
            plugin_policy(),
            domain_registry or build_builtin_domain_registry(),
            project_root=tmp_path,
            builtin_tools=BUILTIN_TOOL_REGISTRY,
            capability_config=(capabilities() if capability_config is None else capability_config),
            permission_policy=(
                permission_policy(effect)
                if permission_source is _DEFAULT_SOURCE
                else permission_source
            ),
        )


def test_missing_permission_rule_is_inactive_but_manifest_remains_loaded(tmp_path):
    result = run_bootstrap(tmp_path, effect=None)
    activation = result.activations[0]
    assert activation.state is PluginToolState.INACTIVE
    assert activation.reasons == ("missing_permission_rule",)
    assert "plugin_echo" not in result.combined_tool_mapping
    assert result.manifests[0].name == "sample"
    assert result.diagnostics == ("sample:plugin_echo:missing_permission_rule",)


def test_deny_rule_is_policy_known_but_inactive(tmp_path):
    result = run_bootstrap(tmp_path, effect=PermissionEffect.DENY)
    assert result.activations[0].reasons == ("permission_denied",)
    assert "plugin_echo" not in result.active_tool_mapping


@pytest.mark.parametrize("effect", [PermissionEffect.ALLOW, PermissionEffect.CONFIRM])
def test_allow_and_confirm_rules_with_matching_metadata_are_active(tmp_path, effect):
    result = run_bootstrap(tmp_path, effect=effect)
    assert result.activations[0].state is PluginToolState.ACTIVE
    assert result.activations[0].reasons == ()
    assert result.combined_tool_mapping["plugin_echo"]() == "ok"


@pytest.mark.parametrize(
    ("config", "reason"),
    [({}, "missing_capability_metadata"),
     (capabilities(permission="WRITE"), "capability_permission_mismatch"),
     (capabilities(capabilities=["project.write"]), "capabilities_mismatch")],
)
def test_capability_gate_mismatches_are_inactive(tmp_path, config, reason):
    result = run_bootstrap(tmp_path, capability_config=config)
    assert reason in result.activations[0].reasons
    assert "plugin_echo" not in result.combined_tool_mapping


def test_disabled_domain_is_inactive(tmp_path):
    domains = DomainRegistry()
    domains.register(DomainDefinition(
        "coding", "Disabled coding domain.", ("test_run",), ("project.read",),
        ("read_file",), False,
    ))
    result = run_bootstrap(tmp_path, domain_registry=domains)
    assert result.activations[0].reasons == ("domain_disabled",)


def test_unknown_domain_is_bootstrap_error(tmp_path):
    with pytest.raises(PluginBootstrapError, match="unknown plugin domains"):
        run_bootstrap(tmp_path, plugin_manifest=manifest("unknown"))


def test_permission_mapping_source_is_supported(tmp_path):
    result = run_bootstrap(
        tmp_path,
        permission_source=permission_policy(PermissionEffect.ALLOW).to_dict(),
    )
    assert result.activations[0].active


def test_permission_and_capability_json_paths_are_supported(tmp_path):
    permission_path = tmp_path / "permission.json"
    permission_path.write_text(
        json.dumps(permission_policy(PermissionEffect.ALLOW).to_dict()),
        encoding="utf-8-sig",
    )
    capability_path = tmp_path / "capabilities.json"
    capability_path.write_text(
        json.dumps({"schema_version": 1, "tools": capabilities()}),
        encoding="utf-8-sig",
    )
    result = run_bootstrap(
        tmp_path,
        capability_config=capability_path,
        permission_source=permission_path,
    )
    assert result.activations[0].active
