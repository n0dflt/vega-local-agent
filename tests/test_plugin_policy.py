import json

import pytest

from plugins.policy import PluginPolicyError, load_plugin_policy, parse_plugin_policy


def policy_data(**changes):
    data = {
        "schema_version": 1, "enabled": True, "fail_closed": True,
        "allowed_modules": ["plugins.builtin.sample"], "allowed_plugins": ["sample"],
        "allowed_package_prefixes": ["plugins.builtin"], "allow_file_paths": False,
        "trusted_roots": ["plugins/builtin"], "allow_entry_points": False,
        "max_plugins": 16,
    }
    data.update(changes)
    return data


def test_valid_and_disabled_policy():
    assert parse_plugin_policy(policy_data()).enabled
    assert not parse_plugin_policy(policy_data(enabled=False)).enabled


@pytest.mark.parametrize(
    "changes",
    [dict(unknown=True), dict(allow_file_paths=True), dict(allow_entry_points=True),
     dict(fail_closed=False), dict(max_plugins=0), dict(max_plugins=101)],
)
def test_unsafe_policy_is_rejected(changes):
    with pytest.raises(PluginPolicyError):
        parse_plugin_policy(policy_data(**changes))


def test_utf8_sig_json_is_supported(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy_data()), encoding="utf-8-sig")
    assert load_plugin_policy(path).allowed_plugins == ("sample",)


@pytest.mark.parametrize(
    "trusted_roots",
    [[""], ["../outside"], ["plugins/../outside"], ["C:/plugins"],
     ["plugins/builtin", "plugins/builtin"]],
)
def test_unsafe_trusted_roots_are_rejected(trusted_roots):
    with pytest.raises(PluginPolicyError):
        parse_plugin_policy(policy_data(trusted_roots=trusted_roots))


@pytest.mark.parametrize(
    ("field", "values"),
    [("allowed_modules", ["plugins.builtin.sample", "plugins.builtin.sample"]),
     ("allowed_plugins", ["sample", "sample"]),
     ("allowed_package_prefixes", ["plugins.builtin", "plugins.builtin"])],
)
def test_duplicate_policy_entries_are_rejected(field, values):
    with pytest.raises(PluginPolicyError):
        parse_plugin_policy(policy_data(**{field: values}))
