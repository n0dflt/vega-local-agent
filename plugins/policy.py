"""Fail-closed loading for the trusted-module plugin policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from pathlib import PureWindowsPath
import re
from typing import Any, ClassVar


class PluginPolicyError(ValueError):
    """Raised when plugin policy data is unsafe or invalid."""


_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_PLUGIN = re.compile(r"^[a-z][a-z0-9_]*$")


def _string_tuple(value: Any, field: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise PluginPolicyError(f"{field} must be a list or tuple")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not pattern.fullmatch(item):
            raise PluginPolicyError(f"{field} contains an invalid value")
        result.append(item)
    if len(set(result)) != len(result):
        raise PluginPolicyError(f"{field} must not contain duplicates")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class PluginPolicy:
    schema_version: int
    enabled: bool
    fail_closed: bool
    allowed_modules: tuple[str, ...]
    allowed_plugins: tuple[str, ...]
    allowed_package_prefixes: tuple[str, ...]
    trusted_roots: tuple[str, ...]
    allow_file_paths: bool
    allow_entry_points: bool
    max_plugins: int

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version", "enabled", "fail_closed", "allowed_modules",
            "allowed_plugins", "allowed_package_prefixes", "allow_file_paths",
            "allow_entry_points", "max_plugins", "trusted_roots",
        }
    )

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise PluginPolicyError("supported schema_version is exactly 1")
        if type(self.enabled) is not bool:
            raise PluginPolicyError("enabled must be a boolean")
        if self.fail_closed is not True:
            raise PluginPolicyError("fail_closed must be true")
        object.__setattr__(
            self, "allowed_modules", _string_tuple(self.allowed_modules, "allowed_modules", _MODULE)
        )
        object.__setattr__(
            self,
            "trusted_roots",
            _trusted_root_tuple(self.trusted_roots),
        )
        object.__setattr__(
            self, "allowed_plugins", _string_tuple(self.allowed_plugins, "allowed_plugins", _PLUGIN)
        )
        object.__setattr__(
            self,
            "allowed_package_prefixes",
            _string_tuple(
                self.allowed_package_prefixes,
                "allowed_package_prefixes",
                _MODULE,
            ),
        )
        if self.allow_file_paths is not False:
            raise PluginPolicyError("allow_file_paths must be false")
        if self.allow_entry_points is not False:
            raise PluginPolicyError("allow_entry_points must be false")
        if type(self.max_plugins) is not int or not 1 <= self.max_plugins <= 100:
            raise PluginPolicyError("max_plugins must be an integer between 1 and 100")


def _trusted_root_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise PluginPolicyError("trusted_roots must be a list or tuple")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise PluginPolicyError("trusted_roots contains an invalid value")
        normalized = item.replace("\\", "/")
        parts = normalized.split("/")
        if (
            Path(item).is_absolute()
            or PureWindowsPath(item).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise PluginPolicyError(
                "trusted_roots must contain normalized relative directory paths"
            )
        result.append(normalized)
    if len(set(result)) != len(result):
        raise PluginPolicyError("trusted_roots must not contain duplicates")
    return tuple(result)


def parse_plugin_policy(data: Any) -> PluginPolicy:
    if not isinstance(data, Mapping) or not all(isinstance(key, str) for key in data):
        raise PluginPolicyError("plugin policy must be an object")
    fields = set(data)
    missing = sorted(PluginPolicy._FIELDS - fields)
    unknown = sorted(fields - PluginPolicy._FIELDS)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise PluginPolicyError("invalid plugin policy fields (" + "; ".join(details) + ")")
    return PluginPolicy(**{field: data[field] for field in PluginPolicy._FIELDS})


def load_plugin_policy(source: Mapping[str, Any] | str | Path) -> PluginPolicy:
    if isinstance(source, Mapping):
        return parse_plugin_policy(source)
    if not isinstance(source, (str, Path)):
        raise PluginPolicyError("policy source must be a mapping or filesystem path")
    try:
        raw = Path(source).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise PluginPolicyError(
            f"plugin policy could not be read: {type(exc).__name__}: {exc}"
        ) from exc
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise PluginPolicyError(
            f"plugin policy contains invalid JSON: {type(exc).__name__}: {exc}"
        ) from exc
    return parse_plugin_policy(data)


__all__ = ["PluginPolicy", "PluginPolicyError", "load_plugin_policy", "parse_plugin_policy"]
