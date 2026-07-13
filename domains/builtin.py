"""Factories for built-in VEGA domains."""

from __future__ import annotations

from domains.coding.domain import create_coding_domain
from domains.registry import DomainRegistry
from domains.research.domain import create_research_domain


def build_builtin_domain_registry() -> DomainRegistry:
    registry = DomainRegistry()
    registry.register(create_coding_domain())
    registry.register(create_research_domain())
    return registry


__all__ = ["build_builtin_domain_registry"]
