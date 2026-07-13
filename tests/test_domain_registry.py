import pytest

from domains.models import DomainDefinition
from domains.registry import DomainRegistry, DomainRegistryError


def domain(name, *, enabled=True):
    return DomainDefinition(name, f"{name} domain.", ("test_run",),
                            ("project.read",), ("read_file",), enabled)


def test_registry_api_is_sorted_and_searchable():
    registry = DomainRegistry()
    registry.register(domain("zeta"))
    registry.register(domain("alpha"))
    assert registry.get("alpha").name == "alpha"
    assert registry.require("zeta").name == "zeta"
    assert tuple(item.name for item in registry.list_domains()) == ("alpha", "zeta")
    assert tuple(item.name for item in registry.find_by_intent("test_run")) == ("alpha", "zeta")
    assert len(registry.find_by_capability("project.read")) == 2
    assert registry.tool_names_for_domain("alpha") == ("read_file",)


def test_duplicates_unknown_and_snapshot_mutation_fail():
    registry = DomainRegistry()
    registry.register(domain("alpha"))
    with pytest.raises(DomainRegistryError):
        registry.register(domain("alpha"))
    with pytest.raises(DomainRegistryError):
        registry.require("missing")
    with pytest.raises(TypeError):
        registry.snapshot()["other"] = domain("other")


def test_instances_are_independent_and_enabled_filter_works():
    first, second = DomainRegistry(), DomainRegistry()
    first.register(domain("alpha", enabled=False))
    assert first.list_domains(enabled_only=True) == ()
    assert second.list_domains() == ()
