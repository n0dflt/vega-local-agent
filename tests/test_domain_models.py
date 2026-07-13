import pytest

from domains.models import DomainDefinition, DomainValidationError


def make_domain(**changes):
    values = dict(
        name="sample", description="Sample domain.", intents=["test_run"],
        capabilities=["project.read"], tool_names=["read_file"], enabled=True,
    )
    values.update(changes)
    return DomainDefinition(**values)


def test_valid_domain_normalizes_collections_and_round_trips():
    domain = make_domain()
    assert domain.intents == ("test_run",)
    assert domain.capabilities == ("project.read",)
    assert domain.tool_names == ("read_file",)
    assert DomainDefinition.from_dict(domain.to_dict()) == domain


@pytest.mark.parametrize("name", ["", "Coding", "bad-name"])
def test_invalid_domain_names(name):
    with pytest.raises(DomainValidationError):
        make_domain(name=name)


@pytest.mark.parametrize(
    ("field", "value"),
    [("intents", ["test_run", "test_run"]),
     ("capabilities", ["project.read", "project.read"]),
     ("tool_names", ["read_file", "read_file"])],
)
def test_duplicate_metadata_is_rejected(field, value):
    with pytest.raises(DomainValidationError):
        make_domain(**{field: value})


def test_unknown_field_and_nonboolean_enabled_are_rejected():
    data = make_domain().to_dict()
    data["unknown"] = True
    with pytest.raises(DomainValidationError):
        DomainDefinition.from_dict(data)
    with pytest.raises(DomainValidationError):
        make_domain(enabled=1)
