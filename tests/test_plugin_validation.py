import pytest

from domains.builtin import build_builtin_domain_registry
from plugins.models import PluginManifest, PluginTool, PluginValidationError
from plugins.policy import parse_plugin_policy
from plugins.validation import (
    validate_manifest_domains, validate_module_allowed, validate_module_name,
    validate_tool_collisions,
)


def handler():
    return True


def manifest(domain="coding", name="plugin_echo"):
    return PluginManifest("sample", "1.0.0", "Sample plugin.", (domain,),
                          (PluginTool(name, handler, domain, "READ",
                                      ("project.read",), "Safe echo."),))


def policy(**changes):
    data = dict(schema_version=1, enabled=True, fail_closed=True,
                allowed_modules=["trusted.plugins.sample"], allowed_plugins=["sample"],
                allowed_package_prefixes=["trusted.plugins"], allow_file_paths=False,
                trusted_roots=["trusted"], allow_entry_points=False, max_plugins=4)
    data.update(changes)
    return parse_plugin_policy(data)


@pytest.mark.parametrize("name", [r"C:\\x.py", "../x", "./x", "file://x", "a..b", "a:b", "a/b"])
def test_only_dotted_module_names_are_valid(name):
    with pytest.raises(PluginValidationError):
        validate_module_name(name)


def test_allowlist_requires_exact_module_and_prefix():
    validate_module_allowed("trusted.plugins.sample", policy())
    with pytest.raises(PluginValidationError):
        validate_module_allowed("trusted.plugins.other", policy())
    with pytest.raises(PluginValidationError):
        validate_module_allowed(
            "trusted.plugins.sample", policy(allowed_package_prefixes=["other"])
        )
    with pytest.raises(PluginValidationError):
        validate_module_allowed(
            "trusted.pluginsevil.sample",
            policy(allowed_modules=["trusted.pluginsevil.sample"]),
        )


def test_domain_and_collision_validation_fail_closed():
    validate_manifest_domains(manifest(), build_builtin_domain_registry())
    with pytest.raises(PluginValidationError):
        validate_manifest_domains(manifest("unknown"), build_builtin_domain_registry())
    with pytest.raises(PluginValidationError):
        validate_tool_collisions(manifest(), {"plugin_echo": handler})
