"""Strict immutable models for trusted local plugins."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import re
from typing import Any

from domains.models import DomainValidationError, validate_domain_name
from permissions.models import PermissionValidationError, validate_tool_name


class PluginValidationError(ValueError):
    """Raised when plugin metadata violates the Plugin API contract."""


ROUTING_PERMISSIONS = frozenset(
    {"READ", "ANALYZE", "DRAFT", "WRITE", "EXECUTE", "SEND", "DELETE", "ADMIN"}
)
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_MAX_DESCRIPTION_LENGTH = 500


def _description(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PluginValidationError("description must be a non-empty string")
    if value != value.strip() or len(value) > _MAX_DESCRIPTION_LENGTH:
        raise PluginValidationError(
            "description must be trimmed and at most 500 characters"
        )
    return value


def _domain(value: Any, *, field: str = "domain") -> str:
    try:
        return validate_domain_name(value, field=field)
    except DomainValidationError as exc:
        raise PluginValidationError(str(exc)) from exc


def _tool_name(value: Any) -> str:
    try:
        return validate_tool_name(value)
    except PermissionValidationError as exc:
        raise PluginValidationError(str(exc)) from exc


def _capabilities(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise PluginValidationError("capabilities must be a non-empty list or tuple")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _CAPABILITY.fullmatch(item):
            raise PluginValidationError(
                "capabilities must use normalized lowercase dotted notation"
            )
        result.append(item)
    if len(set(result)) != len(result):
        raise PluginValidationError("capabilities must not contain duplicates")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class PluginTool:
    name: str
    handler: Callable[..., Any]
    domain: str
    permission: str
    capabilities: tuple[str, ...]
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _tool_name(self.name))
        if not callable(self.handler):
            raise PluginValidationError("handler must be callable")
        object.__setattr__(self, "domain", _domain(self.domain))
        if not isinstance(self.permission, str) or self.permission not in ROUTING_PERMISSIONS:
            raise PluginValidationError(f"invalid routing permission: {self.permission!r}")
        object.__setattr__(self, "capabilities", _capabilities(self.capabilities))
        object.__setattr__(self, "description", _description(self.description))


@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    version: str
    description: str
    domains: tuple[str, ...]
    tools: tuple[PluginTool, ...]
    api_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _domain(self.name, field="plugin name"))
        if not isinstance(self.version, str) or not _VERSION.fullmatch(self.version):
            raise PluginValidationError("version must use strict X.Y.Z numeric format")
        object.__setattr__(self, "description", _description(self.description))
        if not isinstance(self.domains, (list, tuple)) or not self.domains:
            raise PluginValidationError("domains must be a non-empty list or tuple")
        domains = tuple(_domain(item) for item in self.domains)
        if len(set(domains)) != len(domains):
            raise PluginValidationError("domains must not contain duplicates")
        object.__setattr__(self, "domains", domains)
        if not isinstance(self.tools, (list, tuple)):
            raise PluginValidationError("tools must be a list or tuple")
        tools = tuple(self.tools)
        if any(not isinstance(tool, PluginTool) for tool in tools):
            raise PluginValidationError("tools must contain only PluginTool values")
        names = [tool.name for tool in tools]
        if len(set(names)) != len(names):
            raise PluginValidationError("tool names must be unique within a manifest")
        undeclared = sorted({tool.domain for tool in tools} - set(domains))
        if undeclared:
            raise PluginValidationError(
                "tool domains must be declared by the manifest: " + ", ".join(undeclared)
            )
        object.__setattr__(self, "tools", tools)
        if type(self.api_version) is not int or self.api_version != 1:
            raise PluginValidationError("supported api_version is exactly 1")


class PluginToolState(str, Enum):
    """Final activation state for a tool from a successfully loaded manifest."""

    LOADED = "loaded"
    INACTIVE = "inactive"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class PluginToolActivation:
    """Immutable result of applying the domain, permission and routing gates."""

    tool_name: str
    plugin_name: str
    domain: str
    state: PluginToolState
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_name", _tool_name(self.tool_name))
        object.__setattr__(self, "plugin_name", _domain(self.plugin_name, field="plugin name"))
        object.__setattr__(self, "domain", _domain(self.domain))
        if not isinstance(self.state, PluginToolState):
            raise PluginValidationError("state must be a PluginToolState")
        if not isinstance(self.reasons, (list, tuple)):
            raise PluginValidationError("reasons must be a list or tuple")
        reasons = tuple(self.reasons)
        if any(not isinstance(reason, str) or not reason for reason in reasons):
            raise PluginValidationError("reasons must contain non-empty strings")
        if len(set(reasons)) != len(reasons):
            raise PluginValidationError("reasons must not contain duplicates")
        if self.state is PluginToolState.ACTIVE and reasons:
            raise PluginValidationError("active tools must not contain inactive reasons")
        if self.state is PluginToolState.INACTIVE and not reasons:
            raise PluginValidationError("inactive tools must contain at least one reason")
        object.__setattr__(self, "reasons", reasons)

    @property
    def eligible(self) -> bool:
        return self.state is PluginToolState.ACTIVE

    @property
    def active(self) -> bool:
        return self.state is PluginToolState.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "plugin_name": self.plugin_name,
            "domain": self.domain,
            "state": self.state.value,
            "reasons": list(self.reasons),
        }


__all__ = [
    "PluginManifest",
    "PluginTool",
    "PluginToolActivation",
    "PluginToolState",
    "PluginValidationError",
    "ROUTING_PERMISSIONS",
]
