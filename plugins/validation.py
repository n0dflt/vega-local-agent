"""Explicit validation boundaries for plugin loading and activation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from domains.registry import DomainRegistry
from plugins.models import (
    PluginManifest,
    PluginTool,
    PluginValidationError,
    ROUTING_PERMISSIONS,
)
from plugins.policy import PluginPolicy


_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def validate_module_name(module_name: Any) -> str:
    if not isinstance(module_name, str) or not module_name:
        raise PluginValidationError("module name must be a non-empty string")
    if not _MODULE.fullmatch(module_name):
        raise PluginValidationError("module name must use dotted Python notation")
    return module_name


def validate_module_allowed(module_name: str, policy: PluginPolicy) -> None:
    module = validate_module_name(module_name)
    if not isinstance(policy, PluginPolicy):
        raise PluginValidationError("policy must be a PluginPolicy")
    if module not in policy.allowed_modules:
        raise PluginValidationError(f"module {module!r} is not in allowed_modules")
    if not any(
        module == prefix or module.startswith(prefix + ".")
        for prefix in policy.allowed_package_prefixes
    ):
        raise PluginValidationError(
            f"module {module!r} does not match an allowed package prefix"
        )


def validate_plugin_tool(tool: Any) -> PluginTool:
    if not isinstance(tool, PluginTool):
        raise PluginValidationError("plugin tool must be a PluginTool")
    validate_permission_metadata(tool.permission)
    validate_capability_metadata(tool.capabilities)
    return tool


def validate_plugin_manifest(manifest: Any) -> PluginManifest:
    if not isinstance(manifest, PluginManifest):
        raise PluginValidationError("plugin manifest must be a PluginManifest")
    for tool in manifest.tools:
        validate_plugin_tool(tool)
    return manifest


def validate_permission_metadata(permission: Any) -> str:
    if not isinstance(permission, str) or permission not in ROUTING_PERMISSIONS:
        raise PluginValidationError(f"invalid routing permission: {permission!r}")
    return permission


def validate_capability_metadata(capabilities: Any) -> tuple[str, ...]:
    if not isinstance(capabilities, (list, tuple)) or not capabilities:
        raise PluginValidationError("capability metadata must be non-empty")
    if any(not isinstance(item, str) or not item for item in capabilities):
        raise PluginValidationError("capability metadata contains an invalid value")
    if len(set(capabilities)) != len(capabilities):
        raise PluginValidationError("capability metadata contains duplicates")
    return tuple(capabilities)


def validate_manifest_domains(
    manifest: PluginManifest,
    domain_registry: DomainRegistry,
) -> None:
    validate_plugin_manifest(manifest)
    if not isinstance(domain_registry, DomainRegistry):
        raise PluginValidationError("domain_registry must be a DomainRegistry")
    unknown = sorted(name for name in manifest.domains if domain_registry.get(name) is None)
    if unknown:
        raise PluginValidationError("unknown plugin domains: " + ", ".join(unknown))


def validate_tool_collisions(
    manifest: PluginManifest,
    existing_tool_names: Iterable[str] | Mapping[str, Any],
) -> None:
    validate_plugin_manifest(manifest)
    names = set(
        existing_tool_names.keys()
        if isinstance(existing_tool_names, Mapping)
        else existing_tool_names
    )
    collisions = sorted(tool.name for tool in manifest.tools if tool.name in names)
    if collisions:
        raise PluginValidationError("tool name collisions: " + ", ".join(collisions))


__all__ = [
    "validate_capability_metadata",
    "validate_manifest_domains",
    "validate_module_allowed",
    "validate_module_name",
    "validate_permission_metadata",
    "validate_plugin_manifest",
    "validate_plugin_tool",
    "validate_tool_collisions",
]
