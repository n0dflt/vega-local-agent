from unittest.mock import patch

import pytest

from domains.builtin import build_builtin_domain_registry
from plugins.bootstrap import PluginBootstrapError, bootstrap_plugins
from tools.registry import BUILTIN_TOOL_REGISTRY


def policy(**changes):
    data = dict(schema_version=1, enabled=False, fail_closed=True,
                allowed_modules=[], allowed_plugins=[],
                allowed_package_prefixes=["plugins.builtin"], allow_file_paths=False,
                trusted_roots=["plugins/builtin"], allow_entry_points=False,
                max_plugins=16)
    data.update(changes)
    return data


def test_disabled_bootstrap_is_empty_and_does_not_import():
    with patch("plugins.loader.resolve_module", side_effect=AssertionError("must not resolve")):
        result = bootstrap_plugins(policy(), build_builtin_domain_registry(),
                                   builtin_tools=BUILTIN_TOOL_REGISTRY)
    assert result.loaded_plugins == ()
    assert not result.plugin_handlers
    assert dict(result.tool_registry) == BUILTIN_TOOL_REGISTRY


def test_bootstrap_fails_closed_without_partial_result():
    with pytest.raises(PluginBootstrapError, match="project_root"):
        bootstrap_plugins(
            policy(enabled=True, allowed_modules=["plugins.builtin.missing"]),
            build_builtin_domain_registry(), builtin_tools=BUILTIN_TOOL_REGISTRY,
        )


@pytest.mark.parametrize("missing", ["capability_config", "permission_policy"])
def test_enabled_bootstrap_requires_activation_inputs(tmp_path, missing):
    kwargs = dict(
        project_root=tmp_path,
        builtin_tools=BUILTIN_TOOL_REGISTRY,
        capability_config={},
        permission_policy={},
    )
    kwargs[missing] = None
    with pytest.raises(PluginBootstrapError, match=missing):
        bootstrap_plugins(
            policy(enabled=True, trusted_roots=["trusted"]),
            build_builtin_domain_registry(),
            **kwargs,
        )
