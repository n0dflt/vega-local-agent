from __future__ import annotations

import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.production_snapshot as snapshot_module
from core.contextual_router import ContextualRoutingError
from core.policy_consistency import PolicyIssueCode, PolicyTool
from core.production_snapshot import ProductionSnapshot, build_production_snapshot
from permissions.models import PermissionPolicy
from plugins.bootstrap import PluginBootstrapError, PluginBootstrapResult
from plugins.models import (
    PluginManifest,
    PluginTool,
    PluginToolActivation,
    PluginToolState,
)
from tools.registry import BUILTIN_TOOL_REGISTRY, TOOL_REGISTRY


ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_is_immutable_and_contains_no_execution_authority() -> None:
    snapshot = build_production_snapshot(ROOT)

    assert isinstance(snapshot, ProductionSnapshot)
    assert isinstance(snapshot.tools, tuple)
    assert all(isinstance(tool, PolicyTool) for tool in snapshot.tools)
    assert "CONFIRM" not in repr(snapshot)
    assert not any(callable(value) for value in snapshot.tools)
    with pytest.raises(FrozenInstanceError):
        snapshot.tools = ()


def test_current_production_configuration_builds_without_fatal_issues() -> None:
    snapshot = build_production_snapshot(ROOT)

    assert snapshot.can_execute_tools
    assert snapshot.consistency_report.ok
    assert snapshot.consistency_report.fatal_issues == ()
    assert {
        issue.subject for issue in snapshot.consistency_report.degraded_issues
    } == {"bug_fix", "test_run"}
    assert snapshot.effective_tool_names == tuple(sorted(BUILTIN_TOOL_REGISTRY))
    assert snapshot.plugin_activations == ()


def test_build_does_not_mutate_either_registry_and_is_repeatable() -> None:
    builtin_before = dict(BUILTIN_TOOL_REGISTRY)
    compatibility_before = dict(TOOL_REGISTRY)

    first = build_production_snapshot(ROOT)
    second = build_production_snapshot(ROOT)

    assert first == second
    assert dict(BUILTIN_TOOL_REGISTRY) == builtin_before
    assert dict(TOOL_REGISTRY) == compatibility_before


def test_capability_dictionary_order_does_not_change_snapshot(monkeypatch) -> None:
    original = snapshot_module.load_tool_capabilities
    baseline = build_production_snapshot(ROOT)

    def reversed_capabilities(path):
        values = original(path)
        return dict(reversed(tuple(values.items())))

    monkeypatch.setattr(snapshot_module, "load_tool_capabilities", reversed_capabilities)
    assert build_production_snapshot(ROOT) == baseline


def test_disabled_plugin_policy_produces_no_active_plugin_tools() -> None:
    snapshot = build_production_snapshot(ROOT)
    assert snapshot.plugin_activations == ()
    assert all(tool.source == "builtin" for tool in snapshot.tools)


def _permission_policy_with_plugin_rule() -> PermissionPolicy:
    data = snapshot_module.load_permission_policy(ROOT).to_dict()
    data["rules"].append(
        {
            "tool_name": "plugin_reader",
            "capabilities": ["project.read"],
            "risk": "low",
            "effect": "allow",
            "session_grant_allowed": False,
            "reason": "Test plugin read.",
        }
    )
    return PermissionPolicy.from_dict(data)


def _plugin_bootstrap(*, active: bool) -> PluginBootstrapResult:
    def handler():
        raise AssertionError("snapshot construction must not execute plugin handlers")

    tool = PluginTool(
        name="plugin_reader",
        handler=handler,
        domain="coding",
        permission="READ",
        capabilities=("project.read",),
        description="Test reader.",
    )
    manifest = PluginManifest(
        name="sample_plugin",
        version="1.0.0",
        description="Test plugin.",
        domains=("coding",),
        tools=(tool,),
    )
    activation = PluginToolActivation(
        tool_name=tool.name,
        plugin_name=manifest.name,
        domain=tool.domain,
        state=PluginToolState.ACTIVE if active else PluginToolState.INACTIVE,
        reasons=() if active else ("permission_denied",),
    )
    active_mapping = {tool.name: handler} if active else {}
    combined = dict(BUILTIN_TOOL_REGISTRY)
    combined.update(active_mapping)
    return PluginBootstrapResult(
        manifests=(manifest,),
        plugin_snapshot={manifest.name: manifest},
        activations=(activation,),
        active_tool_mapping=active_mapping,
        combined_tool_mapping=combined,
        diagnostics=() if active else ("sample_plugin:plugin_reader:permission_denied",),
    )


def _install_fake_plugin(monkeypatch, *, active: bool) -> None:
    original_capabilities = snapshot_module.load_tool_capabilities
    plugin_permission_policy = _permission_policy_with_plugin_rule()

    def capabilities(path):
        values = dict(original_capabilities(path))
        values["plugin_reader"] = {
            "permission": "READ",
            "capabilities": ["project.read"],
            "description": "Test reader.",
        }
        return values

    monkeypatch.setattr(snapshot_module, "load_tool_capabilities", capabilities)
    monkeypatch.setattr(
        snapshot_module,
        "load_permission_policy",
        lambda root: plugin_permission_policy,
    )
    monkeypatch.setattr(
        snapshot_module,
        "load_plugin_policy",
        lambda path: SimpleNamespace(enabled=True),
    )
    monkeypatch.setattr(
        snapshot_module,
        "bootstrap_plugins",
        lambda *args, **kwargs: _plugin_bootstrap(active=active),
    )


def test_allowed_plugin_uses_existing_bootstrap_result(monkeypatch) -> None:
    _install_fake_plugin(monkeypatch, active=True)

    snapshot = build_production_snapshot(ROOT)

    assert snapshot.can_execute_tools
    assert "plugin_reader" in snapshot.effective_tool_names
    assert snapshot.plugin_activations[0].active
    assert "handler" not in repr(snapshot.tools)


def test_inactive_plugin_is_excluded_from_effective_tools(monkeypatch) -> None:
    _install_fake_plugin(monkeypatch, active=False)

    snapshot = build_production_snapshot(ROOT)

    assert "plugin_reader" not in snapshot.effective_tool_names
    assert not snapshot.plugin_activations[0].active


def test_plugin_collision_or_partial_bootstrap_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        snapshot_module,
        "load_plugin_policy",
        lambda path: SimpleNamespace(enabled=True),
    )

    def fail(*args, **kwargs):
        raise PluginBootstrapError("tool name collision: read_file")

    monkeypatch.setattr(snapshot_module, "bootstrap_plugins", fail)
    snapshot = build_production_snapshot(ROOT)

    assert not snapshot.can_execute_tools
    assert snapshot.tools == ()
    assert snapshot.plugin_activations == ()
    assert snapshot.consistency_report.issues[0].code is PolicyIssueCode.CONFIGURATION_ERROR
    assert "read_file" not in repr(snapshot.consistency_report.to_safe_dict())


def test_missing_permission_rule_prevents_execution(monkeypatch) -> None:
    policy = snapshot_module.load_permission_policy(ROOT)
    data = policy.to_dict()
    data["rules"] = [
        rule for rule in data["rules"] if rule["tool_name"] != "read_file"
    ]
    incomplete = PermissionPolicy.from_dict(data)
    monkeypatch.setattr(snapshot_module, "load_permission_policy", lambda root: incomplete)

    snapshot = build_production_snapshot(ROOT)

    assert not snapshot.can_execute_tools
    assert PolicyIssueCode.MISSING_PERMISSION_RULE in {
        issue.code for issue in snapshot.consistency_report.issues
    }
    assert "read_file" not in snapshot.effective_tool_names


def test_malformed_policy_is_structured_and_prevents_execution(monkeypatch) -> None:
    def malformed(path):
        raise ContextualRoutingError("secret raw policy content")

    monkeypatch.setattr(snapshot_module, "load_tool_routing_policy", malformed)
    snapshot = build_production_snapshot(ROOT)
    rendered = repr(snapshot.consistency_report.to_safe_dict())

    assert not snapshot.can_execute_tools
    assert snapshot.tools == ()
    assert "secret raw policy content" not in rendered
    assert "ContextualRoutingError" in rendered


def test_malformed_capability_metadata_is_structured(monkeypatch) -> None:
    original = snapshot_module.load_tool_capabilities

    def malformed(path):
        values = dict(original(path))
        values["read_file"] = {"permission": "READ", "capabilities": 42}
        return values

    monkeypatch.setattr(snapshot_module, "load_tool_capabilities", malformed)
    snapshot = build_production_snapshot(ROOT)

    assert not snapshot.can_execute_tools
    assert snapshot.tools == ()
    assert snapshot.consistency_report.issues[0].code is PolicyIssueCode.CONFIGURATION_ERROR


def test_snapshot_creation_does_not_create_runtime_state(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "config", tmp_path / "config")

    snapshot = build_production_snapshot(tmp_path)

    assert snapshot.can_execute_tools
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "logs").exists()


def test_snapshot_does_not_query_ollama(monkeypatch) -> None:
    def forbidden():
        raise AssertionError("Ollama availability must not be queried")

    monkeypatch.setattr("core.model_router.get_installed_ollama_models", forbidden)
    assert build_production_snapshot(ROOT).can_execute_tools


def test_snapshot_does_not_execute_builtin_tools(monkeypatch) -> None:
    calls: list[str] = []

    def forbidden_tool():
        calls.append("called")
        raise AssertionError("tool executed")

    inert_registry = {name: forbidden_tool for name in BUILTIN_TOOL_REGISTRY}
    monkeypatch.setattr(snapshot_module, "BUILTIN_TOOL_REGISTRY", inert_registry)

    snapshot = build_production_snapshot(ROOT)

    assert snapshot.can_execute_tools
    assert calls == []
