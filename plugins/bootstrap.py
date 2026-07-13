"""Explicit high-level bootstrap for trusted, allowlisted plugins."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from core.tool_catalog import load_tool_capabilities
from domains.registry import DomainRegistry
from permissions.models import PermissionEffect, PermissionPolicy
from permissions.policy import load_permission_policy
from plugins.loader import PluginLoader
from plugins.models import (
    PluginManifest,
    PluginTool,
    PluginToolActivation,
    PluginToolState,
)
from plugins.policy import PluginPolicy, load_plugin_policy
from plugins.registry import PluginRegistry


class PluginBootstrapError(RuntimeError):
    """Raised when fail-closed bootstrap cannot produce an atomic result."""


@dataclass(frozen=True, slots=True)
class PluginBootstrapResult:
    manifests: tuple[PluginManifest, ...]
    plugin_snapshot: Mapping[str, PluginManifest]
    activations: tuple[PluginToolActivation, ...]
    active_tool_mapping: Mapping[str, Callable[..., Any]]
    combined_tool_mapping: Mapping[str, Callable[..., Any]]
    diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        manifests = tuple(self.manifests)
        activations = tuple(self.activations)
        diagnostics = tuple(self.diagnostics)
        if any(not isinstance(item, PluginManifest) for item in manifests):
            raise PluginBootstrapError("manifests must contain PluginManifest values")
        if any(not isinstance(item, PluginToolActivation) for item in activations):
            raise PluginBootstrapError("activations must contain PluginToolActivation values")
        if any(not isinstance(item, str) or not item for item in diagnostics):
            raise PluginBootstrapError("diagnostics must contain non-empty strings")
        object.__setattr__(self, "manifests", manifests)
        object.__setattr__(self, "activations", activations)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(
            self,
            "plugin_snapshot",
            MappingProxyType(dict(self.plugin_snapshot)),
        )
        object.__setattr__(
            self,
            "active_tool_mapping",
            MappingProxyType(dict(self.active_tool_mapping)),
        )
        object.__setattr__(
            self,
            "combined_tool_mapping",
            MappingProxyType(dict(self.combined_tool_mapping)),
        )

    @property
    def combined_registry(self) -> Mapping[str, Callable[..., Any]]:
        return self.combined_tool_mapping

    @property
    def tool_registry(self) -> Mapping[str, Callable[..., Any]]:
        return self.combined_tool_mapping

    @property
    def plugin_handlers(self) -> Mapping[str, Callable[..., Any]]:
        return self.active_tool_mapping

    @property
    def loaded_plugins(self) -> tuple[str, ...]:
        return tuple(manifest.name for manifest in self.manifests)


def _combine_tools(
    builtin_tools: Mapping[str, Callable[..., Any]],
    plugin_tools: Mapping[str, Callable[..., Any]],
) -> dict[str, Callable[..., Any]]:
    combined: dict[str, Callable[..., Any]] = {}
    for source, label in ((builtin_tools, "built-in"), (plugin_tools, "plugin")):
        for name, handler in source.items():
            if not isinstance(name, str) or not name:
                raise PluginBootstrapError(f"{label} tool names must be non-empty strings")
            if not callable(handler):
                raise PluginBootstrapError(f"{label} tool {name!r} must be callable")
            if name in combined:
                raise PluginBootstrapError(f"tool name collision: {name!r}")
            combined[name] = handler
    return combined


def _capability_tools(config: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(config, (str, Path)):
        tools = load_tool_capabilities(config)
    elif isinstance(config, Mapping):
        tools = config.get("tools", config)
    else:
        raise PluginBootstrapError("capability_config must be a mapping or file path")
    if not isinstance(tools, Mapping):
        raise PluginBootstrapError("capability_config tools must be a mapping")
    return dict(tools)


def _permission_policy(
    source: PermissionPolicy | Mapping[str, Any] | str | Path,
) -> PermissionPolicy:
    if isinstance(source, PermissionPolicy):
        return source
    if isinstance(source, Mapping):
        return PermissionPolicy.from_dict(dict(source))
    if not isinstance(source, (str, Path)):
        raise PluginBootstrapError(
            "permission_policy must be a PermissionPolicy, mapping, or path"
        )
    path = Path(source)
    if path.is_dir():
        return load_permission_policy(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PluginBootstrapError(
            f"permission policy could not be read: {type(exc).__name__}: {exc}"
        ) from exc
    return PermissionPolicy.from_dict(data)


def _validate_manifest_set(
    manifests: tuple[PluginManifest, ...],
    builtin_tools: Mapping[str, Callable[..., Any]],
) -> None:
    plugin_names: set[str] = set()
    tool_names = set(builtin_tools)
    for manifest in manifests:
        if manifest.name in plugin_names:
            raise PluginBootstrapError(f"duplicate plugin name: {manifest.name!r}")
        plugin_names.add(manifest.name)
        for tool in manifest.tools:
            if tool.name in tool_names:
                raise PluginBootstrapError(f"tool name collision: {tool.name!r}")
            tool_names.add(tool.name)


def _capability_reasons(
    tool: PluginTool,
    capability_tools: Mapping[str, Any],
) -> tuple[str, ...]:
    raw = capability_tools.get(tool.name)
    if raw is None:
        return ("missing_capability_metadata",)
    if not isinstance(raw, Mapping):
        return ("invalid_capability_metadata",)
    reasons: list[str] = []
    if raw.get("permission") != tool.permission:
        reasons.append("capability_permission_mismatch")
    raw_capabilities = raw.get("capabilities")
    if not isinstance(raw_capabilities, (list, tuple)) or any(
        not isinstance(item, str) or not item for item in raw_capabilities
    ):
        reasons.append("invalid_capability_metadata")
    elif len(set(raw_capabilities)) != len(raw_capabilities):
        reasons.append("invalid_capability_metadata")
    elif tuple(sorted(raw_capabilities)) != tuple(sorted(tool.capabilities)):
        reasons.append("capabilities_mismatch")
    return tuple(reasons)


def _activation_for_tool(
    manifest: PluginManifest,
    tool: PluginTool,
    domain_registry: DomainRegistry,
    permission_rules: Mapping[str, Any],
    capability_tools: Mapping[str, Any],
) -> PluginToolActivation:
    reasons: list[str] = []
    domain = domain_registry.get(tool.domain)
    if domain is None:
        raise PluginBootstrapError(f"unknown plugin domain: {tool.domain!r}")
    if not domain.enabled:
        reasons.append("domain_disabled")
    rule = permission_rules.get(tool.name)
    if rule is None:
        reasons.append("missing_permission_rule")
    elif rule.effect is PermissionEffect.DENY:
        reasons.append("permission_denied")
    reasons.extend(_capability_reasons(tool, capability_tools))
    return PluginToolActivation(
        tool_name=tool.name,
        plugin_name=manifest.name,
        domain=tool.domain,
        state=(PluginToolState.INACTIVE if reasons else PluginToolState.ACTIVE),
        reasons=tuple(reasons),
    )


def bootstrap_plugins(
    policy_source,
    domain_registry: DomainRegistry,
    *,
    project_root: str | Path | None = None,
    builtin_tools: Mapping[str, Callable[..., Any]],
    capability_config=None,
    permission_policy: PermissionPolicy | Mapping[str, Any] | str | Path | None = None,
) -> PluginBootstrapResult:
    try:
        policy: PluginPolicy = load_plugin_policy(policy_source)
        if not isinstance(domain_registry, DomainRegistry):
            raise PluginBootstrapError("domain_registry must be a DomainRegistry")
        if not isinstance(builtin_tools, Mapping):
            raise PluginBootstrapError("builtin_tools must be a mapping")
        builtin_copy = _combine_tools(builtin_tools, {})
        if not policy.enabled:
            return PluginBootstrapResult(
                (),
                {},
                (),
                {},
                builtin_copy,
                ("Plugin policy is disabled; no modules were imported.",),
            )
        if project_root is None:
            raise PluginBootstrapError("enabled plugin policy requires project_root")
        if capability_config is None:
            raise PluginBootstrapError("enabled plugin policy requires capability_config")
        if permission_policy is None:
            raise PluginBootstrapError("enabled plugin policy requires permission_policy")
        if not policy.trusted_roots:
            raise PluginBootstrapError("enabled plugin policy requires trusted_roots")
        if len(policy.allowed_modules) > policy.max_plugins:
            raise PluginBootstrapError("allowed_modules exceeds max_plugins")
        capability_tools = _capability_tools(capability_config)
        permissions = _permission_policy(permission_policy)
        permission_rules = {rule.tool_name: rule for rule in permissions.rules}
        loader = PluginLoader(
            policy,
            domain_registry,
            project_root=project_root,
        )
        collected: list[PluginManifest] = []
        for module_name in policy.allowed_modules:
            collected.append(loader.load_manifest(module_name))
        manifests = tuple(collected)
        if len(manifests) > policy.max_plugins:
            raise PluginBootstrapError("loaded manifests exceed max_plugins")
        _validate_manifest_set(manifests, builtin_copy)

        activations = tuple(
            sorted(
                (
                    _activation_for_tool(
                        manifest,
                        tool,
                        domain_registry,
                        permission_rules,
                        capability_tools,
                    )
                    for manifest in manifests
                    for tool in manifest.tools
                ),
                key=lambda item: (item.plugin_name, item.tool_name),
            )
        )
        activation_by_name = {item.tool_name: item for item in activations}
        active_handlers = {
            tool.name: tool.handler
            for manifest in manifests
            for tool in manifest.tools
            if activation_by_name[tool.name].active
        }
        diagnostics = tuple(
            f"{item.plugin_name}:{item.tool_name}:{reason}"
            for item in activations
            for reason in item.reasons
        )

        # Phase 2: publish only after the complete set and activation state pass.
        registry = PluginRegistry(builtin_tools=builtin_copy)
        for manifest in manifests:
            registry.register(manifest)
        snapshot = registry.snapshot()
        combined = _combine_tools(builtin_copy, active_handlers)
        return PluginBootstrapResult(
            manifests,
            snapshot,
            activations,
            active_handlers,
            combined,
            diagnostics,
        )
    except PluginBootstrapError:
        raise
    except Exception as exc:
        raise PluginBootstrapError(
            f"Plugin bootstrap failed closed: {type(exc).__name__}: {exc}"
        ) from exc


__all__ = ["PluginBootstrapError", "PluginBootstrapResult", "bootstrap_plugins"]
