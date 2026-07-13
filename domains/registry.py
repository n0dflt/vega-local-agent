"""Independent, deterministic domain registries."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from domains.models import DomainDefinition, DomainValidationError, validate_domain_name


class DomainRegistryError(ValueError):
    """Raised when a domain registry operation cannot be completed."""


class DomainRegistry:
    def __init__(self) -> None:
        self._domains: dict[str, DomainDefinition] = {}

    def register(self, domain: DomainDefinition) -> None:
        if not isinstance(domain, DomainDefinition):
            raise DomainRegistryError("domain must be a DomainDefinition")
        if domain.name in self._domains:
            raise DomainRegistryError(f"Domain {domain.name!r} is already registered")
        self._domains[domain.name] = domain

    def get(self, name: str) -> DomainDefinition | None:
        return self._domains.get(self._name(name))

    def require(self, name: str) -> DomainDefinition:
        normalized = self._name(name)
        domain = self._domains.get(normalized)
        if domain is None:
            raise DomainRegistryError(f"Unknown domain: {normalized!r}")
        return domain

    def list_domains(self, *, enabled_only: bool = False) -> tuple[DomainDefinition, ...]:
        if type(enabled_only) is not bool:
            raise DomainRegistryError("enabled_only must be a boolean")
        domains = self._domains.values()
        if enabled_only:
            domains = (domain for domain in domains if domain.enabled)
        return tuple(sorted(domains, key=lambda domain: domain.name))

    def find_by_intent(self, intent: str) -> tuple[DomainDefinition, ...]:
        normalized = self._query(intent, "intent")
        return tuple(
            domain for domain in self.list_domains() if normalized in domain.intents
        )

    def find_by_capability(self, capability: str) -> tuple[DomainDefinition, ...]:
        normalized = self._query(capability, "capability")
        return tuple(
            domain for domain in self.list_domains() if normalized in domain.capabilities
        )

    def tool_names_for_domain(self, name: str) -> tuple[str, ...]:
        return tuple(sorted(self.require(name).tool_names))

    def snapshot(self) -> Mapping[str, DomainDefinition]:
        return MappingProxyType(dict(sorted(self._domains.items())))

    @staticmethod
    def _name(value: str) -> str:
        try:
            return validate_domain_name(value)
        except DomainValidationError as exc:
            raise DomainRegistryError(str(exc)) from exc

    @staticmethod
    def _query(value: str, field: str) -> str:
        if not isinstance(value, str) or not value:
            raise DomainRegistryError(f"{field} must be a non-empty string")
        if value != value.lower() or value != value.strip():
            raise DomainRegistryError(f"{field} must be normalized lowercase text")
        return value


__all__ = ["DomainRegistry", "DomainRegistryError"]
