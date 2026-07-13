"""Immutable definitions for VEGA capability domains."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, ClassVar

from permissions.models import PermissionValidationError, validate_tool_name


class DomainValidationError(ValueError):
    """Raised when a domain definition violates the public schema."""


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_MAX_DESCRIPTION_LENGTH = 500


def validate_domain_name(value: Any, *, field: str = "name") -> str:
    if not isinstance(value, str):
        raise DomainValidationError(f"{field} must be a string")
    if not value:
        raise DomainValidationError(f"{field} must not be empty")
    if not _IDENTIFIER.fullmatch(value):
        raise DomainValidationError(
            f"{field} must be a normalized lowercase identifier"
        )
    return value


def _description(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError("description must be a non-empty string")
    if value != value.strip() or len(value) > _MAX_DESCRIPTION_LENGTH:
        raise DomainValidationError(
            "description must be trimmed and at most 500 characters"
        )
    return value


def _string_collection(
    value: Any,
    *,
    field: str,
    validator,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise DomainValidationError(f"{field} must be a list or tuple")
    normalized: list[str] = []
    for item in value:
        try:
            normalized.append(validator(item))
        except (DomainValidationError, PermissionValidationError) as exc:
            raise DomainValidationError(f"invalid {field} value: {exc}") from exc
    if len(set(normalized)) != len(normalized):
        raise DomainValidationError(f"{field} must not contain duplicates")
    return tuple(normalized)


def _intent(value: Any) -> str:
    return validate_domain_name(value, field="intent")


def _capability(value: Any) -> str:
    if not isinstance(value, str):
        raise DomainValidationError("capability must be a string")
    if not value or not _CAPABILITY.fullmatch(value):
        raise DomainValidationError(
            "capability must use normalized lowercase dotted notation"
        )
    return value


@dataclass(frozen=True, slots=True)
class DomainDefinition:
    """Describe one stable domain without owning tool implementations."""

    name: str
    description: str
    intents: tuple[str, ...]
    capabilities: tuple[str, ...]
    tool_names: tuple[str, ...]
    enabled: bool = True

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"name", "description", "intents", "capabilities", "tool_names", "enabled"}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", validate_domain_name(self.name))
        object.__setattr__(self, "description", _description(self.description))
        object.__setattr__(
            self,
            "intents",
            _string_collection(self.intents, field="intents", validator=_intent),
        )
        object.__setattr__(
            self,
            "capabilities",
            _string_collection(
                self.capabilities,
                field="capabilities",
                validator=_capability,
            ),
        )
        object.__setattr__(
            self,
            "tool_names",
            _string_collection(
                self.tool_names,
                field="tool_names",
                validator=validate_tool_name,
            ),
        )
        if type(self.enabled) is not bool:
            raise DomainValidationError("enabled must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "intents": list(self.intents),
            "capabilities": list(self.capabilities),
            "tool_names": list(self.tool_names),
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "DomainDefinition":
        if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
            raise DomainValidationError("domain definition must be an object")
        required = cls._FIELDS - {"enabled"}
        missing = sorted(required - set(data))
        unknown = sorted(set(data) - cls._FIELDS)
        if missing or unknown:
            details = []
            if missing:
                details.append("missing: " + ", ".join(missing))
            if unknown:
                details.append("unknown: " + ", ".join(unknown))
            raise DomainValidationError(
                "invalid domain definition fields (" + "; ".join(details) + ")"
            )
        return cls(
            name=data["name"],
            description=data["description"],
            intents=data["intents"],
            capabilities=data["capabilities"],
            tool_names=data["tool_names"],
            enabled=data.get("enabled", True),
        )


__all__ = ["DomainDefinition", "DomainValidationError", "validate_domain_name"]
