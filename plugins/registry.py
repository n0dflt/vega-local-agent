"""Atomic registry for validated plugin manifests and handlers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import Any

from plugins.models import PluginManifest, PluginTool
from plugins.validation import validate_plugin_manifest


class PluginRegistryError(ValueError):
    """Raised when plugin registration would be ambiguous or destructive."""


class PluginRegistry:
    def __init__(
        self,
        reserved_tool_names: Iterable[str] | Mapping[str, Any] = (),
        *,
        builtin_tools: Iterable[str] | Mapping[str, Any] | None = None,
    ) -> None:
        if builtin_tools is not None:
            if reserved_tool_names:
                raise PluginRegistryError(
                    "use either reserved_tool_names or builtin_tools, not both"
                )
            reserved_tool_names = builtin_tools
        values = (
            reserved_tool_names.keys()
            if isinstance(reserved_tool_names, Mapping)
            else reserved_tool_names
        )
        self._reserved_tool_names = frozenset(values)
        if any(not isinstance(name, str) or not name for name in self._reserved_tool_names):
            raise PluginRegistryError("reserved tool names must be non-empty strings")
        self._plugins: dict[str, PluginManifest] = {}
        self._tools: dict[str, PluginTool] = {}

    def register(self, manifest: PluginManifest) -> None:
        try:
            validate_plugin_manifest(manifest)
        except ValueError as exc:
            raise PluginRegistryError(str(exc)) from exc
        if manifest.name in self._plugins:
            raise PluginRegistryError(f"Plugin {manifest.name!r} is already registered")
        incoming = {tool.name for tool in manifest.tools}
        collisions = sorted(incoming & (set(self._tools) | set(self._reserved_tool_names)))
        if collisions:
            raise PluginRegistryError("Tool name collisions: " + ", ".join(collisions))
        # All checks precede mutation, so registration is atomic.
        self._plugins[manifest.name] = manifest
        self._tools.update({tool.name: tool for tool in manifest.tools})

    def get(self, name: str) -> PluginManifest | None:
        return self._plugins.get(self._name(name))

    def require(self, name: str) -> PluginManifest:
        normalized = self._name(name)
        manifest = self._plugins.get(normalized)
        if manifest is None:
            raise PluginRegistryError(f"Unknown plugin: {normalized!r}")
        return manifest

    def list_plugins(self) -> tuple[PluginManifest, ...]:
        return tuple(sorted(self._plugins.values(), key=lambda item: item.name))

    def list_tools(self) -> tuple[PluginTool, ...]:
        return tuple(sorted(self._tools.values(), key=lambda item: item.name))

    def tool_mapping(self) -> Mapping[str, Callable[..., Any]]:
        return MappingProxyType(
            {name: self._tools[name].handler for name in sorted(self._tools)}
        )

    def snapshot(self) -> Mapping[str, PluginManifest]:
        return MappingProxyType(dict(sorted(self._plugins.items())))

    @staticmethod
    def _name(value: str) -> str:
        if not isinstance(value, str) or not value:
            raise PluginRegistryError("plugin name must be a non-empty string")
        return value


__all__ = ["PluginRegistry", "PluginRegistryError"]
