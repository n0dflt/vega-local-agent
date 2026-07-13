"""Public Domain API. Importing this package has no plugin side effects."""

from domains.builtin import build_builtin_domain_registry
from domains.models import DomainDefinition, DomainValidationError
from domains.registry import DomainRegistry, DomainRegistryError

__all__ = [
    "DomainDefinition",
    "DomainRegistry",
    "DomainRegistryError",
    "DomainValidationError",
    "build_builtin_domain_registry",
]
